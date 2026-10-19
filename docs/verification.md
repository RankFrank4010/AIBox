# 验证记录

环境：Windows 11 build 26200，Intel i9-13900K，NVIDIA RTX 4070 Ti SUPER 16 GB，Python 3.12，Node 24，pnpm 10.18.3，Edge（Playwright）。

## 后端

```text
python -m ruff check services/api        → All checks passed
python -m pytest services/api/tests -q   → 48 passed
```

Windows 上测试进程偶发 `0xC0000005`（Python / 原生库退出阶段，堆栈落在 GC 或 pytest 源码读取），重跑即可通过；服务进程本身持续运行无异常。

覆盖：

- health / settings 校验与钳制
- 模型目录、安装注册、系统探测
- 未知模型、已安装模型下载拒绝
- 演示 ASR 完整任务、轮询、音频、SRT/VTT/JSON 导出、历史、删除
- 空音频拒绝
- 模型删除
- OpenAI 兼容端点、模型别名、四种响应格式、错误结构、Bearer 鉴权
- WebSocket `start / binary / stop`、进度与 final、Token 关闭
- gRPC Unary 与 Streaming 的真实 stub 调用（临时端口）
- gRPC Bearer metadata：未授权 `UNAUTHENTICATED`，授权成功
- MRCP 服务默认关闭 / 服务状态接口
- TTS 演示引擎 `/api/tts/synthesize`、OpenAI `/v1/audio/speech`、音色上传/删除
- 独立 IndexTTS worker 进程 + JSON-lines 协议（用 fake IndexTTS 模块跑通真实 worker 启动、推理、状态与卸载）
- gRPC TTS Unary / Streaming
- `/api/runtime` 查询与模式切换
- 运行时预算 / 换出 / busy 保护 / 超预算拒绝
- 社区内置配方、manifest 导入/启用/停用/删除、外部模型进入目录
- command ASR / command TTS 端到端
- openai-http ASR / TTS 端到端（本机 fake HTTP 服务）
- 命令 / 远程 HTTP 安全开关
- 图像模型目录、演示任务、文件访问、删除
- OpenAI Images `b64_json` / `url`
- ComfyUI 工作流注入、fake `/prompt` + `/history` + `/view` 端到端
- 人声分离模型目录、演示任务、去人声/去背景/四轨、文件访问、删除
- 视频模型目录、演示 MP4、MiniMax fake API、ComfyUI 视频/下载解析

## TTS / 弹性调度实测

- `AIBOX_DEMO_TTS=1` 下，OpenAI Python SDK `client.audio.speech.create` 返回有效 WAV；
- Web UI 生成、试听、下载成功，无 console error；
- IndexTTS 模型库页签显示 2.5 / 2，递归文件发现、下载启动 / 取消与临时目录清理通过；
- 运行中的 ASR 模型被 `/api/runtime` 识别为 `small / CUDA / 3 GB`，预算显示 14.5 GB；
- TTS / 运行时改动后重新跑 Whisper Small CUDA 真实转写，`/api/runtime` 保持 `asr / small / 3 GB`；
- 弹性模式 `auto / balanced / asr_focus / tts_focus / time_slice / custom` 已实现，UI 与 API 可配置；
- 真实 IndexTTS 权重与推理未在本机下载/运行（模型 5 GB+、需要独立 PyTorch 运行时），worker 代码与安装脚本已提供。

## 社区适配实测

- 内置 16 个配方模板（7 个 ASR + 9 个 TTS），覆盖 FunASR、Moonshine、NeMo、Vosk、Speaches、Piper、Kokoro、CosyVoice、F5-TTS、GPT-SoVITS、Fish Speech、ChatTTS、MeloTTS 等；
- 导入 `openai-http` 适配器后默认停用，启用后外部模型以 `installed=true / external=true` 进入模型库；
- 禁用/删除后模型从模型库移除；
- `command` ASR 用 fake 脚本跑通 `/api/transcriptions` 全流程；
- `command` TTS 用 fake 脚本跑通 OpenAI `/v1/audio/speech`；
- 未开启安全开关时命令 / 远程 HTTP 适配器被阻塞且不会注册模型；
- WebUI 社区页 16 个模板、9 项移动导航、无 console error。

## 图像生成实测

- `AIBOX_DEMO_IMAGE=1` 下 `/api/images/generations` 端到端：任务、进度、PNG 文件、历史、删除全部通过；
- OpenAI Images `response_format=b64_json` 返回有效 Base64 PNG，`url` 返回可访问的绝对 URL；
- ComfyUI fake 服务验证工作流注入（checkpoint / positive / negative / seed / steps）、`/prompt`、`/history`、`/view` 全流程；
- WebUI 图像页默认表单生成、结果画廊、最近生成、无 console error；节点图与复杂参数默认折叠；
- 本地 Diffusers worker 与真实 SD / FLUX / Qwen-Image 权重未在本机下载运行，代码路径已提供，ComfyUI / demo 路径已实测。

