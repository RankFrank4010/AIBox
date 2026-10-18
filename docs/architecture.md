# AIBox 架构

## 目标

AIBox 是一个本地优先的 AI 模型工作台。当前版本只解决一条主线：

> 在任意桌面 / 服务器设备上发现可用算力，下载 Whisper 模型，在本地加载并完成语音转写，最后交付可用的字幕文件。

设计约束：

- 同一套 Fluent WebUI 覆盖 Windows、macOS、Linux、服务器和移动浏览器。
- Windows / macOS 有一个本地桌面壳；Linux 只提供 WebUI。
- 模型、音频、转写结果默认不离开设备。
- 硬件能力必须真实探测，不把“驱动枚举到设备”当成“推理可用”。
- 后端边界为未来 NPU / Metal / 其他模型族预留，但当前不虚构实现。

## 总览

```text
┌─────────────────────────────────────────────────────────────┐
│ 表现层                                                      │
│  React 19 + Fluent UI v9 + Vite                             │
│  Browser (Win/mac/Linux) · Tauri WebView (Win/mac)          │
└──────────────────────────┬──────────────────────────────────┘
                           │ /api JSON, multipart, file downloads
┌──────────────────────────▼──────────────────────────────────┐
│ FastAPI                                                     │
│  main.py        HTTP / SPA / CORS                           │
│  hardware.py    平台、CPU、GPU、NPU、CUDA 运行时探测         │
│  catalog.py     Whisper 模型目录与推荐策略                   │
│  downloads.py   Hugging Face 下载 / 进度 / 校验 / 取消       │
│  asr.py         faster-whisper 适配器、模型缓存、CPU 回退    │
│  jobs.py        转写任务线程池、取消、进度写入               │
│  store.py       SQLite 历史、设置、导出格式                  │
└──────────────┬───────────────────────────────┬──────────────┘
               │                               │
┌──────────────▼─────────────┐   ┌─────────────▼──────────────┐
│ 本地模型仓库                │   │ 推理运行时                  │
│ data/models/whisper/<id>/   │   │ CTranslate2 CPU int8        │
│ model.bin + tokenizer + ... │   │ CTranslate2 CUDA float16    │
│ manifest.json               │   │ future NPU / Metal adapters │
└────────────────────────────┘   └────────────────────────────┘
```

## 多模型与运行时预算

`runtime.py` 管理模型驻留与换入换出：

- ASR slot（faster-whisper / CTranslate2）
- TTS slot（IndexTTS worker 子进程）

每类一个槽位；两类可同时驻留。预算来自 GPU 显存（有 CUDA）或系统内存，扣除用户预留后与模型 `memory_gb` 估算比较。

- `ensure_capacity()`：加载前检查，按策略卸载空闲模型，否则抛出资源不足。
- `begin()` / `end()`：推理期间标记 busy，禁止换出。
- `note_request()`：记录 ASR/TTS 需求，驱动 auto / time_slice 焦点。
- 后台任务每 5 秒执行空闲 TTL、焦点切换与陈旧预留清理。
- `status()` 暴露给 `/api/runtime` 与「硬件与引擎」页面。

弹性模式：`auto`、`balanced`、`asr_focus`、`tts_focus`、`time_slice`、`custom`。详见 [运行时与弹性调度](runtime.md)。

## TTS 运行时

IndexTTS 的依赖（PyTorch、transformers、torchaudio）与 ASR 明显不同，因此不直接 import 到 API 进程：

```text
API ── JSON lines stdin/stdout ──► tts_worker.py
                                      │
                                      └─ index-tts repo + PyTorch + model checkpoints
```

- 模型下载到 `models/tts/<model_id>`；
- worker Python 由 `AIBOX_INDEXTTS_PYTHON` 指定；
- 源码仓库由 `AIBOX_INDEXTTS_HOME` 指定；
- API 卸载 TTS 时终止 worker，worker 退出后释放显存；
- `AIBOX_DEMO_TTS=1` 提供确定的提示音输出，用于 UI/CI。

TTS 模型目录支持递归下载（IndexTTS 的 `qwen0.6bemo4-merge/` 子目录）。

## 社区适配器

