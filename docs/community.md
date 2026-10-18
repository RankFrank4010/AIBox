# 社区适配器

AIBox 的内置运行时只覆盖 faster-whisper 与 IndexTTS。社区适配器让用户或模型作者用一份 **声明式 manifest** 接入其他 ASR / TTS 模型，不需要修改 AIBox 源码。

当前支持两类适配器：

| 类型 | 运行方式 | 适合 |
| --- | --- | --- |
| `openai-http` | 调用外部 OpenAI 兼容 `/v1/audio/transcriptions` 或 `/v1/audio/speech` | Speaches、LocalAI、Kokoro-FastAPI、自建网关 |
| `command` | 启动本机 CLI / Python 脚本，通过 `{audio}`、`{text}`、`{output}` 占位符传参 | FunASR、Piper、F5-TTS、ChatTTS、Vosk、NeMo 等 |

内置配方模板（16 个）是配置起点，不是预装引擎。选择模板后需要按本机路径或服务地址修改 `adapter`，再导入启用。

## 安全模型

- 导入的适配器默认 **停用**。
- `command` 适配器默认被全局开关阻止，必须设置 `AIBOX_ALLOW_ADAPTER_COMMANDS=1` 并重启。
- 远程 HTTP 默认被阻止，只允许 loopback / 局域网 IP；跨公网需要 `AIBOX_ALLOW_REMOTE_ADAPTERS=1`。
- 只允许启用可信来源。命令适配器可以执行本机任意进程，等价于本地代码执行权限。
- API key 不要写进 manifest；使用 `api_key_env` 指向环境变量，读取时才注入。
- 外部模型不计入本地显存/内存预算；实际资源由外部进程或服务管理。

## Manifest

JSON 或 YAML 均可。最小示例：

```json
{
  "schema_version": 1,
  "id": "my-tts",
  "name": "My TTS",
  "kind": "tts",
  "description": "本地自建 TTS",
  "languages": "中 / 英",
  "adapter": {
    "type": "openai-http",
    "base_url": "http://127.0.0.1:8000/v1",
    "model": "my-tts",
    "timeout_seconds": 300
  }
}
```

### 通用字段

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `id` | 是 | 2–64 字符，小写开头，仅 `a-z0-9._-`；不能与内置模型冲突 |
| `name` | 否 | 展示名称 |
| `kind` | 是 | `asr` 或 `tts` |
| `description` | 否 | 模型说明 |
| `languages` | 否 | 语言描述 |
| `parameters` | 否 | 参数量 |
| `memory_gb` | 否 | 外部服务资源说明，仅展示 |
| `aliases` | 否 | 别名；可用于 OpenAI `model` 字段 |
| `homepage` | 否 | 上游项目 |
| `tags` | 否 | 标签 |
| `license` / `source` | 否 | 许可与来源 |
| `install` / `docs` | 否 | 安装与配置说明 |
| `adapter` | 是 | 适配器配置 |

### `openai-http`

```json
{
  "type": "openai-http",
  "base_url": "http://127.0.0.1:8000/v1",
  "model": "Systran/faster-whisper-small",
  "api_key_env": "SPEACHES_API_KEY",
  "timeout_seconds": 600,
  "path": "/audio/transcriptions"
}
```

- `base_url` 可以写到 `/v1`；AIBox 会追加 `/audio/transcriptions` 或 `/audio/speech`。
- `path` 可覆盖完整路径，也可直接写完整 URL。
- ASR 使用 multipart 上传，TTS 使用 JSON；TTS 请求 `response_format=wav`。
- `extra_body` 可附加服务端专有字段（TTS）。
- `api_key_env` 是环境变量名，不是密钥本身。

### `command`

```json
{
  "type": "command",
  "command": [
    "python",
    "C:\\models\\piper_runner.py",
    "--text", "{text}",
    "--output", "{output}"
  ],
  "output": "wav",
  "stdin": null,
  "cwd": null,
  "env": {"PYTHONUTF8": "1"},
  "model_dir": "C:\\models\\piper",
  "timeout_seconds": 600
}
```

占位符：

