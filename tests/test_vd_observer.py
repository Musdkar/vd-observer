from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import vd_observer  # noqa: E402
from vd_diagnostics import (  # noqa: E402
    analyze_events,
    compare_reports,
    render_comparison,
    render_text_report,
)


class SessionWriterTests(unittest.TestCase):
    def test_session_writes_valid_event_metric_and_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            writer = vd_observer.SessionWriter(root, {"example.exe"}, 1.0)
            writer.event(
                "test-collector",
                "test",
                "sample_event",
                {"value": 42},
            )
            writer.close("test_completed")

            manifest = json.loads(
                (writer.directory / "manifest.json").read_text(encoding="utf-8")
            )
            events = [
                json.loads(line)
                for line in (writer.directory / "events.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            with (writer.directory / "metrics.csv").open(
                encoding="utf-8", newline=""
            ) as metric_file:
                metric_rows = list(csv.reader(metric_file))

            self.assertEqual(manifest["schema_version"], vd_observer.SCHEMA_VERSION)
            self.assertEqual(manifest["status"], "completed")
            self.assertEqual(manifest["end_reason"], "test_completed")
            self.assertEqual(events[0]["event"], "sample_event")
            self.assertEqual(events[0]["data"], {"value": 42})
            self.assertEqual(events[0]["session_id"], writer.session_id)
            self.assertEqual(len(metric_rows), 1)


class ArgumentTests(unittest.TestCase):
    def test_project_name_includes_log_keyword(self) -> None:
        self.assertEqual(vd_observer.APP_NAME, "vd-log-observer")
        self.assertEqual(vd_observer.APP_DISPLAY_NAME, "VD Log Observer")

    def test_version_is_alpha_release(self) -> None:
        self.assertEqual(vd_observer.APP_VERSION, "0.2.0-alpha.1")


def process_event(name: str, event: str = "process_observed") -> dict:
    return {
        "category": "process",
        "event": event,
        "data": {"name": name},
    }


def connection_event(
    local_ip: str,
    local_port: int,
    remote_ip: str,
    remote_port: int,
    status: str,
    **extra: object,
) -> dict:
    data = {
        "transport": "TCP",
        "status": status,
        "local": {"ip": local_ip, "port": local_port},
        "remote": {"ip": remote_ip, "port": remote_port},
    }
    data.update(extra)
    return {"category": "network", "event": "connection_observed", "data": data}


class DiagnosticTests(unittest.TestCase):
    def test_diagnoses_cloud_registration_blocked_by_tun(self) -> None:
        events = [
            process_event("VirtualDesktop.Streamer.exe"),
            connection_event(
                "127.0.0.1",
                51103,
                "127.0.0.1",
                1080,
                "ESTABLISHED",
                peer_process={"pid": 4242, "name": "ExampleProxyCore.exe"},
            ),
            connection_event(
                "198.18.0.1",
                38810,
                "93.184.216.34",
                38811,
                "SYN_SENT",
            ),
        ]
        environment = {
            "network_adapters": {
                "Example TUN": {
                    "addresses": [{"address": "198.18.0.1"}],
                }
            }
        }

        report = analyze_events(events, environment)

        self.assertEqual(report["status"], "cloud_registration_blocked")
        self.assertFalse(report["success"])
        self.assertEqual(report["signals"]["cloud_syn_sent_count"], 1)
        self.assertEqual(report["signals"]["tun_adapter_names"], ["Example TUN"])
        messages = " ".join(item["message"] for item in report["findings"])
        self.assertIn("ExampleProxyCore.exe", messages)

    def test_diagnoses_cloud_connected_but_no_headset_session(self) -> None:
        events = [
            process_event("VirtualDesktop.Streamer.exe"),
            connection_event(
                "198.18.0.1",
                38810,
                "93.184.216.34",
                38814,
                "ESTABLISHED",
            ),
        ]

        report = analyze_events(events)

        self.assertEqual(report["status"], "cloud_connected_waiting_for_headset")
        self.assertEqual(report["signals"]["connected_session_ports"], [])

    def test_diagnoses_complete_local_session(self) -> None:
        events = [
            process_event("VirtualDesktop.Streamer.exe"),
            process_event("VirtualDesktop.Server.exe", "process_started"),
        ]
        for index, port in enumerate(sorted({38810, 38820, 38830, 38840})):
            events.append(
                connection_event(
                    "10.20.30.10",
                    port,
                    "10.20.30.42",
                    35000 + index,
                    "ESTABLISHED",
                )
            )

        report = analyze_events(events)
        text_report = render_text_report(report)

        self.assertEqual(report["status"], "session_established")
        self.assertTrue(report["success"])
        self.assertEqual(
            report["signals"]["connected_session_ports"],
            [38810, 38820, 38830, 38840],
        )
        self.assertEqual(report["signals"]["headset_ips"], ["10.20.30.42"])
        self.assertIn("No action required.", text_report)
        self.assertIn("VD Log Observer Diagnostic Report", text_report)

    def test_diagnoses_partial_headset_session(self) -> None:
        events = [
            process_event("VirtualDesktop.Streamer.exe"),
            connection_event(
                "10.20.30.10",
                38810,
                "10.20.30.42",
                35000,
                "ESTABLISHED",
            ),
        ]

        report = analyze_events(events)

        self.assertEqual(report["status"], "partial_headset_session")
        self.assertEqual(
            report["signals"]["missing_session_ports"],
            [38820, 38830, 38840],
        )

    def test_compares_blocked_and_successful_sessions_as_resolved(self) -> None:
        before = analyze_events(
            [
                process_event("VirtualDesktop.Streamer.exe"),
                connection_event(
                    "198.18.0.1",
                    38810,
                    "93.184.216.34",
                    38811,
                    "SYN_SENT",
                ),
            ]
        )
        success_events = [
            process_event("VirtualDesktop.Streamer.exe"),
            process_event("VirtualDesktop.Server.exe", "process_started"),
        ]
        for index, port in enumerate(sorted({38810, 38820, 38830, 38840})):
            success_events.append(
                connection_event(
                    "10.20.30.10",
                    port,
                    "10.20.30.42",
                    35000 + index,
                    "ESTABLISHED",
                )
            )
        after = analyze_events(success_events)

        comparison = compare_reports(before, after)

        self.assertEqual(comparison["result"], "resolved")
        self.assertEqual(comparison["before_status"], "cloud_registration_blocked")
        self.assertEqual(comparison["after_status"], "session_established")
        self.assertIn("38840", render_comparison(comparison))


if __name__ == "__main__":
    unittest.main()
