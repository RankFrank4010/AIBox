# 文本翻译

AIBox 新增「文本翻译」页面，支持：

- LibreTranslate（也适用于 Argos Translate 的 HTTP 服务）
- 本机 Argos Translate CLI
- Index-Translate
- 腾讯混元 Hy-MT2
- 任意 OpenAI 兼容翻译网关

翻译结果会保存为本地历史记录，可复制、回填和删除。

## 页面

路由：`/translation`

- 源语言 / 目标语言，支持自动检测；
- 自动选择可用服务，或手动指定；
- Index / 混元可选择模型名；
- 译文、提供方、模型、耗时、检测语言；
- 翻译历史。

## 服务配置

在「设置 → 翻译服务」中填写：

| 字段 | 说明 |
| --- | --- |
| `translation_provider` | `auto` / `libre` / `argos` / `index` / `hunyuan` / `openai` |
| `libre_url` | LibreTranslate 地址，例如 `http://127.0.0.1:5000` |
| `libre_api_key` | LibreTranslate API Key |
| `argos_command` | Argos CLI 命令，默认 `argos-translate` |
| `index_url` | Index-Translate OpenAI 兼容地址，如 `https://.../v1` |
| `index_api_key` | Index-Translate Key |
| `index_model` | Index-Translate 模型 ID |
| `hunyuan_url` | 混元 Hy-MT2 OpenAI 兼容地址 |
| `hunyuan_api_key` | 混元 API Key |
| `hunyuan_model` | 默认 `hunyuan-mt2` |
| `llm_base_url` / `llm_api_key` | `openai` 兼容翻译提供方复用 LLM 网关 |

也可用环境变量：

```text
AIBOX_TRANSLATION_PROVIDER
AIBOX_LIBRE_URL
AIBOX_LIBRE_API_KEY
AIBOX_INDEX_URL
AIBOX_INDEX_API_KEY
AIBOX_INDEX_MODEL
AIBOX_HUNYUAN_URL
AIBOX_HUNYUAN_API_KEY
AIBOX_HUNYUAN_MODEL
AIBOX_ARGOS_COMMAND
AIBOX_DEMO_TRANSLATION
```

## 协议

### LibreTranslate

```http
POST {libre_url}/translate
Content-Type: application/json

{"q": "Hello", "source": "en", "target": "zh", "format": "text", "api_key": "..."}
```

读取 `translatedText` 和可选的 `detectedLanguage.language`。

### Argos Translate

```bash
argos-translate --from-lang en --to-lang zh "Hello"
```

Argos 需要明确源语言；源语言选择「自动检测」时不允许使用 Argos。

### Index-Translate / 混元 / OpenAI 兼容

```http
POST {base_url}/v1/chat/completions
Authorization: Bearer <key>

{
  "model": "Index-Translate",
  "temperature": 0.2,
  "max_tokens": 4096,
  "messages": [
    {"role": "system", "content": "Translate from English to Chinese..."},
    {"role": "user", "content": "Hello"}
  ]
}
```

`base_url` 已以 `/v1` 结尾时不会重复追加。Index-Translate 与混元也可通过 NewAPI 暴露为 OpenAI 兼容渠道。

## API

```http
GET    /api/translations/status
GET    /api/translations
POST   /api/translations
DELETE /api/translations/{id}
```

请求：

```json
{
  "text": "Hello",
  "source": "en",
  "target": "zh",
  "provider": "auto",
  "model": null
}
```

## 演示

```powershell
$env:AIBOX_DEMO_TRANSLATION="1"
```

演示翻译器返回带标记的文本，用于验证 UI / 历史 / 删除，不调用真实模型。

## 限制

- LibreTranslate、Index-Translate、混元需要用户提供可达的服务地址与凭据；AIBox 不内置这些模型权重。
- Index-Translate / 混元的默认协议是 OpenAI 兼容 `/chat/completions`；如使用厂商私有签名接口，需要通过 NewAPI 或自建兼容网关转换。
- 单次最多 20000 字符。
- 翻译是同步请求，不进入 ASR/TTS 的长任务队列。
