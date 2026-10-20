# AIBox API

Base URL: `http://127.0.0.1:8765`

- JSON 使用 UTF-8；上传使用 `multipart/form-data`。
- 时间字段为 ISO 8601 UTC 字符串。
- 错误统一为 `{"detail": "..."}`。
- 交互式文档：`GET /docs`，OpenAPI：`GET /openapi.json`。
- 当前 `/api/*` 没有内置鉴权，默认只监听 `127.0.0.1`；外部 OpenAI / WS / gRPC 可通过 `AIBOX_API_TOKEN` 启用 Bearer Token。
- 外部 OpenAI / WebSocket / gRPC / MRCPv2 的独立协议与示例见 [服务接入文档](transports.md)。

## 服务状态

```http
GET /api/services
GET /api/services/proto
```

返回 OpenAI HTTP、WebSocket、gRPC、MRCPv2 的状态、端口、认证要求与能力。`/api/services/proto` 下载 gRPC proto 文件。

```json
{
  "openai": {
    "status": "ready",
    "base_url": "http://127.0.0.1:8765/v1",
    "transcriptions": "/v1/audio/transcriptions",
    "models": "/v1/models",
    "auth_required": false,
    "response_formats": ["json", "text", "srt", "verbose_json", "vtt"]
  },
  "websocket": {
    "status": "ready",
    "url": "ws://127.0.0.1:8765/ws/asr",
    "path": "/ws/asr",
    "auth_required": false,
    "partial_supported": true
  },
  "grpc": {
    "status": "running",
    "host": "127.0.0.1",
    "port": 50051,
    "service": "aibox.asr.v1.AsrService",
    "auth_required": false
  },
  "mrcp": {
    "status": "running",
    "host": "127.0.0.1",
    "port": 8060,
    "control_port": 8061,
    "rtp_port_range": [50000, 50100],
    "resource": "speechrecog"
  }
}
```

## TTS

```http
POST /v1/audio/speech
Content-Type: application/json
Authorization: Bearer <token>
```

```json
{
  "model": "tts-1",
  "input": "你好，欢迎使用 AIBox",
  "voice": "alloy",
  "language": "zh",
  "speed": 1.0,
  "response_format": "mp3"
}
```

