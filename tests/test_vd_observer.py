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
    def test_version_is_alpha_release(self) -> None:
        self.assertEqual(vd_observer.APP_VERSION, "0.1.0-alpha.1")


if __name__ == "__main__":
    unittest.main()
