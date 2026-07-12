from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import platform
import queue
import socket
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import psutil


APP_VERSION = "0.1.0-alpha.1"
SCHEMA_VERSION = "0.1.0"
DEFAULT_PROCESSES = (
    "VirtualDesktop.Streamer.exe",
    "VirtualDesktop.Server.exe",
    "vrserver.exe",
    "vrmonitor.exe",
    "OVRServer_x64.exe",
)


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds")


def local_now() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="milliseconds")


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


class SessionWriter:
    def __init__(self, root: Path, watched_names: set[str], interval: float):
        started = dt.datetime.now().astimezone()
        self.session_id = f"{started:%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:8]}"
        self.directory = root / self.session_id
        self.directory.mkdir(parents=True, exist_ok=False)
        self.started_monotonic = time.monotonic()
        self.started_utc = utc_now()
        self.event_file = (self.directory / "events.jsonl").open("w", encoding="utf-8")
        self.metric_file = (self.directory / "metrics.csv").open(
            "w", encoding="utf-8", newline=""
        )
        self.metric_writer = csv.DictWriter(
            self.metric_file,
            fieldnames=(
                "timestamp_utc",
                "monotonic_ms",
                "pid",
                "process_name",
                "cpu_percent",
                "memory_rss_bytes",
                "thread_count",
            ),
        )
        self.metric_writer.writeheader()
        self.manifest: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "session_id": self.session_id,
            "started_at_utc": self.started_utc,
            "started_at_local": local_now(),
            "watched_process_names": sorted(watched_names),
            "sample_interval_seconds": interval,
            "status": "recording",
            "files": {
                "events": "events.jsonl",
                "metrics": "metrics.csv",
                "environment": "environment.json",
            },
        }
        write_json(self.directory / "manifest.json", self.manifest)

    def monotonic_ms(self) -> int:
        return round((time.monotonic() - self.started_monotonic) * 1000)

    def event(
        self,
        source: str,
        category: str,
        event: str,
        data: dict[str, Any],
        severity: str = "info",
    ) -> None:
        row = {
            "schema_version": SCHEMA_VERSION,
            "session_id": self.session_id,
            "timestamp_utc": utc_now(),
            "timestamp_local": local_now(),
            "monotonic_ms": self.monotonic_ms(),
            "source": source,
            "category": category,
            "event": event,
            "severity": severity,
            "data": data,
        }
        self.event_file.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        self.event_file.flush()

    def metric(self, process: psutil.Process) -> None:
        try:
            with process.oneshot():
                row = {
                    "timestamp_utc": utc_now(),
                    "monotonic_ms": self.monotonic_ms(),
                    "pid": process.pid,
                    "process_name": process.name(),
                    "cpu_percent": process.cpu_percent(None),
                    "memory_rss_bytes": process.memory_info().rss,
                    "thread_count": process.num_threads(),
                }
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return
        self.metric_writer.writerow(row)
        self.metric_file.flush()

    def close(self, reason: str) -> None:
        self.event_file.close()
        self.metric_file.close()
        self.manifest.update(
            {
                "status": "completed",
                "ended_at_utc": utc_now(),
                "duration_ms": self.monotonic_ms(),
                "end_reason": reason,
            }
        )
        write_json(self.directory / "manifest.json", self.manifest)


def environment_snapshot() -> dict[str, Any]:
    adapters: dict[str, Any] = {}
    stats = psutil.net_if_stats()
    for name, addresses in psutil.net_if_addrs().items():
        adapters[name] = {
            "is_up": stats[name].isup if name in stats else None,
            "speed_mbps": stats[name].speed if name in stats else None,
            "addresses": [
                {
                    "family": str(address.family),
                    "address": address.address,
                    "netmask": address.netmask,
                }
                for address in addresses
            ],
        }
    return {
        "captured_at_utc": utc_now(),
        "hostname": socket.gethostname(),
        "os": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "architecture": platform.machine(),
        },
        "python": sys.version,
        "cpu_logical_count": psutil.cpu_count(logical=True),
        "memory_total_bytes": psutil.virtual_memory().total,
        "network_adapters": adapters,
    }


def matching_processes(names: set[str]) -> dict[int, psutil.Process]:
    matches: dict[int, psutil.Process] = {}
    lowered = {name.lower() for name in names}
    for process in psutil.process_iter(("pid", "name")):
        try:
            if (process.info["name"] or "").lower() in lowered:
                matches[process.pid] = process
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return matches


