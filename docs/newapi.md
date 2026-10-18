# 与 NewAPI 结合

四号服务器上的 NewAPI 部署信息：

- 地址：`https://newapi.franj2.top`
- 版本：`v0.13.2`（`x-new-api-version`）
- 容器：`1Panel-new-api-0Vsg`，`calciumion/new-api:v0.13.2`
- 监听：`127.0.0.1:3000`，由 1Panel Nginx 反向代理
- 数据库：SQLite，容器内 `/data/one-api.db`
- 网络：`1panel-network`

AIBox 和 NewAPI 都是 OpenAI 兼容服务，因此有两种结合方向。

## 方向 A：AIBox 使用 NewAPI 的模型池（推荐）

NewAPI 作为模型网关，AIBox 作为本地工作台：

```text
AIBox Chat / OpenAI API
        │
        ▼
NewAPI https://newapi.franj2.top/v1
        │
        ├── OpenAI / Claude / Gemini / Qwen / DeepSeek ...
        └── 其他中转渠道
```

### 1. 在 NewAPI 创建令牌

在 NewAPI 控制台创建 API Token，确认：

- 令牌状态启用；
- 额度足够；
- 模型限制允许要使用的模型；
- 分组与渠道匹配。

不要把令牌提交到仓库。

### 2. 配置 AIBox

```powershell
$env:AIBOX_LLM_BASE_URL="https://newapi.franj2.top/v1"
$env:AIBOX_LLM_API_KEY="<NewAPI Token>"
$env:AIBOX_LLM_MODEL="mimo-v2.6-flash-free"
```

重启 AIBox 后：

```http
GET /api/llm/status
```

`external.models` 会从 NewAPI 的 `/v1/models` 读取模型。语言模型页会把这些模型列在“外部”分组，选择后即可对话。

也可以直接使用 AIBox 的 OpenAI 兼容入口：

```bash
curl http://127.0.0.1:8765/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"mimo-v2.6-flash-free","messages":[{"role":"user","content":"你好"}]}'
```

AIBox 会把请求转发给 NewAPI；模型名、错误与用量由 NewAPI 返回。

### 3. 当前实测

在四号服务器上验证：

```text
GET https://newapi.franj2.top/v1/models
Authorization: Bearer <NewAPI Token>
→ HTTP 200，111 个模型
```

NewAPI 当前部分上游渠道存在可用性问题：

- 部分模型返回 `Missing API key`（上游渠道缺 Key）；
- 部分模型返回 `Model is unavailable` / `ModelDeprecated`；
- 部分模型返回 `504` 或上游超时。

这属于 NewAPI 渠道/上游状态，不是 AIBox 转发问题。AIBox 会把 NewAPI 的错误原样呈现给用户，并在模型列表中同步 NewAPI 的模型。

## 方向 B：NewAPI 把 AIBox 作为渠道

AIBox 已经暴露 OpenAI 兼容接口：

```http
GET  /v1/models
POST /v1/chat/completions
```

在 NewAPI 中新增 OpenAI 类型渠道：

```text
Base URL: http://<AIBOX_HOST>:8765/v1
API Key:  AIBOX_API_TOKEN（如已设置）
模型:     qwen3-8b / llama-3.1-8b / 本地 GGUF ID
```

适用于：

- NewAPI 与 AIBox 在同一 Docker 网络；
- 或 AIBox 有内网 / 公网可达地址；
- 或通过反向代理把 AIBox 暴露给 NewAPI。

当前 AIBox 运行在本地开发机，未直接加入四号服务器的 `1panel-network`，因此没有修改 NewAPI 渠道配置。

## Docker 网络注意事项

如果两者都在四号服务器：

```text
NewAPI 容器：1panel-network，宿主 127.0.0.1:3000
AIBox 容器：需要加入同一网络，例如 aibox:8765
NewAPI 渠道 Base URL：http://aibox:8765/v1
```

如果 AIBox 在另一台机器：

```text
Base URL: http://<内网 IP>:8765/v1
```

不要把未鉴权的 AIBox 直接暴露公网；至少设置 `AIBOX_API_TOKEN` 并通过 HTTPS 反向代理。

## 配置建议

- NewAPI Token 放在 AIBox 的 `.env` 或运行环境变量中，不写入 `settings.json` / 仓库；
- `AIBOX_LLM_BASE_URL` 末尾不要带 `/chat/completions`，只到 `/v1`；
- 模型 ID 使用 NewAPI `/v1/models` 返回的 `id`；
- 如果 NewAPI 使用 Cloudflare，长视频/长上下文请求可能需要更长的超时；
- AIBox 的外部模型列表是实时读取的，NewAPI 新增模型后刷新语言模型页即可。
