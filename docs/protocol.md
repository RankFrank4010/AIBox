# AIBOX Unified Protocol 1.0

AIBOX Unified Protocol（AUP）是 AIBox 对外集成的最小统一契约。它不替换现有 API，而是在两个稳定表面上提供一致的发现、错误、任务与流式语义：

| Surface | Base | 用途 |
| --- | --- | --- |
| Native | `/api` | AIBox 全部能力，异步任务、历史与工件 |
| OpenAI-compatible | `/v1` | Chat、ASR、TTS、模型列表，可直接对接 OpenAI SDK |

发现入口：

```http
GET /api/protocol
X-AIBox-Protocol: 1.0
```

返回协议版本、能力、端点、任务状态、流式格式和认证要求。所有 HTTP 响应都带
`X-AIBox-Protocol: 1.0`。

## 认证

```http
Authorization: Bearer <AIBOX_API_TOKEN>
```

- `/v1/*` 需要 Bearer Token；`/api/*` 默认允许本机访问，也可在部署时要求 Token。
- Token 通过 `AIBOX_API_TOKEN` 配置。
- WebSocket ASR 使用 `?token=` 或 `Authorization` 头。

## 通用头

| Header | 方向 | 说明 |
| --- | --- | --- |
| `X-AIBox-Protocol` | 请求/响应 | 固定 `1.0` |
| `X-AIBox-Client` | 请求 | 客户端标识，如 `aibox-python/1.0` |
| `X-Request-ID` | 请求/响应 | 请求追踪 |
| `Idempotency-Key` | 请求 | 任务创建幂等键，服务端按能力支持 |

## 统一对象

### Job

```json
{
  "id": "job_xxx",
  "status": "running",
  "stage": "推理中",
  "progress": 42.5,
  "created_at": "2026-01-01T00:00:00+00:00",
  "updated_at": "2026-01-01T00:00:10+00:00",
  "error": null
}
```

状态：

```text
queued -> running -> completed
                  -> failed
                  -> cancelling -> cancelled
```

终态：`completed` / `failed` / `cancelled`。

任务路径：

| Kind | Create | Poll | Cancel |
| --- | --- | --- | --- |
| transcription | `POST /api/transcriptions` | `GET /api/transcriptions/{id}` | `POST .../cancel` |
| image | `POST /api/images/generations` | `GET /api/images/generations/{id}` | `POST .../cancel` |
| video | `POST /api/videos` | `GET /api/videos/{id}` | `POST .../cancel` |
| separation | `POST /api/separations` | `GET /api/separations/{id}` | `POST .../cancel` |
| training | `POST /api/training/jobs` | `GET /api/training/jobs/{id}` | `POST .../cancel` |

### Error

Native 错误：

```json
{"detail": "模型未安装"}
```

OpenAI 错误：

```json
{"error": {"message": "...", "type": "...", "code": "...", "param": "..."}}
```

SDK 将两者统一为：

```text
AIBOXAPIError(status_code, code, message, details, request_id)
```

### Pagination

列表接口使用 `limit` / `offset`，`limit` 默认 50，最大 200。

## 流式

### Chat SSE

```http
POST /v1/chat/completions
Content-Type: application/json

{"model": "...", "messages": [...], "stream": true}
```

响应：

```text
Content-Type: text/event-stream

data: {"choices":[{"delta":{"content":"你"}}]}

data: [DONE]
```

错误可能以 `{"error": {"message": "..."}}` 事件返回。

### WebSocket ASR

```text
ws://host/ws/asr?token=<token>
```

发送音频分片，返回增量转写事件；具体消息格式以 `/api/protocol` 的
`streaming.websocket_asr` 为准。

## 端点目录

### 发现与管理

```http
GET /api/protocol
GET /api/health
GET /v1/models
```

### 文本

```http
POST /v1/chat/completions
POST /api/translations
POST /api/ocr
```

### 音频

```http
POST /v1/audio/transcriptions
POST /v1/audio/speech
POST /api/transcriptions
POST /api/separations
```

### 图像 / 视频 / 训练

```http
POST /api/images/generations
POST /api/videos
POST /api/training/jobs
```

完整列表由 `GET /api/protocol` 动态返回，避免文档与实现漂移。

## SDK

- [Python SDK](../sdk/python/README.md)
- [TypeScript SDK](../sdk/typescript/README.md)
- [OpenAPI](../sdk/openapi/aibox.openapi.json)

### Python

```python
from aibox_sdk import AIBOXClient

with AIBOXClient("http://127.0.0.1:8765", api_key="...") as client:
    protocol = client.protocol()
    text = client.transcribe("meeting.wav", language="zh")
    job = client.create_image(prompt="A quiet lake")
    done = client.wait_job("image", job["id"])
```

### TypeScript

```ts
import { AIBOXClient } from '@aibox/sdk';

const client = new AIBOXClient({ baseUrl: 'http://127.0.0.1:8765' });
const text = await client.transcribe(blob, { filename: 'meeting.wav' });
const job = await client.createImage({ prompt: 'A quiet lake' });
await client.waitJob('image', job.id);
```

## 版本策略

- 1.x 内保持向后兼容；新增能力只追加字段/端点。
- `GET /api/protocol` 的 `compatibility` 表示兼容范围。
- 客户端应忽略未知字段；服务端保留旧字段至少一个次版本。