`community.py` 把声明式 manifest 转成 `ModelSpec` 并注册到动态模型目录：

- `openai-http`：ASR/TTS 通过 OpenAI 兼容端点调用；
- `command`：通过 `{audio}` / `{text}` / `{output}` 占位符启动本机 CLI；
- 导入的适配器默认停用；命令执行与远程 HTTP 有全局安全开关；
- 启用的外部模型以 `external=true` 出现在模型库，不占本地下载/驻留预算；
- ASR / TTS 引擎在运行前查询 `CommunityRegistry.adapter_for()`，命中后走外部适配器，否则走 faster-whisper / IndexTTS。

内置配方在 `adapters_builtin/templates.json`，覆盖 16 个主流 ASR/TTS 项目；社区贡献只需增加 manifest，不改核心代码。详见 [社区适配](community.md)。

## 图像生成

图像生成采用 provider 抽象：

- `diffusers`：独立 `image_worker.py`，按 `pipeline` 选择 SD / SDXL / FLUX / Qwen-Image pipeline；API 与 worker 用 JSON lines 通信。
- `comfyui`：`ComfyUIClient` 提交 API workflow、轮询 history、下载 `/view` 结果；默认隐藏节点图。
- `demo`：Pillow 生成示意图，用于 UI/CI。

`ImageJobs` 使用独立线程池串行执行图像任务；`ImageStore` 持久化提示词、参数、状态、进度、图片路径和错误。默认 UI 只暴露提示词/比例/模型/数量，复杂参数在高级设置中。

原生 Diffusers 模型注册为 `kind="image"`，占用 `models/image` 与 `image` 弹性槽位；ComfyUI 外部服务不占本地预算。详见 [图像生成](images.md)。

## 人声 / 伴奏分离

`SeparationEngine` 通过独立 Python 环境执行：

- Demucs：`python -m demucs.separate -n <model> ...`；
- audio-separator：`audio-separator <audio> --model_filename ...`；
- demo：FFmpeg 滤波生成示意分轨。

`SeparationStore` / `SeparationJobs` 持久化任务、进度与分轨路径；`SeparationEngine` 只负责运行与归一化 stems，默认 UI 不暴露 chunk/overlap 等参数。详见 [人声/伴奏分离](separation.md)。

## 视频生成

`VideoEngine` 有三种 provider：

- `minimax`：创建 MiniMax `/video_generation` 任务，轮询 `/query/video_generation`，再通过 `/files/retrieve` 下载 MP4；
- `comfyui`：提交高级 API workflow，轮询 history，下载 SaveVideo / VHS_VideoCombine 输出；
- `demo`：FFmpeg `testsrc2` 生成测试 MP4 与海报。

`VideoStore` / `VideoJobs` 持久化提示词、模型、时长、分辨率、状态、视频与海报路径；视频任务默认串行。API 仍保持简单表单，ComfyUI 节点图只在高级设置中。详见 [视频生成](video.md)。

## 大语言模型

`LLMEngine` 支持：

- 本地 GGUF：启动 `llama-server` 子进程，OpenAI 兼容 `/v1/chat/completions`；
- 外部 OpenAI 兼容服务：直接代理 Ollama / LM Studio / vLLM / 云端；
- demo：确定性流式回复。

本地 `llm` 注册为弹性槽位，使用 GGUF 模型元数据参与预算；切换模型时停止旧 `llama-server`。对话 UI 与 `/v1/chat/completions` 共用同一引擎和 SSE 流。详见 [大语言模型](llm.md)。

## 对外传输

`ExternalAsrGateway` 是所有外部协议的共享入口：

```text
OpenAI HTTP  ─┐
WebSocket    ─┤
gRPC         ─┼─► ExternalAsrGateway ─► TranscriptionJobs ─► WhisperEngine
MRCPv2       ─┘        │
                       └─► TranscriptionStore (history / SSE-independent polling)
```

