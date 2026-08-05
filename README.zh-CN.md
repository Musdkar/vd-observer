# VD Log Observer

[![CI](https://github.com/Musdkar/vd-log-observer/actions/workflows/ci.yml/badge.svg)](https://github.com/Musdkar/vd-log-observer/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

[English](README.md) | [简体中文](README.zh-CN.md)

面向 Virtual Desktop 故障复现的 Windows 本地日志采集与诊断工具。

VD Log Observer 通过记录 Virtual Desktop 及相关 VR 运行环境中的进程、资源和网络变化来采集 VD 日志，将数据保存为结构化日志，并为 AI、技术人员和普通用户生成基于证据的诊断摘要。

> [!IMPORTANT]
> 当前版本为 `0.2.0-alpha.1`，接口和日志格式仍可能发生变化。本项目是非官方工具，与 Virtual Desktop, Inc. 没有关联。

## 为什么需要它

黑屏、卡顿、断流、无响应和异常退出往往同时涉及 VD、SteamVR、OpenXR、显卡驱动、网络与 Windows 系统环境。相关线索分散在不同位置，而且偶发问题很难事后还原。

VD Log Observer 将这些信息放进同一个会话和时间轴，让分析者能够回答：

- 问题发生前后有哪些进程启动、退出或消失？
- 当时目标进程的 CPU、内存和线程状态如何？
- 网络连接在什么时间建立、改变或消失？
- 用户标记的故障时刻与系统事件是否相邻？
- 日志来自哪个采集器，时间顺序是否可靠？

## 当前能力

- 为每次采集创建独立会话
- 使用 JSON Lines 保存统一事件流
- 同时记录 UTC、本地时间和单调时间
- 发现并跟踪 VD、SteamVR 和 Meta/Oculus 相关进程
- 周期采集目标进程的 CPU、内存和线程数量
- 记录目标进程的 TCP/UDP 连接变化
- 保存 Windows、Python 和网络环境快照
- 支持在复现过程中添加用户故障标记
- 生成可供 AI 直接读取的 JSONL、JSON 和 CSV 文件
- 自动生成 `report.txt` 和 `report.json` 诊断报告
- 区分 VD 云端注册、头显会话和端口不完整等故障阶段
- 识别常见 TUN（`198.18.0.0/15`）与本机环回代理迹象

VD Log Observer 不会注入或修改 Virtual Desktop 进程，也不会默认代理、解密或保存网络通信正文。

## 环境要求

- Windows 10 或 Windows 11
- Python 3.10 或更高版本
- [`psutil`](https://pypi.org/project/psutil/)

安装依赖：

```powershell
python -m pip install -r requirements.txt
```

## 快速开始

克隆并进入项目目录：

```powershell
git clone https://github.com/Musdkar/vd-log-observer.git
cd vd-log-observer
```

启动采集，按 `Ctrl+C` 停止：

```powershell
python src\vd_observer.py
```

采集固定时长，例如 60 秒：

```powershell
python src\vd_observer.py --duration 60
```

每次采集结束后会显示可读诊断，并把报告保存在原始证据旁边。也可以分析已有会话：

```powershell
python src\vd_observer.py --analyze sessions\<session-id>
```

对比一次故障采集和之后的采集：

```powershell
python src\vd_observer.py --compare sessions\<before-id> sessions\<after-id>
```

默认观察以下进程：

- `VirtualDesktop.Streamer.exe`
- `VirtualDesktop.Server.exe`
- `vrserver.exe`
- `vrmonitor.exe`
- `OVRServer_x64.exe`

可以重复使用 `--process` 观察自定义进程：

```powershell
python src\vd_observer.py --process VirtualDesktop.Streamer.exe --process vrserver.exe
```

运行过程中输入一段文字并按回车，即可在时间线上添加故障标记；输入 `quit` 可提前结束采集。

## 命令行参数

```text
--process NAME     要观察的进程名，可重复指定
--interval SEC    采样间隔，默认 1 秒，最小 0.1 秒
--duration SEC    采集时长；默认 0，表示持续运行
--output PATH     会话输出目录，默认 sessions
--analyze PATH    分析已有会话，不进行新采集
--compare A B     对比早期会话与后续会话
```

查看程序版本：

```powershell
python src\vd_observer.py --version
```

## 会话输出

每次运行都会创建一个带时间和随机标识的会话目录：

```text
sessions/<session-id>/
|-- manifest.json
|-- environment.json
|-- events.jsonl
|-- metrics.csv
|-- report.json
`-- report.txt
```

| 文件 | 内容 |
| --- | --- |
| `manifest.json` | 会话 ID、格式版本、采集范围、起止时间和结束原因 |
| `environment.json` | 操作系统、硬件和网络适配器的静态快照 |
| `events.jsonl` | 进程、网络、会话和用户标记组成的统一事件流 |
| `metrics.csv` | 目标进程的周期性资源采样数据 |
| `report.txt` | 面向用户的状态、证据和下一步建议 |
| `report.json` | 面向程序的诊断结果和提取信号 |

`events.jsonl` 中的每一行都是独立 JSON 对象。事件包含会话 ID、数据格式版本、时间戳、单调时间、来源、类别、严重程度和具体数据，便于 AI 按时间窗口筛选与关联。

## 诊断状态

当前诊断层会输出以下状态之一：

- `streamer_not_running`
- `streamer_running_no_cloud_evidence`
- `cloud_registration_blocked`
- `cloud_connected_waiting_for_headset`
- `partial_headset_session`
- `session_established`

完整本地会话的判断依据是头显在 `38810`、`38820`、`38830` 和 `38840`
端口上均建立连接。诊断属于基于证据的启发式结论，原始事件仍是最终依据。

## 隐私与数据安全

所有日志默认只保存在本地，项目不会自动上传会话数据。`sessions/` 已被 Git 忽略。

运行时日志可能包含以下敏感信息：

- 主机名
- 网卡名称、IP、IPv6、MAC 地址和子网掩码
- 进程可执行文件路径
- 远端连接地址和端口
- 用户输入的故障标记

当前原型尚未提供自动脱敏导出。向 Issue、论坛、云端 AI 或其他第三方提交日志前，请先检查并移除不希望公开的信息。不要提交密码、访问令牌、Wi-Fi 密钥或未经检查的崩溃转储。

## 已知限制

- 目前只有命令行采集器，尚无 DevTools 图形界面。
- 尚未采集 Windows Event Log、ETW、GPU 编码器和 VR Runtime 详细状态。
- 无法保证默认进程名覆盖所有 VD 或 VR Runtime 版本。
- 被动网络观察只能看到连接元数据，无法读取加密通信内容。
- 部分系统或其他用户进程的数据可能因 Windows 权限限制而不可用。
- 当前版本尚未提供环形缓冲和脱敏导出。

## 路线图

- Windows Event Log 与应用崩溃事件采集
- GPU、显存、视频编码和网络质量指标
- SteamVR、OpenXR 与 Meta/Oculus Runtime 状态
- 可配置的环形缓冲与“保存故障前 N 分钟”
- 会话浏览、搜索、过滤和时间线界面
- 可预览、可选择字段的脱敏导出
- 稳定的事件 Schema 与兼容性测试

## 反馈与贡献

欢迎通过 GitHub Issues 提交问题、功能建议和经过脱敏的复现信息。有效的故障样例通常包括：

- 用户实际看到的现象
- 大致发生时间及对应的用户标记
- 可重复执行的复现步骤
- VD、Windows、GPU 驱动和头显版本
- 使用的 OpenXR Runtime 与网络连接方式
- 已检查并脱敏的 VD Log Observer 会话日志

提交前可参考 [`docs/error-example-template.md`](docs/error-example-template.md)。

运行基础测试：

```powershell
python -m unittest discover -s tests -v
```

## 许可证

本项目使用 [MIT License](LICENSE)。
