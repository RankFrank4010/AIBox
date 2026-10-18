# 外部服务接入

AIBox 把同一套 Whisper 推理能力暴露为四种传输方式。它们共享模型选择、任务队列、历史记录、硬件选择与字幕导出。

| 传输 | 默认端口 | 认证 | 适用场景 |
| --- | --- | --- | --- |
| OpenAI ASR HTTP | `8765/tcp` | Bearer Token（可选） | OpenAI SDK、现有 HTTP 客户端、批处理 |
| OpenAI TTS HTTP | `8765/tcp` | Bearer Token（可选） | OpenAI Speech SDK、文本转语音 |
| WebSocket ASR | `8765/tcp` | Bearer / `?token=`（可选） | 浏览器录音、边传边转写、部分结果 |
| gRPC ASR | `50051/tcp` | Bearer metadata（可选） | 服务间调用、ASR 双向流 |
| gRPC TTS | `50051/tcp` | Bearer metadata（可选） | 服务间调用、TTS Unary / 流式音频 |
| MRCPv2 | SIP `8060/udp`、控制 `8061/tcp`、RTP `50000-50100/udp` | 无内置认证 | IVR、呼叫中心、FreeSWITCH / SIP 网关 |

> MRCP 当前只实现 `speechrecog`（ASR）。`speechsynth`（TTS）尚未实现；TTS 请使用 OpenAI HTTP 或 gRPC。

## 鉴权

设置环境变量后，外部 HTTP / WebSocket / gRPC 接口需要 Token：

```bash
AIBOX_API_TOKEN=change-me
```

| 传输 | 传递方式 |
| --- | --- |
| OpenAI HTTP | `Authorization: Bearer <token>` |
| WebSocket | `Authorization: Bearer <token>` 或 `?token=<token>` |
| gRPC | metadata `authorization: Bearer <token>` |
| MRCP | 无 Token；使用 SBC / 防火墙 / 可信内网 |

`/api/*` 本地 WebUI 接口不要求这个 Token，避免把本地管理 UI 锁死。未设置 `AIBOX_API_TOKEN` 时外部接口开放，默认只绑定 `127.0.0.1`。

## OpenAI 兼容 HTTP

Base URL：`http://127.0.0.1:8765/v1`

### 模型列表

```http
GET /v1/models
Authorization: Bearer <token>
```

返回 OpenAI `list` 结构，包含 `whisper-1` 别名和已安装的 Whisper 模型 ID。

### 创建转写

```http
POST /v1/audio/transcriptions
Authorization: Bearer <token>
Content-Type: multipart/form-data
```

| 字段 | 说明 |
| --- | --- |
| `file` | 音频文件，必填 |
| `model` | `whisper-1`、`small`、`large-v3-turbo` 等；`whisper-1` 使用默认模型 |
| `language` | ISO-639-1，缺省自动检测 |
| `prompt` | 兼容字段，当前保留 |
| `response_format` | `json`（默认）、`text`、`srt`、`verbose_json`、`vtt` |
| `temperature` | 兼容字段；会出现在 `verbose_json`，当前不改写解码策略 |
| `timestamp_granularities[]` | 可传 `word` / `segment`；`word` 会启用词级时间戳 |

```bash
curl http://127.0.0.1:8765/v1/audio/transcriptions \
  -H "Authorization: Bearer change-me" \
  -F file=@meeting.mp3 \
  -F model=whisper-1 \
  -F language=zh \
  -F response_format=verbose_json
```

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://127.0.0.1:8765/v1",
    api_key="change-me",  # 未配置 AIBOX_API_TOKEN 时可填任意非空值
)
with open("meeting.mp3", "rb") as audio:
    result = client.audio.transcriptions.create(
        model="whisper-1",
        file=audio,
        response_format="verbose_json",
    )