def connection_key(connection: Any) -> tuple[Any, ...]:
    local = tuple(connection.laddr) if connection.laddr else (None, None)
    remote = tuple(connection.raddr) if connection.raddr else (None, None)
    return (connection.pid, str(connection.type), local, remote, connection.status)


def connection_data(connection: Any) -> dict[str, Any]:
    local = connection.laddr if connection.laddr else None
    remote = connection.raddr if connection.raddr else None
    return {
        "pid": connection.pid,
        "transport": str(connection.type),
        "status": connection.status,
        "local": {"ip": local.ip, "port": local.port} if local else None,
        "remote": {"ip": remote.ip, "port": remote.port} if remote else None,
    }


def input_worker(messages: queue.Queue[str], stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            value = input().strip()
        except EOFError:
            return
        messages.put(value)
        if value.lower() == "quit":
            return


def run(args: argparse.Namespace) -> int:
    watched = set(args.process or DEFAULT_PROCESSES)
    writer = SessionWriter(Path(args.output), watched, args.interval)
    write_json(writer.directory / "environment.json", environment_snapshot())
    writer.event(
        "vd-observer",
        "session",
        "session_started",
        {"watched_process_names": sorted(watched)},
    )
    print(f"Session: {writer.session_id}")
    print(f"Output:  {writer.directory.resolve()}")
    print("Type a problem marker and press Enter; type 'quit' to stop.")

    stop = threading.Event()
    messages: queue.Queue[str] = queue.Queue()
    threading.Thread(target=input_worker, args=(messages, stop), daemon=True).start()
    known_processes: dict[int, psutil.Process] = {}
    known_connections: set[tuple[Any, ...]] = set()
    deadline = time.monotonic() + args.duration if args.duration > 0 else None
    reason = "duration_elapsed"

    try:
        while deadline is None or time.monotonic() < deadline:
            while not messages.empty():
                marker = messages.get_nowait()
                if marker.lower() == "quit":
                    reason = "user_requested"
                    return 0
                if marker:
                    writer.event(
                        "user",
                        "marker",
                        "problem_marker",
                        {"text": marker},
                        severity="notice",
                    )

            current = matching_processes(watched)
            for pid, process in current.items():
                if pid not in known_processes:
                    try:
                        data = {
                            "pid": pid,
                            "name": process.name(),
                            "executable": process.exe(),
                            "created_at_utc": dt.datetime.fromtimestamp(
                                process.create_time(), dt.timezone.utc
                            ).isoformat(timespec="milliseconds"),
                        }
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
                    writer.event("process-monitor", "process", "process_started", data)
                    process.cpu_percent(None)

                writer.metric(process)

            for pid, process in list(known_processes.items()):
                if pid not in current:
                    writer.event(
                        "process-monitor",
                        "process",
                        "process_disappeared",
                        {"pid": pid, "name": process.info.get("name")},
                        severity="warning",
                    )

            current_connections: set[tuple[Any, ...]] = set()
            try:
                for connection in psutil.net_connections(kind="inet"):
                    if connection.pid not in current:
                        continue
                    key = connection_key(connection)
                    current_connections.add(key)
                    if key not in known_connections:
                        writer.event(
                            "network-monitor",
                            "network",
                            "connection_observed",
                            connection_data(connection),
                        )
            except psutil.AccessDenied:
                writer.event(
                    "network-monitor",
                    "collector",
                    "collection_unavailable",
                    {"reason": "access_denied"},
                    severity="warning",
                )

            for key in known_connections - current_connections:
                writer.event(
                    "network-monitor",
                    "network",
                    "connection_no_longer_observed",
                    {"connection_key": list(key)},
                )

            known_processes = current
            known_connections = current_connections
            time.sleep(args.interval)
    except KeyboardInterrupt:
        reason = "keyboard_interrupt"
    finally:
        stop.set()
        writer.event("vd-observer", "session", "session_ended", {"reason": reason})
        writer.close(reason)
        print(f"Saved: {writer.directory.resolve()}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Observe VD-related Windows processes.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {APP_VERSION}")
    parser.add_argument(
        "--process",
        action="append",
        help="Process name to watch. Repeat for multiple names.",
    )
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument(
        "--duration",
        type=float,
        default=0,
        help="Seconds to capture; zero runs until stopped.",
    )
    parser.add_argument("--output", default="sessions")
    args = parser.parse_args()
    if args.interval < 0.1:
        parser.error("--interval must be at least 0.1 seconds")
    if args.duration < 0:
        parser.error("--duration cannot be negative")
    return args


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