- 模型解析、音频落盘、任务创建、等待、失败语义只实现一次。
- OpenAI HTTP / WebSocket / gRPC / MRCP 都会进入同一个 SQLite 历史。
- `WhisperEngine` 有进程级推理锁；外部传输与 UI 任务不会同时操作同一个 CTranslate2 模型实例。
- OpenAI / WebSocket / gRPC 共用可选 `AIBOX_API_TOKEN`；MRCP 走网络隔离。
- gRPC 与 MRCP 由 FastAPI lifespan 启动/关闭；端口冲突不会阻止 HTTP 服务启动，只会把状态标为 `error`。
- 传输层实现位于 `aibox_api/transports/`：
  - `openai_api.py`
  - `websocket_asr.py`
  - `grpc_service.py`
  - `mrcp.py`
- 服务状态通过 `GET /api/services` 暴露。

### 端口

| 服务 | 绑定 | 协议 |
| --- | --- | --- |
| WebUI / API / OpenAI / WS | 8765 | HTTP / WebSocket |
| gRPC | 50051 | HTTP/2 gRPC |
| MRCP SIP | 8060 | UDP |
| MRCP 控制 | 8061 | TCP（共享，按 Channel-Identifier 复用） |
| MRCP RTP | 50000–50100 | UDP，每会话一个 |

## 进程与端口

| 进程 | 端口 | 职责 |
| --- | --- | --- |
| `aibox_api`（uvicorn） | 8765 | API、静态 WebUI、后台下载与转写线程 |
| Vite dev server（仅开发） | 5173 | 前端热更新；`/api` 代理到 8765 |
| Tauri 桌面壳 | 无 | WebView + 拉起 / 关闭本地 API |

生产模式只有一个后端进程提供完整 WebUI；开发模式前后端分离。

## 前端

- **设计系统**：Fluent UI v9 的深色 / 浅色自定义 brand ramp；自研布局与动效，不依赖第三方图表库。
- **路由**：`BrowserRouter`，页面为总览、模型库、转写、硬件、路线图、设置。
- **状态**：轻量 React Context。启动时并行拉取 health / system / models / settings；硬件 20 秒刷新；有下载任务时 1.2 秒刷新模型，否则 10 秒。
- **响应式**：>1180px 完整侧栏；940–1180px 图标栏；<940px 隐藏侧栏，使用底部 6 项导航。
- **桌面**：Tauri 构建时通过 `.env.desktop` 把 `VITE_API_BASE` 设为 `http://127.0.0.1:8765`，因此本地 WebView 中的 `fetch` 能访问 API；CORS 默认允许 `tauri://localhost` 与 `http://tauri.localhost`。

## 硬件探测

`hardware.py` 缓存 20 秒，按平台分别实现：

- **CPU**：Windows 注册表、macOS `sysctl`、Linux `/proc/cpuinfo`；线程数与物理核心来自 `psutil`。
- **内存**：`psutil`，Windows `GlobalMemoryStatusEx` 兜底，Linux `sysconf`。
- **NVIDIA GPU**：`nvidia-smi --query-gpu=name,memory.total,...`。
- **其他 GPU**：
  - Windows：`Win32_VideoController`，过滤虚拟显示器；
  - macOS：`system_profiler SPDisplaysDataType -json`；
  - Linux：`lspci`。
- **NPU**：
  - Windows：PnP 设备名匹配 `\bNPU\b|Neural|AI Boost|Hexagon|VPU|Ryzen AI|AI Engine`；
  - macOS：Apple Silicon 识别 Neural Engine；
  - Linux：`/dev/accel*` 与 `lspci`。
- **CUDA 是否真的可用**：
  1. `ctranslate2.get_cuda_device_count()` 确认驱动枚举；
  2. `cuda_runtime.py` 实际加载 cuBLAS 与 cuDNN；
  3. 两者都为真才把 `has_cuda` / `for_asr` 设为 true。
- **可选 pip CUDA 库**：Windows 将 `site-packages/nvidia/{cublas,cudnn,...}/bin` 注入 DLL 搜索路径；Linux 将 `lib` 注入 `LD_LIBRARY_PATH` 并预加载共享库。

NPU 当前只参与“发现与展示”，不会出现在可执行的 ASR 设备选项中。

## 模型目录与下载

模型目录（`catalog.py`）是静态白名单，包含模型 ID、仓库、体积、速度 / 精度、语言、内存建议、标签和许可证。下载器：