print(result.text)
```

响应：

```json
{"text": "..."}
```

`verbose_json` 还包含 `task`、`language`、`duration`、`segments`（以及请求词级时间戳时的 `words`）。SRT / VTT 直接返回字幕文本。

错误采用 OpenAI 结构：

```json
{
  "error": {
    "message": "The model 'large-v3' is not installed.",
    "type": "invalid_request_error",
    "param": "model",
    "code": "model_not_installed"
  }
}
```

模型别名：

- `whisper-1` → 默认已安装模型；
- `gpt-4o-transcribe` / `gpt-4o-mini-transcribe` → 同样回退到默认 Whisper 模型（兼容新 SDK 的模型名）；
- `whisper-small` / `whisper-large-v3` / `whisper-large-v3-turbo` 等 → 对应模型；
- 未知或未安装模型返回 `404`。

## OpenAI TTS

```http
POST /v1/audio/speech
Authorization: Bearer <token>
Content-Type: application/json
```

| 字段 | 说明 |
| --- | --- |
| `model` | `tts-1` / `tts-1-hd` / `gpt-4o-mini-tts` 映射到默认 IndexTTS；也支持 `indextts-2.5` / `indextts-2` |
| `input` | 待合成文本，上限 8000 字符 |
| `voice` | 内置音色 ID、自定义音色 ID，或 OpenAI alloy/nova 等名称 |
| `language` | `auto` / `zh` / `en` / `ja` / `es` / `ar` |
| `speed` | 0.25–4.0；IndexTTS 2.5 原生语速，IndexTTS 2 使用 ffmpeg atempo |
| `response_format` | `mp3`（默认）、`opus`、`aac`、`flac`、`wav`、`pcm` |
| `instructions` | 兼容字段，当前忽略 |

```bash
curl http://127.0.0.1:8765/v1/audio/speech \
  -H "Authorization: Bearer change-me" \
  -H "Content-Type: application/json" \
  -d '{"model":"tts-1","voice":"alloy","input":"你好，欢迎使用 AIBox","response_format":"mp3"}' \
  --output speech.mp3
```

```python
from openai import OpenAI

client = OpenAI(base_url="http://127.0.0.1:8765/v1", api_key="change-me")
speech = client.audio.speech.create(
    model="tts-1",
    voice="alloy",
    input="你好，欢迎使用 AIBox",
    response_format="mp3",
)
speech.write_to_file("speech.mp3")
```

IndexTTS 需要参考音频。内置的 `default-en` / `default-zh` 来自仓库示例音频；OpenAI 的 alloy / echo 等名称会自动映射到内置参考音。要使用专属音色：

```http
GET    /api/tts/voices
POST   /api/tts/voices        (multipart: file, name, language)
DELETE /api/tts/voices/{id}
```

本地 UI 也通过 `POST /api/tts/synthesize` 调用同一合成引擎。

> `AIBOX_DEMO_TTS=1` 时合成引擎输出提示音而不是语音，仅用于 UI / CI 验证。

## WebSocket

URL：`ws://127.0.0.1:8765/ws/asr`

### 协议

1. 建立连接后发送 JSON `start`；
2. 接收 `ready`；
3. 发送二进制音频帧；
4. 发送 `{"type":"stop"}` 或 `{"type":"commit"}`；
5. 接收 `processing`、`progress`、`final`。

`start`：

```json
{
  "type": "start",
  "model": "whisper-1",
  "language": "zh",
  "format": "pcm16",
  "sample_rate": 16000,
  "partial": true,
  "filename": "call.wav",
  "beam_size": 5,
  "vad_filter": true,
  "word_timestamps": false,
  "device": "auto",
  "compute_type": "auto"
}
```

`format`：

- `pcm16`（默认）：单声道、16-bit little-endian、无 WAV 头；`sample_rate` 可设 8000–48000；
- `wav` / `mp3` / `m4a` / `webm` / `ogg` / `flac` / `opus` / `aac`：发送完整编码文件字节流，服务端收完后统一转写。

事件：

| 事件 | 说明 |
| --- | --- |
| `ready` | 会话创建，包含 `model` / `format` / `partial_supported` |
| `received` | 已接收字节数（约 0.5 秒节流） |
| `partial` | PCM16 + `partial:true` 时的最新部分文本（最多前 60 秒） |
| `processing` | 音频接收完成，任务进入队列 |
| `progress` | `progress` / `stage` / `status` |
| `final` | 最终文本、分段、语言、设备、导出 URL |
| `error` | `code` / `message` / `status` |

控制消息：

- `{"type":"stop"}`：结束音频并开始最终转写；
- `{"type":"cancel"}`：取消当前会话 / 任务；
- `{"type":"ping"}`：返回 `{"type":"pong"}`。