| 占位符 | ASR | TTS | 说明 |
| --- | --- | --- | --- |
| `{audio}` | ✅ | — | 输入音频路径 |
| `{text}` | — | ✅ | 待合成文本 |
| `{output}` | ✅ | ✅ | 输出文件路径 |
| `{model_dir}` | ✅ | ✅ | 模型目录；可由 `adapter.model_dir` 覆盖 |
| `{language}` | ✅ | ✅ | 语言代码 |
| `{task}` | ✅ | — | `transcribe` / `translate` |
| `{voice}` | — | ✅ | 音色 ID |
| `{reference}` | — | ✅ | 参考音频路径（可选） |
| `{speed}` | — | ✅ | 语速 |
| `{filename}` | ✅ | — | 原始文件名 |

ASR 的 `output` 为 `json` 时，命令应写入：

```json
{
  "text": "完整文本",
  "language": "zh",
  "duration": 12.3,
  "segments": [
    {"start": 0.0, "end": 2.4, "text": "第一段"}
  ]
}
```

也可以直接输出纯文本（`output: "text"`）。TTS 的 `output` 应为 `wav`（也接受 ffmpeg 可读的其他音频容器）。

`stdin` 可设置 `{text}`，适合 Piper 这类从 stdin 读文本的 CLI。

## 内置配方模板

| ID | 类型 | 上游 | 推荐接入 |
| --- | --- | --- | --- |
| `sensevoice-small` | ASR | FunASR | command |
| `paraformer-zh` | ASR | FunASR | command |
| `moonshine-base` | ASR | Moonshine | command |
| `parakeet-tdt-0.6b-v2` | ASR | NVIDIA NeMo | command |
| `vosk-model-small-cn` | ASR | Vosk | command |
| `qwen3-asr-1.7b` | ASR | Qwen | command |
| `speaches-whisper` | ASR | Speaches | openai-http |
| `kokoro-82m` | TTS | Kokoro | openai-http / command |
| `piper-zh-huayan` | TTS | Piper | command |
| `cosyvoice2-0.5b` | TTS | CosyVoice | openai-http |
| `f5-tts` | TTS | F5-TTS | command |
| `gpt-sovits-v2` | TTS | GPT-SoVITS | openai-http |
| `fish-speech-1.5` | TTS | Fish Speech | openai-http |
| `chattts` | TTS | ChatTTS | command |
| `melo-tts-zh` | TTS | MeloTTS | command |
| `openai-tts-server` | TTS | 任意 OpenAI 兼容服务 | openai-http |

模板在 WebUI「社区适配」中点击「使用模板」，修改后导入。模板中的命令与端点只是推荐写法，实际参数以上游版本为准。

## WebUI / API

页面：`/community`

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/community` | 模板、适配器、安全状态 |
| GET | `/api/community/templates/{id}` | 可编辑的 manifest |
| POST | `/api/community/adapters` | `{"manifest": "..."}` 或对象 |
| PATCH | `/api/community/adapters/{id}` | `{"enabled": true}` |
| DELETE | `/api/community/adapters/{id}` | 仅删除导入文件 |
| POST | `/api/community/reload` | 重新扫描适配器目录 |

启用后就绪的外部模型会自动出现在模型库，`installed=true`、`external=true`；它们不需要下载，也不能通过模型删除按钮删除。

## 目录

- 内置模板：`services/api/aibox_api/adapters_builtin/templates.json`
- 用户适配器：`<data_dir>/adapters/*.json|yaml|yml`（默认 `%LOCALAPPDATA%\AIBox\adapters`）
- Docker：`/data/adapters`

## 贡献新模型

1. 复制一个最接近的内置模板，修改元数据与 `adapter_example`。
2. 在本机导入并启用，确认模型出现在模型库。
3. 对 ASR 跑一段音频，对 TTS 跑一段文本，检查 `text` / `segments` / 音频格式。
4. 如果命令需要额外依赖，在 `install` 字段写清版本与安装步骤。
5. 把模板加入 `templates.json` 并提交 PR；不需要改 AIBox 核心代码。

提交前请确保 manifest 不含密钥、私有路径或无法公开分发的权重。

## 限制

- 目前不加载任意 Python 插件模块；需要 Python 集成时用 `command` 包装一个薄脚本。
- 外部模型不会自动下载，也不会进入本地弹性预算；请自行管理服务与显存。
- `command` 适配器目前不支持流式 partial 结果；ASR 在命令结束后一次性返回。
- `openai-http` 依赖上游兼容性；非标准服务请用 `command` 或网关转换。