## 人声分离实测

- `AIBOX_DEMO_SEPARATION=1` 下 `/api/separations` 端到端：上传、任务、进度、单轨/四轨、WAV 文件访问、删除；
- WebUI 上传音频、选择“去人声/去背景/全部分轨”、模型选择、分轨试听与下载通过；
- 11 项移动导航在 390px 下无横向溢出；
- 真实 Demucs / UVR 权重未在本机下载运行，CLI 路径已实现，演示与 API 流程已实测。

## 视频生成实测

- `AIBOX_DEMO_VIDEO=1` 下 `/api/videos` 端到端：任务、MP4、海报、文件访问、删除；
- WebUI 生成、`<video>` 播放、历史、下载通过；
- MiniMax fake API 验证创建 / 查询 / 文件检索 / 下载流程；
- ComfyUI 视频代码路径支持 SaveVideo / VHS_VideoCombine 输出解析；
- 真实 MiniMax H3 API 与 ComfyUI 视频工作流未在本机运行（无 Key / 无节点包），演示与 fake API 已实测。

## 语言模型实测

- 8 个 GGUF 模型目录、单文件下载字段、模型库语言模型页签；
- `AIBOX_DEMO_LLM=1` 下 `/api/llm/chat` 流式 / 非流式、`/v1/chat/completions`、`/v1/models`；
- fake OpenAI 兼容服务：`/v1/models`、流式与非流式 chat；
- 已安装 GGUF 模型出现在 `/v1/models`；
- WebUI 流式对话、停止、模型选择、语言模型页；
- 12 项移动导航在 390px 下无横向溢出；
- 真实 GGUF 与 llama-server 未在本机下载运行，协议与 fake 服务已实测。

## NewAPI 联调

四号服务器 NewAPI：

```text
https://newapi.franj2.top
x-new-api-version: v0.13.2
container: 1Panel-new-api-0Vsg
```

- 使用 NewAPI Token 调用 `GET /v1/models`：HTTP 200，返回 **111** 个模型；
- AIBox 外部 LLM 读取同一 `/v1/models`，语言模型页可作为外部模型源；
- NewAPI 当前部分上游渠道返回 `Missing API key`、`Model is unavailable`、`ModelDeprecated`、`504`，属于 NewAPI 渠道状态；
- 未把 NewAPI Token 写入仓库；双向接入说明见 [与 NewAPI 结合](newapi.md)。

## 多设备与并行实测

- `/api/devices` 返回 `cuda:0` / `cpu` 设备池、选中设备、策略与并发数；
- 设置 PATCH 后策略与设备池即时反映；
- `tensor` 策略生成 `row` split，`pipeline` 生成 `layer` split；
- 单卡环境自动退化为单设备；
- 真实双卡机器未在本机验证；调度、命令生成与 API 流程已测试。

## 计算优先级实测

- 默认 `services_first`：存在 ASR 需求时 `admit("llm")` 被拒绝，普通服务 priority 高于 LLM；
- `scheduled` + 全天窗口：LLM 优先，普通服务 priority 低于 LLM；
- `auto`：窗口内 LLM 优先，窗口外普通服务需求时切回服务优先；
- `/api/system.runtime.compute_priority` 返回模式、生效策略、窗口与压力状态。

## 模型微调实测

- `AIBOX_DEMO_TRAINING=1` 下数据集上传、校验、任务、进度、日志、取消、产物、删除；
- JSONL 数据集含 UTF-8 BOM 时可正常读取；
- WebUI 上传数据集、创建 QLoRA 任务、日志与产物展示通过；
- 真实 Transformers / PEFT / DeepSpeed 训练未在本机运行；外部命令与演示路径已实现。

## 四号服务器部署实测

- AIBox 容器 `aibox` 已加入 `1panel-network`，健康检查通过；
- NewAPI 新增 OpenAI 渠道 `AIBox Local ASR`，模型 `whisper-cpp-tiny`；
- `GET /v1/models` 已包含 `whisper-cpp-tiny`；
- 通过 `https://newapi.franj2.top/v1/audio/transcriptions` 上传英文测试 WAV，返回 200：
  `Hello, this is AIBox running a local whisper transcription test. The audio never leaves this computer.`
- 该服务器为 AMD A6-3400M（无 AVX），faster-whisper/CTranslate2 会非法指令崩溃，因此改用 whisper.cpp CPU 命令适配器；
- 9 秒音频约 72 秒完成，Nginx 代理读超时已提高到 300s。

## 外部传输端到端

在本机启动 HTTP/WS/gRPC/MRCP 服务后实测：