1. 校验模型 ID、是否已安装、磁盘空间；
2. 调用 Hugging Face model API 获取根目录权重文件；
3. 对每个文件 HEAD 获取大小（失败时回退已知文件清单）；
4. 流式写入 `.<id>.download` 临时目录，按 1 MB 分块更新进度、速度与 ETA；
5. 支持取消；取消或失败清理临时目录；
6. 校验 `model.bin / config.json / tokenizer.json`；
7. 写入 `manifest.json`，原子重命名到正式目录；
8. 下载任务保留在内存中供 UI 查看最近状态；进程重启后以磁盘目录为准。

下载使用 `HF_TOKEN`、`AIBOX_HF_ENDPOINT`，默认 Hugging Face。

## ASR 生命周期

1. `POST /api/transcriptions` 接收 multipart 音频，按扩展名与 512 MB 上限校验，保存到 `data/uploads/<job_id>.<ext>`；
2. SQLite 插入 `queued` 记录；
3. `TranscriptionJobs` 线程池提交任务，最多并发数由设置决定（默认 1）；
4. `WhisperEngine` 归一化设备与计算类型：
   - `auto`：CUDA 运行时可用则 CUDA，否则 CPU；
   - CPU：默认 int8；
   - CUDA：默认 float16；
   - NPU / Metal：明确拒绝并提示路线图状态；
5. 按 `(模型路径, 设备, 计算类型)` 缓存一个 `WhisperModel`。切换模型时释放旧模型；
6. 逐段解码，按音频时长更新进度与当前时间戳；取消标志在每段检查；
7. 结果写入 SQLite（全文、分段、语言、置信度、设备、警告）；
8. 若 GPU 推理阶段出现 cuBLAS / cuDNN / OOM 等错误且设备为 `auto`，卸载模型并以 CPU int8 重试一次；
9. 完成 / 失败 / 取消均写入任务历史；可按需删除源音频。

### 为什么只缓存一个模型

Whisper 模型 75 MB–3 GB。同时常驻多个模型会不可控地占用显存/内存。当前版本通过“切换即卸载”保证可预测性；`支持多种模型加载` 体现为可安装、可选择、可即时切换，而不是并行常驻。

## 存储

```text
<data_dir>/
  models/whisper/<model_id>/
    model.bin
    config.json
    tokenizer.json
    vocabulary.txt | vocabulary.json
    manifest.json
  uploads/<transcription_id>.<ext>
  state/aibox.db          # SQLite (WAL)
  state/settings.json
  exports/
  logs/
```

SQLite 只保存转写历史和任务元数据；模型权重、音频仍以文件形式存在，便于用户直接迁移或备份。

## 桌面壳

```text
Tauri (Rust)
  ├─ startup: 127.0.0.1:8765 已监听？→ 直接加载 WebUI
  ├─ 否则 dev: 启动 .venv Python -m aibox_api
  ├─ 否则 release: 启动 PyInstaller sidecar aibox-server
  ├─ WebView: Fluent 前端（构建产物内置）
  └─ exit: kill 自己启动的 API 子进程
```

桌面壳不复制业务逻辑，不直接访问模型文件，所有操作仍走同一 HTTP API。Linux 不构建桌面壳。

## 安全边界

- 默认监听 `127.0.0.1`。
- CORS 只允许本地 Vite、Tauri 或显式配置的来源。
- 音频路径在删除与读取时校验位于 uploads 目录内，防止路径穿越。
- 模型 ID 走白名单，不接受任意路径。
- 服务端目前没有鉴权；公网部署必须在反向代理层加 TLS + 鉴权。

## 扩展点

新增推理后端时，保持 `WhisperEngine.transcribe()` 的输入输出契约，并在 `_resolve_backend` 与硬件能力矩阵中加入真实探测。新增模型族时，扩展 `catalog.py` 与下载安装校验，前端模型卡片由目录数据驱动，无需改动布局。

未来计划：

- OpenVINO / QNN 的 NPU 适配；
- Metal / Core ML 路径；
- 自定义模型导入与校验；
- 服务端多用户与 API Token；
- Android / iOS 容器与端侧运行时。