认证失败以 WebSocket close code `1008` 关闭。单会话音频上限为 `AIBOX_MAX_UPLOAD_MB`（默认 512 MB）。`partial` 仅对 PCM16 生效，且部分结果是对当前缓冲区的完整重识别，超过 60 秒后不再更新中间结果，最终结果仍然完整。

### Python 示例

```python
import asyncio, json, wave
import websockets

async def main():
    with wave.open("call.wav", "rb") as w:
        rate = w.getframerate()
        pcm = w.readframes(w.getnframes())
    async with websockets.connect("ws://127.0.0.1:8765/ws/asr") as ws:
        await ws.send(json.dumps({
            "type": "start", "model": "whisper-1",
            "format": "pcm16", "sample_rate": rate, "partial": True,
        }))
        print(await ws.recv())
        for i in range(0, len(pcm), rate * 2):
            await ws.send(pcm[i:i + rate * 2])
        await ws.send(json.dumps({"type": "stop"}))
        while True:
            event = json.loads(await ws.recv())
            if event["type"] == "final":
                print(event["text"])
                break

asyncio.run(main())
```

## gRPC

- 地址：`127.0.0.1:50051`
- ASR Service：`aibox.asr.v1.AsrService`
- TTS Service：`aibox.tts.v1.TtsService`
- Proto：[`aibox_asr.proto`](../services/api/aibox_api/proto/aibox_asr.proto)、[`aibox_tts.proto`](../services/api/aibox_api/proto/aibox_tts.proto)
- 下载：`GET /api/services/proto`、`GET /api/services/proto/tts`
- Reflection：已开启，可直接使用 `grpcurl` / `grpcui`。

### ASR 方法

```proto
rpc Transcribe(TranscribeRequest) returns (TranscribeResponse);
rpc TranscribeStream(stream AudioChunk) returns (stream StreamEvent);
```

`Transcribe` 是文件字节 → 结果。`TranscribeStream` 的首帧必须是 `StartSession`，随后发送 `data`，最后发送 `end=true`；服务端返回 `started`、`progress`、`result` 或 `error`。

### TTS 方法

```proto
rpc Synthesize(SynthesizeRequest) returns (SynthesizeResponse);
rpc SynthesizeStream(SynthesizeRequest) returns (stream AudioChunk);
```

`Synthesize` 返回完整音频字节；`SynthesizeStream` 在合成完成后按 64 KB 分块返回音频，并在最后一帧设置 `final=true`。

```bash
grpcurl -plaintext 127.0.0.1:50051 list
grpcurl -plaintext 127.0.0.1:50051 describe aibox.asr.v1.AsrService
grpcurl -plaintext 127.0.0.1:50051 describe aibox.tts.v1.TtsService
```

带 Token：

```bash
grpcurl -plaintext \
  -H "authorization: Bearer change-me" \
  127.0.0.1:50051 list
```

Python 客户端：

```python
import asyncio, grpc
from aibox_api.proto import aibox_asr_pb2 as pb
from aibox_api.proto import aibox_asr_pb2_grpc as rpc

async def main():
    audio = open("call.wav", "rb").read()
    async with grpc.aio.insecure_channel("127.0.0.1:50051") as channel:
        stub = rpc.AsrServiceStub(channel)
        response = await stub.Transcribe(pb.TranscribeRequest(
            audio=audio,
            filename="call.wav",
            options=pb.TranscribeOptions(model="whisper-1", language="zh"),
        ))
        print(response.text)

asyncio.run(main())
```

使用仓库源码时，生成客户端：

```bash
python -m grpc_tools.protoc \
  -I services/api \
  --python_out=. --grpc_python_out=. \
  services/api/aibox_api/proto/aibox_asr.proto
```

## MRCPv2

面向 IVR / 呼叫中心的最小 `speechrecog` 服务：

```text
SIP/UDP 8060      会话建立
MRCPv2/TCP 8061   共享控制通道（按 Channel-Identifier 复用）
RTP/UDP 50000-50100  每会话一个 RTP 端口
```

### SIP / SDP

客户端发送 `INVITE sip:aibox@<host>:8060`，AIBox 返回 200 OK，SDP 包含：

```text
m=application 8061 TCP/MRCPv2 1
a=channel:<channel-id>@speechrecog
a=cmid:1
m=audio <rtp-port> RTP/AVP 0 8 96
a=rtpmap:0 PCMU/8000
a=rtpmap:8 PCMA/8000
a=rtpmap:96 L16/16000
a=recvonly
a=mid:1
```

