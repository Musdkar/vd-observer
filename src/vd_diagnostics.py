from __future__ import annotations

import ipaddress
import json
from pathlib import Path
from typing import Any, Iterable


VD_SESSION_PORTS = {38810, 38820, 38830, 38840}
STREAMER_PROCESS = "virtualdesktop.streamer.exe"
SERVER_PROCESS = "virtualdesktop.server.exe"
SUCCESS_STATUS = "session_established"
STATUS_RANK = {
    "streamer_not_running": 0,
    "streamer_running_no_cloud_evidence": 1,
    "cloud_registration_blocked": 1,
    "cloud_connected_waiting_for_headset": 2,
    "partial_headset_session": 3,
    "session_established": 4,
}


def _is_private(value: str | None) -> bool:
    if not value:
        return False
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return address.is_private


def _is_loopback(value: str | None) -> bool:
    if not value:
        return False
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


def _is_tun_benchmark(value: str | None) -> bool:
    if not value:
        return False
    try:
        return ipaddress.ip_address(value) in ipaddress.ip_network("198.18.0.0/15")
    except ValueError:
        return False


def _process_name(event: dict[str, Any]) -> str:
    return str(event.get("data", {}).get("name", "")).lower()


def _connection(event: dict[str, Any]) -> dict[str, Any] | None:
    if event.get("category") != "network":
        return None
    if event.get("event") != "connection_observed":
        return None
    return event.get("data", {})


def _endpoint(connection: dict[str, Any], side: str) -> tuple[str | None, int | None]:
    endpoint = connection.get(side) or {}
    return endpoint.get("ip"), endpoint.get("port")