返回音频字节。支持 `mp3 / opus / aac / flac / wav / pcm`。详细字段与 IndexTTS 说明见 [服务接入文档](transports.md#openai-tts)。

本地 UI：

```http
GET    /api/tts/status
GET    /api/tts/voices
POST   /api/tts/voices
DELETE /api/tts/voices/{id}
POST   /api/tts/synthesize
```

```json
{
  "text": "你好，欢迎使用 AIBox",
  "model": "indextts-2.5",
  "voice": "default-zh",
  "language": "zh",
  "speed": 1.0,
  "response_format": "wav"
}
```

## 弹性运行时

```http
GET   /api/runtime
PATCH /api/runtime
POST  /api/runtime/unload/{kind}
```

可写字段：`elastic_mode`、`elastic_idle_ttl_seconds`、`elastic_switch_interval_seconds`、`elastic_max_loaded_models`、`elastic_gpu_reserve_gb`、`elastic_ram_reserve_gb`、`elastic_pinned_kinds`。

```json
{
  "mode": "auto",
  "focus": "asr",
  "loaded": [
    {"kind": "asr", "model_id": "small", "estimated_gb": 3.0, "busy": false}
  ],
  "budget": {"kind": "vram", "total_gb": 14.5, "used_gb": 3.0, "available_gb": 11.5},
  "demand": {"asr": 4, "tts": 1, "window_seconds": 300},
  "max_loaded_models": 2
}
```

完整模式语义见 [多模型与弹性调度](runtime.md)。

## 社区适配

```http
GET    /api/community
GET    /api/community/templates/{id}
POST   /api/community/adapters
PATCH  /api/community/adapters/{id}
DELETE /api/community/adapters/{id}
POST   /api/community/reload
```

导入：

```json
{
  "manifest": {
    "id": "my-tts",
    "name": "My TTS",
    "kind": "tts",
    "adapter": {
      "type": "openai-http",
      "base_url": "http://127.0.0.1:8000/v1",
      "model": "my-tts"
    }
  }
}
```

导入后默认停用；`PATCH {"enabled": true}` 后，若适配器就绪，模型会以 `external=true` 出现在 `/api/models`，无需下载。命令适配器默认需要 `AIBOX_ALLOW_ADAPTER_COMMANDS=1`，远程 HTTP 默认需要 `AIBOX_ALLOW_REMOTE_ADAPTERS=1`。

Manifest 字段、占位符与安全说明见 [社区适配](community.md)。

## 图像生成

```http
GET    /api/images/status
GET    /api/images/generations?limit=30
POST   /api/images/generations
GET    /api/images/generations/{id}
POST   /api/images/generations/{id}/cancel
DELETE /api/images/generations/{id}
GET    /api/images/files/{job_id}/{filename}
```

```json
{
  "prompt": "云海上的未来图书馆",
  "model": "sdxl",
  "provider": "auto",
  "width": 1024,
  "height": 1024,
  "batch": 1
}
```

OpenAI 兼容：

```http
POST /v1/images/generations
Authorization: Bearer <token>
```

```json
{
  "model": "sdxl",
  "prompt": "云海上的未来图书馆",
  "n": 1,
  "size": "1024x1024",
  "response_format": "b64_json"
}
```

`provider` 支持 `auto` / `diffusers` / `comfyui` / `demo`。高级 `workflow` 字段只用于 ComfyUI API 工作流。详见 [图像生成](images.md)。

## 人声 / 伴奏分离

```http
GET  /api/separations/status
GET  /api/separations?limit=30
POST /api/separations          (multipart: file, model_id, mode)
GET  /api/separations/{id}
POST /api/separations/{id}/cancel
DELETE /api/separations/{id}
GET  /api/separations/files/{job_id}/{filename}
```

`mode`：

- `instrumental`：去人声，保留伴奏；
- `vocals`：去背景，保留人声；
- `stems`：全部分轨。

返回 `outputs[]`，每项包含 `role`、`label`、`filename`、`url`。Demucs 有四轨，UVR/MDX 为两轨。详见 [人声/伴奏分离](separation.md)。

## 视频生成

```http
GET  /api/videos/status
GET  /api/videos?limit=30
POST /api/videos
GET  /api/videos/{id}
POST /api/videos/{id}/cancel
DELETE /api/videos/{id}
GET  /api/videos/files/{job_id}/{filename}
```

```json
{
  "prompt": "雨夜的东京街头，霓虹灯倒映在湿润路面，镜头缓慢推进",
  "model": "minimax-h3",
  "duration": 6,
  "resolution": "1080P",
  "aspect": "16:9",
  "seed": null,
  "workflow": null
}
```

`workflow` 仅用于 ComfyUI。返回任务对象，轮询 `video_url` / `poster_url`。MiniMax 需要 `MINIMAX_API_KEY`。详见 [视频生成](video.md)。

## 大语言模型

```http
POST /v1/chat/completions
GET  /v1/models
GET  /api/llm/status
POST /api/llm/chat
POST /api/llm/unload
```

`/v1/chat/completions` 与本地语言模型页共用引擎，支持 `stream: true`。请求示例：

```json
{
  "model": "qwen3-8b",
  "messages": [
    {"role": "system", "content": "你是简洁的助手。"},
    {"role": "user", "content": "你好"}
  ],
  "temperature": 0.7,
  "max_tokens": 1024,
  "stream": true
}
```

本地 GGUF 通过 llama-server 运行；外部 OpenAI 兼容服务使用 `AIBOX_LLM_BASE_URL`。详见 [大语言模型](llm.md)。

## 多设备与并行

```http
GET  /api/devices
POST /api/devices/refresh
```

返回设备池、当前策略、每类引擎的设备分配、ASR 活跃占用与并发数。设置字段：

```json
{
  "parallel_strategy": "data",
  "parallel_devices": ["cuda:0", "cuda:1"],
  "parallel_workers": 4,
  "asr_device": "auto",
  "tts_device": "cuda:1",
  "image_device": "cuda:0",
  "llm_device": "auto"
}
```

策略与限制见 [多设备与并行推理](parallel.md)。

## 模型微调

```http
GET  /api/training/status
GET  /api/training/datasets
POST /api/training/datasets          (multipart: file, name)
DELETE /api/training/datasets/{id}
GET  /api/training/jobs
POST /api/training/jobs
GET  /api/training/jobs/{id}
POST /api/training/jobs/{id}/cancel
DELETE /api/training/jobs/{id}
GET  /api/training/jobs/{id}/logs
GET  /api/training/artifacts/{job_id}/{file}
```

任务示例：

```json
{
  "name": "qwen-lora",
  "base_model": "Qwen/Qwen3-8B",
  "method": "qlora",
  "dataset_id": "ds_xxx",
  "epochs": 3,
  "batch_size": 1,
  "grad_accum": 8,
  "learning_rate": 0.0002,
  "max_seq": 2048,
  "lora_r": 16,
  "lora_alpha": 32,
  "device": "cuda:0",
  "parallel_strategy": "single"
}
```

真实训练由 `AIBOX_TRAIN_COMMAND` 执行；`AIBOX_DEMO_TRAINING=1` 为演示运行器。详见 [模型微调](training.md)。

## 文本翻译

```http
GET    /api/translations/status
GET    /api/translations
POST   /api/translations
DELETE /api/translations/{id}
```

```json
{
  "text": "Hello",
  "source": "en",
  "target": "zh",
  "provider": "auto",
  "model": null
}
```

支持 `libre`、`argos`、`index`、`hunyuan`、`openai`、`demo`。详见 [文本翻译](translation.md)。

## 图片文字识别

```http
GET    /api/ocr/status
GET    /api/ocr
POST   /api/ocr
GET    /api/ocr/images/{id}
DELETE /api/ocr/{id}
```

`POST /api/ocr` multipart 字段：`file`、`provider`、`model`、`language`。支持 GLM-OCR、OpenAI 兼容视觉、Tesseract。详见 [图片文字识别](ocr.md)。

## 计算集群

```http
GET  /api/cluster/status
GET  /api/cluster/nodes
POST /api/cluster/nodes
POST /api/cluster/nodes/{id}/heartbeat
POST /api/cluster/nodes/{id}/drain
POST /api/cluster/tasks
GET  /api/cluster/tasks
GET  /api/cluster/tasks/{id}
```

详见 [多机集群](cluster.md)。

## 账户与权限

```http
GET    /api/auth/status
POST   /api/auth/bootstrap
POST   /api/auth/login
POST   /api/auth/logout
GET    /api/auth/me
GET    /api/auth/users
POST   /api/auth/users
PATCH  /api/auth/users/{id}
DELETE /api/auth/users/{id}
```

详见 [账户与权限](auth.md)。

## 健康检查

```http
GET /api/health
```

```json
{
  "status": "ok",
  "app": "AIBox",
  "version": "0.1.0",
  "engine": {
    "id": "faster-whisper",
    "installed": true,
    "demo": false,
    "ready": true
  },
  "platform": "windows",
  "settings": { "...": "..." }
}
```

## 系统与硬件

```http
GET /api/system
GET /api/system/refresh
```

`/refresh` 会使硬件缓存失效后重新探测（nvidia-smi / PnP / lspci 等）。

主要字段：

| 字段 | 说明 |
| --- | --- |
| `platform` | 系统、架构、主机名、支持面 |
| `cpu` | 名称、核心数、物理核心、架构 |
| `memory_gb` | 总内存 |
| `gpus` | NVIDIA / AMD / Intel / Apple GPU 原始探测 |
| `npus` | NPU 设备 |
| `accelerators` | UI 使用的统一设备列表 |
| `engines` | faster-whisper、ffmpeg、CUDA / Metal / NPU 状态 |
| `recommendation` | 推荐模型与理由 |
| `has_cuda` | **已确认 cuBLAS + cuDNN 可用** |
| `storage` | 数据目录、模型占用、磁盘空间 |
| `models` | 已安装数量、推荐模型 |
| `settings` | 当前设置 |

`accelerators[]` 示例：

```json
{
  "id": "gpu-0",
  "kind": "gpu",
  "name": "NVIDIA GeForce RTX 4070 Ti SUPER",
  "vendor": "NVIDIA",
  "memory_gb": 16,
  "backend": "CUDA",
  "status": "ready",
  "for_asr": true,
  "detail": "CUDA · 已就绪"
}
```

## 模型列表

```http
GET /api/models
```

```json
{
  "catalog": [
    {
      "id": "small",
      "name": "Whisper Small",
      "repo": "Systran/faster-whisper-small",
      "size_bytes": 484000000,
      "size_label": "484 MB",
      "speed": 3.7,
      "accuracy": 3.2,
      "languages": "99 种语言",
      "memory_gb": 3,
      "tags": ["推荐", "CPU 友好"],
      "installed": true,
      "installed_bytes": 484000000,
      "download": null
    }
  ],
  "installed": ["..."],
  "downloads": ["..."],
  "storage": { "...": "..." },
  "recommendation": {
    "model_id": "large-v3",
    "installed_id": "small",
    "reason": "..."
  }
}
```

`/v1/models` 同时列出 `whisper-1`、TTS 别名（`tts-1` / `tts-1-hd` / `gpt-4o-mini-tts`）以及已安装的 ASR / TTS 模型。

`GET /api/models` 的 `catalog[].download` 为当前进行中的下载任务快照；`installed` 为已校验安装的模型。`catalog[].kind` 为 `asr` 或 `tts`；TTS 模型会递归下载 `qwen0.6bemo4-merge/` 等子目录。`tts_recommendation` 给出 IndexTTS 推荐。

## 下载模型

```http
POST /api/models/downloads
Content-Type: application/json

{"model_id": "small"}
```

`202 Accepted` 返回任务：

```json
{
  "id": "dl_33775511c73b",
  "model_id": "small",
  "model_name": "Whisper Small",
  "status": "downloading",
  "progress": 13.4,
  "bytes_downloaded": 10488009,
  "total_bytes": 78203619,
  "files_done": 1,
  "files_total": 4,
  "current_file": "model.bin",
  "speed_bps": 1183881,
  "eta_seconds": 57,
  "error": null
}
```

状态：`queued | downloading | cancelling | completed | failed | cancelled`。

```http
GET  /api/models/downloads
POST /api/models/downloads/{task_id}/cancel
GET  /api/models/downloads
```

## 删除模型

```http
DELETE /api/models/{model_id}
```

- 正在用于转写任务时返回 `409`；
- 会取消该模型进行中的下载；
- 若它是默认模型，会清空默认设置。

## 设置

```http
GET   /api/settings
PATCH /api/settings
```

可写字段：

```json
{
  "default_model": "small",
  "language": "auto",
  "task": "transcribe",
  "device": "auto",
  "compute_type": "auto",
  "beam_size": 5,
  "vad_filter": true,
  "word_timestamps": false,
  "theme": "dark",
  "max_concurrent_jobs": 1,
  "keep_audio": true
}
```

- `device`: `auto | cpu | cuda | npu | metal`。`npu` / `metal` 当前会被 ASR 引擎拒绝并给出提示。
- `max_concurrent_jobs` 在服务重启后完全生效。
- `default_model` 必须已经安装。

## 创建转写

```http
POST /api/transcriptions
Content-Type: multipart/form-data
```

| 字段 | 类型 | 必填 | 默认 |
| --- | --- | --- | --- |
| `file` | 音频文件 | 是 | — |
| `model_id` | string | 否 | 设置 / 推荐 |
| `language` | string | 否 | `auto` |
| `task` | `transcribe` / `translate` | 否 | `transcribe` |
| `beam_size` | int 1–10 | 否 | 5 |
| `vad_filter` | bool | 否 | true |
| `word_timestamps` | bool | 否 | false |
| `device` | string | 否 | `auto` |
| `compute_type` | string | 否 | `auto` |

支持扩展名：`.wav .mp3 .m4a .flac .ogg .oga .opus .webm .mp4 .aac .wma .aiff .aif .caf`。默认上限 512 MB（`AIBOX_MAX_UPLOAD_MB`）。

成功返回 `202` 和任务对象。轮询：

```http
GET /api/transcriptions/{id}
```

```json
{
  "id": "tr_a441ba6554d74b",
  "status": "completed",
  "stage": "转写完成",
  "progress": 100,
  "filename": "test-zh.wav",
  "duration": 9.18,
  "model_id": "small",
  "task": "transcribe",
  "language": "auto",
  "detected_language": "zh",
  "language_probability": 0.99,
  "engine": "faster-whisper",
  "device": "cuda",
  "compute_type": "float16",
  "text": "欢迎使用 AIBOX ...",
  "segments": [
    {"id": 1, "start": 0.0, "end": 3.2, "text": "欢迎使用 AIBOX"}
  ],
  "audio_url": "/api/transcriptions/tr_a441ba6554d74b/audio",
  "export_urls": {
    "txt": "/api/transcriptions/tr_a441ba6554d74b/export?format=txt",
    "srt": "/api/transcriptions/tr_a441ba6554d74b/export?format=srt",
    "vtt": "/api/transcriptions/tr_a441ba6554d74b/export?format=vtt",
    "json": "/api/transcriptions/tr_a441ba6554d74b/export?format=json"
  },
  "warning": null,
  "error": null
}
```

任务状态机：

```text
queued → running → completed
              ├→ failed
              └→ cancelling → cancelled
```

### 取消 / 删除

```http
POST   /api/transcriptions/{id}/cancel
DELETE /api/transcriptions/{id}
```

运行中的任务不能直接删除，请先取消。

### 音频

```http
GET /api/transcriptions/{id}/audio
```

返回原始音频（若设置了不保留音频或已删除，则 `404`）。

### 导出

```http
GET /api/transcriptions/{id}/export?format=srt
GET /api/transcriptions/{id}/export?format=vtt
GET /api/transcriptions/{id}/export?format=txt
GET /api/transcriptions/{id}/export?format=json
```

仅允许已完成的任务。带 `Content-Disposition: attachment`。

## 历史

```http
GET /api/transcriptions?limit=40&offset=0
```

返回 `{"items": [ ... ]}`，按创建时间倒序。列表包含全文与分段，前端可用于快速打开历史。

## 示例

```bash
curl -F "file=@meeting.mp3" \
     -F "model_id=small" \
     -F "language=zh" \
     -F "device=auto" \
     http://127.0.0.1:8765/api/transcriptions
```

```bash
curl "http://127.0.0.1:8765/api/transcriptions/tr_xxx/export?format=srt" \
     -o meeting.srt
```

## 错误码

| 状态 | 场景 |
| --- | --- |
| `400` | 空音频、未知模型、非法参数 |
| `401/403` | 外部接口 Bearer Token 缺失 / 错误；Hugging Face 授权失败会体现在下载错误文本 |
| `404` | 模型 / 任务 / 音频不存在 |
| `409` | 模型已安装、正在使用、任务尚未完成 |
| `413` | 音频超过上传限制 |
| `415` | 不支持的音频扩展名 |
| `503` | faster-whisper 未安装 |
