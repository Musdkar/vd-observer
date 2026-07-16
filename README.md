# VD Observer

[![CI](https://github.com/Musdkar/vd-observer/actions/workflows/ci.yml/badge.svg)](https://github.com/Musdkar/vd-observer/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

[English](README.md) | [简体中文](README.zh-CN.md)

A Windows local observation tool for reproducing Virtual Desktop faults.

VD Observer records process, resource, and network changes in the Virtual Desktop and related VR runtime environment, and saves the data as structured logs for further analysis by AI or technical staff. It only collects verifiable runtime facts and does not attempt to automatically determine the cause of faults.

> [!IMPORTANT]
> The current version is `0.1.0-alpha.1`; the interface and log format may still change. This is an unofficial tool and is not affiliated with Virtual Desktop, Inc.

## Why It's Needed

Black screens, stuttering, stream drops, unresponsiveness, and abnormal exits often involve VD, SteamVR, OpenXR, GPU drivers, the network, and the Windows system environment at the same time. Relevant clues are scattered across different locations, and intermittent issues are hard to reconstruct after the fact.

VD Observer puts this information into a single session and timeline, allowing analysts to answer:

- Which processes started, exited, or disappeared around the time of the issue?
- What were the CPU, memory, and thread states of the target processes at that moment?
- When were network connections established, changed, or dropped?
- Are user-marked fault moments adjacent to system events?
- Which collector do the logs come from, and is the time ordering reliable?

## Current Capabilities

- Creates an independent session for each collection run
- Saves a unified event stream using JSON Lines
- Records UTC, local time, and monotonic time simultaneously
- Discovers and tracks VD, SteamVR, and Meta/Oculus related processes
- Periodically samples CPU, memory, and thread count of target processes
- Records TCP/UDP connection changes of target processes
- Saves Windows, Python, and network environment snapshots
- Supports adding user fault marks during reproduction
- Generates JSONL, JSON, and CSV files that AI can read directly

VD Observer does not inject into or modify the Virtual Desktop process, nor does it proxy, decrypt, or save network communication content by default.

## Requirements

- Windows 10 or Windows 11
- Python 3.10 or later
- [`psutil`](https://pypi.org/project/psutil/)

Install dependencies:

```powershell
python -m pip install -r requirements.txt
```

## Quick Start

Clone and enter the project directory:

```powershell
git clone https://github.com/Musdkar/vd-observer.git
cd vd-observer
```

Start collection, press `Ctrl+C` to stop:

```powershell
python src\vd_observer.py
```

Collect for a fixed duration, e.g. 60 seconds:

```powershell
python src\vd_observer.py --duration 60
```

By default, the following processes are observed:

- `VirtualDesktop.Streamer.exe`
- `VirtualDesktop.Server.exe`
- `vrserver.exe`
- `vrmonitor.exe`
- `OVRServer_x64.exe`

You can repeat `--process` to observe custom processes:

```powershell
python src\vd_observer.py --process VirtualDesktop.Streamer.exe --process vrserver.exe
```

During a run, type any text and press Enter to add a fault mark on the timeline; type `quit` to end collection early.

## Command-Line Arguments

```text
--process NAME     Process name to observe; can be specified multiple times
--interval SEC     Sampling interval, default 1 second, minimum 0.1 seconds
--duration SEC     Collection duration; default 0 means run continuously
--output PATH      Session output directory, default sessions
```

Check the program version:

```powershell
python src\vd_observer.py --version
```

## Session Output

Each run creates a session directory with a timestamp and a random identifier:

```text
sessions/<session-id>/
|-- manifest.json
|-- environment.json
|-- events.jsonl
`-- metrics.csv
```

| File | Content |
| --- | --- |
| `manifest.json` | Session ID, format version, collection scope, start/end time, and end reason |
| `environment.json` | Static snapshot of operating system, hardware, and network adapters |
| `events.jsonl` | Unified event stream composed of process, network, session, and user marks |
| `metrics.csv` | Periodic resource sampling data for target processes |

Each line in `events.jsonl` is an independent JSON object. Events contain session ID, data format version, timestamp, monotonic time, source, category, severity, and specific data, making it convenient for AI to filter and correlate by time window.

## Privacy & Data Safety

All logs are saved locally by default; the project does not automatically upload session data. `sessions/` is ignored by Git.

Runtime logs may contain the following sensitive information:

- Hostname
- Network adapter names, IP, IPv6, MAC addresses, and subnet masks
- Process executable file paths
- Remote connection addresses and ports
- User-entered fault marks

The current prototype does not yet provide automatic redaction export. Before submitting logs to Issues, forums, cloud AI, or any other third party, please review and remove any information you do not want to make public. Do not submit passwords, access tokens, Wi-Fi keys, or unchecked crash dumps.

## Known Limitations

- Currently only a command-line collector; no DevTools GUI yet.
- Windows Event Log, ETW, GPU encoder, and detailed VR Runtime state are not yet collected.
- Cannot guarantee that the default process names cover all VD or VR Runtime versions.
- Passive network observation can only see connection metadata, not encrypted communication content.
- Data for some system or other-user processes may be unavailable due to Windows permission restrictions.
- The current version does not yet provide ring buffering or redaction export.

## Roadmap

- Windows Event Log and application crash event collection
- GPU, video memory, video encoding, and network quality metrics
- SteamVR, OpenXR, and Meta/Oculus Runtime status
- Configurable ring buffer and "save the N minutes before a fault"
- Session browsing, search, filtering, and timeline interface
- Previewable, field-selectable redaction export
- Stable event schema and compatibility testing

## Feedback & Contributing

Contributions via GitHub Issues are welcome for problems, feature suggestions, and redacted reproduction information. An effective fault sample usually includes:

- What the user actually observed
- Approximate time of occurrence and the corresponding user mark
- Repeatable reproduction steps
- Versions of VD, Windows, GPU driver, and headset
- OpenXR Runtime used and network connection method
- Reviewed and redacted VD Observer session logs

Before submitting, you may refer to [`docs/error-example-template.md`](docs/error-example-template.md).

Run the basic tests:

```powershell
python -m unittest discover -s tests -v
```

## License

This project is licensed under the [MIT License](LICENSE).