def analyze_events(
    events: Iterable[dict[str, Any]],
    environment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    event_list = list(events)
    processes = {
        _process_name(event)
        for event in event_list
        if event.get("category") == "process"
        and event.get("event") in {"process_observed", "process_started"}
    }
    connections = [
        connection
        for event in event_list
        if (connection := _connection(event)) is not None
    ]

    streamer_seen = STREAMER_PROCESS in processes
    server_seen = SERVER_PROCESS in processes
    established_public = []
    stalled_public = []
    local_session_connections = []
    proxy_connections = []
    tun_connections = []

    for connection in connections:
        local_ip, local_port = _endpoint(connection, "local")
        remote_ip, remote_port = _endpoint(connection, "remote")
        status = str(connection.get("status", "")).upper()
        transport = str(connection.get("transport", "")).upper()
        is_tcp = transport in {"TCP", "1", "SOCK_STREAM"}

        if _is_loopback(local_ip) and _is_loopback(remote_ip):
            proxy_connections.append(connection)
        if _is_tun_benchmark(local_ip):
            tun_connections.append(connection)

        if remote_ip and not _is_private(remote_ip) and is_tcp:
            if status == "ESTABLISHED":
                established_public.append(connection)
            elif status == "SYN_SENT":
                stalled_public.append(connection)

        if (
            is_tcp
            and status == "ESTABLISHED"
            and _is_private(local_ip)
            and _is_private(remote_ip)
            and local_port in VD_SESSION_PORTS
        ):
            local_session_connections.append(connection)

    connected_ports = sorted(
        {
            _endpoint(connection, "local")[1]
            for connection in local_session_connections
            if _endpoint(connection, "local")[1] is not None
        }
    )
    missing_ports = sorted(VD_SESSION_PORTS - set(connected_ports))
    headset_ips = sorted(
        {
            _endpoint(connection, "remote")[0]
            for connection in local_session_connections
            if _endpoint(connection, "remote")[0]
        }
    )

    adapter_names = []
    tun_adapter_names = []
    if environment:
        for name, adapter in environment.get("network_adapters", {}).items():
            adapter_names.append(name)
            addresses = adapter.get("addresses", [])
            if any(_is_tun_benchmark(item.get("address")) for item in addresses):
                tun_adapter_names.append(name)

    findings: list[dict[str, str]] = []
    actions: list[str] = []

    if not streamer_seen:
        status = "streamer_not_running"
        summary = "Virtual Desktop Streamer was not observed."
        actions.append("Start Virtual Desktop Streamer, then capture a new session.")
    elif not missing_ports:
        status = SUCCESS_STATUS
        target = ", ".join(headset_ips) or "the headset"
        summary = f"Virtual Desktop established all four session channels with {target}."
    elif connected_ports:
        status = "partial_headset_session"
        summary = (
            "The headset reached the PC, but the Virtual Desktop session is incomplete."
        )
        actions.append(
            "Restart Virtual Desktop Streamer and check rules for the missing VD ports."
        )
    elif stalled_public and not established_public:
        status = "cloud_registration_blocked"
        summary = "Streamer cloud connections remained in SYN_SENT."
        actions.append(
            "Bypass VPN/TUN/proxy handling for Virtual Desktop and restart Streamer."
        )
    elif established_public:
        status = "cloud_connected_waiting_for_headset"
        summary = "Streamer reached its cloud service, but no headset session appeared."
        actions.append(
            "Keep the headset awake on the Computers screen and restart Streamer."
        )
    else:
        status = "streamer_running_no_cloud_evidence"
        summary = "Streamer was running, but no cloud or headset connection was observed."
        actions.append("Capture for longer while reproducing the connection attempt.")

    if stalled_public:
        resolved = status == SUCCESS_STATUS or bool(established_public)
        findings.append(
            {
                "code": "public_syn_sent",
                "severity": "notice" if resolved else "warning",
                "message": (
                    f"{len(stalled_public)} public connection observation(s) stalled "
                    "in SYN_SENT."
                    + (
                        " Later connection evidence shows that this was transient."
                        if resolved
                        else ""
                    )
                ),
            }
        )
    if proxy_connections:
        peers = sorted(
            {
                str(connection.get("peer_process", {}).get("name"))
                for connection in proxy_connections
                if connection.get("peer_process", {}).get("name")
            }
        )
        peer_text = f" Peer process: {', '.join(peers)}." if peers else ""
        findings.append(
            {
                "code": "loopback_proxy",
                "severity": "notice",
                "message": (
                    f"Streamer used {len(proxy_connections)} loopback proxy "
                    f"connection(s).{peer_text}"
                ),
            }
        )
    if tun_connections or tun_adapter_names:
        names = f" ({', '.join(tun_adapter_names)})" if tun_adapter_names else ""
        findings.append(
            {
                "code": "tun_detected",
                "severity": "notice",
                "message": f"A 198.18.0.0/15 TUN path was observed{names}.",
            }
        )
    if connected_ports:
        findings.append(
            {
                "code": "vd_session_ports",
                "severity": "info",
                "message": (
                    f"Connected VD ports: {', '.join(map(str, connected_ports))}; "
                    f"missing: {', '.join(map(str, missing_ports)) or 'none'}."
                ),
            }
        )
    if server_seen:
        findings.append(
            {
                "code": "server_started",
                "severity": "info",
                "message": "VirtualDesktop.Server.exe was observed.",
            }
        )

    return {
        "diagnostic_version": "0.1.0",
        "status": status,
        "success": status == SUCCESS_STATUS,
        "summary": summary,
        "signals": {
            "streamer_seen": streamer_seen,
            "server_seen": server_seen,
            "cloud_established_count": len(established_public),
            "cloud_syn_sent_count": len(stalled_public),
            "connected_session_ports": connected_ports,
            "missing_session_ports": missing_ports,
            "headset_ips": headset_ips,
            "tun_adapter_names": tun_adapter_names,
            "network_adapter_names": sorted(adapter_names),
        },
        "findings": findings,
        "recommended_actions": actions,
    }


def read_events(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def analyze_session(directory: Path) -> dict[str, Any]:
    environment_path = directory / "environment.json"
    environment = (
        json.loads(environment_path.read_text(encoding="utf-8"))
        if environment_path.exists()
        else {}
    )
    return analyze_events(read_events(directory / "events.jsonl"), environment)


def render_text_report(report: dict[str, Any]) -> str:
    lines = [
        "VD Observer Diagnostic Report",
        "=============================",
        f"Status:  {report['status']}",
        f"Result:  {'success' if report['success'] else 'attention needed'}",
        f"Summary: {report['summary']}",
        "",
        "Evidence",
        "--------",
    ]
    findings = report.get("findings", [])
    if findings:
        lines.extend(
            f"- [{finding['severity']}] {finding['message']}" for finding in findings
        )
    else:
        lines.append("- No additional findings.")

    lines.extend(["", "Recommended actions", "-------------------"])
    actions = report.get("recommended_actions", [])
    if actions:
        lines.extend(f"- {action}" for action in actions)
    else:
        lines.append("- No action required.")
    return "\n".join(lines) + "\n"


def write_reports(directory: Path, report: dict[str, Any]) -> None:
    (directory / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (directory / "report.txt").write_text(
        render_text_report(report),
        encoding="utf-8",
    )


def compare_reports(
    before: dict[str, Any],
    after: dict[str, Any],
) -> dict[str, Any]:
    before_status = before["status"]
    after_status = after["status"]
    before_rank = STATUS_RANK.get(before_status, -1)
    after_rank = STATUS_RANK.get(after_status, -1)

    if not before.get("success") and after.get("success"):
        result = "resolved"
        summary = "The later session established a complete VD headset session."
    elif after_rank > before_rank:
        result = "improved"
        summary = "The later session progressed further through the VD connection flow."
    elif after_rank < before_rank:
        result = "regressed"
        summary = "The later session regressed to an earlier VD connection stage."
    elif before_status == after_status:
        result = "unchanged"
        summary = "Both sessions ended in the same diagnostic state."
    else:
        result = "changed"
        summary = "The diagnostic state changed without a clear rank difference."

    before_signals = before.get("signals", {})
    after_signals = after.get("signals", {})
    changes = {
        "cloud_established_count": {
            "before": before_signals.get("cloud_established_count", 0),
            "after": after_signals.get("cloud_established_count", 0),
        },
        "cloud_syn_sent_count": {
            "before": before_signals.get("cloud_syn_sent_count", 0),
            "after": after_signals.get("cloud_syn_sent_count", 0),
        },
        "connected_session_ports": {
            "before": before_signals.get("connected_session_ports", []),
            "after": after_signals.get("connected_session_ports", []),
        },
        "headset_ips": {
            "before": before_signals.get("headset_ips", []),
            "after": after_signals.get("headset_ips", []),
        },
    }
    return {
        "comparison_version": "0.1.0",
        "result": result,
        "summary": summary,
        "before_status": before_status,
        "after_status": after_status,
        "changes": changes,
    }


def compare_sessions(before_directory: Path, after_directory: Path) -> dict[str, Any]:
    return compare_reports(
        analyze_session(before_directory),
        analyze_session(after_directory),
    )


def render_comparison(comparison: dict[str, Any]) -> str:
    changes = comparison["changes"]
    return "\n".join(
        [
            "VD Observer Session Comparison",
            "==============================",
            f"Result: {comparison['result']}",
            f"Before: {comparison['before_status']}",
            f"After:  {comparison['after_status']}",
            f"Summary: {comparison['summary']}",
            "",
            "Signal changes",
            "--------------",
            (
                "- Cloud established observations: "
                f"{changes['cloud_established_count']['before']} -> "
                f"{changes['cloud_established_count']['after']}"
            ),
            (
                "- Cloud SYN_SENT observations: "
                f"{changes['cloud_syn_sent_count']['before']} -> "
                f"{changes['cloud_syn_sent_count']['after']}"
            ),
            (
                "- Connected VD ports: "
                f"{changes['connected_session_ports']['before']} -> "
                f"{changes['connected_session_ports']['after']}"
            ),
            (
                "- Headset IPs: "
                f"{changes['headset_ips']['before']} -> "
                f"{changes['headset_ips']['after']}"
            ),
            "",
        ]
    )