| 传输 | 结果 |
| --- | --- |
| OpenAI HTTP | `curl` + 官方 `openai` Python SDK：`json` / `verbose_json` 返回文本、分段与 16 个词级时间戳 |
| OpenAI TTS | 官方 SDK `audio.speech.create` + `curl`：演示引擎返回有效 WAV / MP3 |
| WebSocket（编码文件） | 发送完整 WAV 字节，收到 `ready → received → processing → progress → final` |
| WebSocket（PCM16 + partial） | 逐秒发送 22.05 kHz PCM，收到 4 次 `partial`，final 文本完整 |
| gRPC Unary | `small` / CUDA float16，返回 2 个分段 |
| gRPC Streaming | 首帧 `StartSession`，收到 `started → progress → result` |
| gRPC TTS | Unary 返回 WAV；SynthesizeStream 返回音频分块 |
| MRCPv2 | 手工 SIP INVITE + RTP PCMU，收到 `200 IN-PROGRESS`、`START-OF-INPUT`、`RECOGNITION-COMPLETE` NLSML 文本 |
| OpenAI 鉴权 | 未带 Token `401`，带 `Bearer` 成功 |
| WebSocket 鉴权 | 未带 Token 连接被 `1008` 关闭 |

MRCP 实测结果：

```text
control 8061 rtp 50000
MRCP/2.0 81 101 200 IN-PROGRESS
MRCP/2.0 142 START-OF-INPUT 101 IN-PROGRESS
MRCP/2.0 425 RECOGNITION-COMPLETE 101 COMPLETE
Completion-Cause: 000 success
<input>Hello, this is AIBOX running a local whisper transcription test.
The audio never leaves this computer.</input>
```

## 真实 GPU 转写

通过 UI 上传 `examples/audio/chinese-test.wav`：

```text
Whisper Small · NVIDIA CUDA · float16
9.47 s 音频 → 3 段中文
欢迎使用 AIBOX
这是一个本地运行的语音识别工作台
音频不会离开你的电脑
```

- 音频请求返回 `206 Partial Content`，播放器可播放；
- 点击第二段后音频跳转到对应时间并高亮；
- SRT / VTT / TXT / JSON 导出通过；
- 故意让 CUDA 用户态库缺失时，系统检测为 `runtime-missing`，CPU int8 转写成功；
- 安装 `nvidia-cublas-cu12` / `nvidia-cudnn-cu12` 后，系统识别 `has_cuda=true`，GPU 路径恢复。

## 前端

```text
pnpm --filter @aibox/web typecheck   → 通过
pnpm --filter @aibox/web test        → 4 passed
pnpm --filter @aibox/web build       → 通过（约 816 KB JS / 222 KB gzip）
pnpm --filter @aibox/web build:desktop → 通过
```

Playwright 页面检查：

- 16 个桌面页面状态 + 13 个移动端页面：总览、模型库、社区适配、转写、转写结果（查询参数）、语音合成、语言模型、文本翻译、模型微调、图像生成、视频生成、人声分离、硬件、服务接入、路线图、设置；
- 1440px 与 390px 两套视口；
- `document.body.scrollWidth == innerWidth`，无水平溢出；
- 0 个 console error / pageerror；
- 移动端 7 项底部导航显示、侧栏隐藏；
- 模型下载启动、队列进度、取消与临时目录清理；
- 删除模型确认弹窗打开 / 关闭；
- 主题切换为浅色后 `data-theme=light`，背景切换成功；
- 服务接入页显示 7 个服务卡片、gRPC/MRCP 运行状态与端口。

截图为最终构建产物重新渲染后的结果，位于 `screenshots/`。

## 桌面壳

```text
pnpm --filter @aibox/desktop check
→ Finished dev profile ...
```

- Rust 1.90.0（`rust-toolchain.toml` 固定）；
- 通过带 stub sidecar 的 `cargo check`；
- 未生成安装包：需要先运行 `scripts/build-sidecar.ps1` 生成 PyInstaller sidecar；
- 未在 macOS 实机验证（代码路径为跨平台 Tauri 2）。

## 文本翻译实测

- 演示翻译器：API 返回、SQLite 历史、删除、UI 翻译流程通过；
- LibreTranslate：请求体、`translatedText`、`detectedLanguage` 解析测试通过；
- Index-Translate / 混元 OpenAI 兼容：`/v1/chat/completions` 地址、Bearer Key、模型与翻译提示词测试通过；
- 真实 LibreTranslate / Index-Translate / 混元服务需要用户提供地址和凭据，本机未验证上游推理质量。

## 部署

```text
docker compose config --quiet            → 0
docker compose -f docker-compose.gpu.yml config --quiet → 0
```

本机 Docker daemon 未启动，因此未实际构建镜像 / 启动容器。Dockerfile 与 Compose 语法已通过 `docker compose config` 验证。

## 未验证项

- macOS 桌面壳与签名 / 公证；
- Linux 实机 CUDA / 容器 GPU 透传；
- NPU Whisper 加速（规划中）；
- Android / iOS（仅规划）；
- 大模型下载中断后的断点续传（当前取消会清理临时目录，不支持跨进程续传）；
- 移动端 Safari / Android WebView 的实机兼容性。