客户端向 SDP 中的 RTP 端口发送音频，连接 8061 控制通道，发送 `RECOGNIZE`。支持：

- SIP：`INVITE`、`ACK`、`BYE`、`CANCEL`、`OPTIONS`（UDP）；
- MRCP 方法：`SET-PARAMS`、`GET-PARAMS`、`RECOGNIZE`、`STOP`、`START-INPUT-TIMERS`，`PAUSE` / `RESUME` / `GET-RESULT` 返回成功，`DEFINE-GRAMMAR` / `INTERPRET` 接受但不使用语法；
- MRCP 事件：`START-OF-INPUT`、`RECOGNITION-COMPLETE`；
- 结果：`application/nlsml+xml`，包含 `<input>` 文本；
- 编码：PCMU/8000、PCMA/8000、L16/16000（96）与 L16/8000（97）；
- 结束条件：`Speech-Complete-Timeout`（默认 900 ms）静音、`STOP`、`No-Input-Timeout`（默认 5000 ms）或 `Recognition-Timeout`（默认 120000 ms）。

### 兼容边界

- **仅 SIP over UDP**，不实现 SIP over TCP/TLS；
- 一个 SIP dialog 只分配一个 `speechrecog` 通道；
- 不实现语法匹配 / 语义解释，NLSML 只返回识别文本；
- 不实现 `Save-Waveform` 的 Waveform-URI；
- 无 SIP 认证、无 TLS；公网必须经 SBC / 防火墙；
- 未与 FreeSWITCH 实机联调，但已通过内部 SIP/RTP 客户端端到端验证。

### Docker / NAT

MRCP 的 SDP 必须广告客户端可达地址：

```bash
AIBOX_MRCP_ADVERTISE_HOST=192.0.2.10
```

Compose 需要映射：

```yaml
ports:
  - "8060:8060/udp"
  - "8061:8061/tcp"
  - "50000-50100:50000-50100/udp"
```

如使用 `network_mode: host`，可直接使用容器所在主机网络。若只在本机测试，默认 `127.0.0.1` 即可。

## 服务发现

```http
GET /api/services
GET /api/services/proto
```

`/api/services` 返回四类传输的状态、端口、认证要求、支持格式和错误信息，WebUI「服务接入」页面也使用同一数据。

## 端口与环境变量

| 环境变量 | 默认 | 说明 |
| --- | --- | --- |
| `AIBOX_API_TOKEN` | 空 | OpenAI / WS / gRPC Bearer Token |
| `AIBOX_PUBLIC_BASE_URL` | 自动 | 反向代理后的公开 Base URL |
| `AIBOX_GRPC_ENABLED` | `true` | 是否启动 gRPC |
| `AIBOX_GRPC_HOST` | `127.0.0.1` | gRPC 绑定地址 |
| `AIBOX_GRPC_PORT` | `50051` | 设为 `0` 禁用 |
| `AIBOX_MRCP_ENABLED` | `true` | 是否启动 MRCP |
| `AIBOX_MRCP_HOST` | `127.0.0.1` | SIP/控制/RTP 绑定地址 |
| `AIBOX_MRCP_PORT` | `8060` | SIP UDP；设为 `0` 禁用 |
| `AIBOX_MRCP_CONTROL_PORT` | `8061` | 共享 MRCPv2 TCP 控制端口 |
| `AIBOX_MRCP_RTP_PORT_START/END` | `50000/50100` | 每会话 RTP 端口池 |
| `AIBOX_MRCP_ADVERTISE_HOST` | `127.0.0.1` | SDP 中广告给客户端的地址 |

## 限制

- HTTP / WS / gRPC / MRCP 共享同一个推理锁；同一时刻只有一个 Whisper 解码在运行，避免显存/模型状态冲突。高并发场景应部署多个 AIBox 实例或后续增加模型池。
- 外部请求也会写入 SQLite 历史，可在 WebUI「语音转写 → 转写历史」查看。
- 所有外部传输默认使用已安装模型；不会在请求期间自动下载模型。
- OpenAI `stream=true`（Chat Completions 风格）不适用；批量转写请使用 HTTP，实时音频请使用 WebSocket / gRPC / MRCP。
