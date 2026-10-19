# 图片文字识别（OCR）

AIBox 新增「图片文字识别」页面，支持：

- 智谱 GLM-OCR（GLM 视觉模型 OpenAI 兼容接口）
- 任意 OpenAI 兼容视觉模型
- 本机 Tesseract CLI
- 演示 OCR

支持 PNG / JPEG / WebP / BMP / TIFF，单张最大 20 MB。识别结果与图片会保存到本地历史，可复制、回填和删除。

## 页面

路由：`/ocr`

- 点击 / 拖入图片，预览原图
- 选择 OCR 服务、语言、可选模型
- 显示识别文字、服务、模型、耗时、语言
- 历史缩略图、文本、删除

## 配置

在「设置 → OCR 服务」中填写：

| 字段 | 说明 |
| --- | --- |
| `ocr_provider` | `auto` / `glm` / `openai` / `tesseract` / `demo` |
| `glm_base_url` | 默认 `https://open.bigmodel.cn/api/paas/v4` |
| `glm_api_key` | 智谱 API Key |
| `glm_ocr_model` | 默认 `glm-ocr` |
| `ocr_openai_url` | OpenAI 兼容视觉服务地址 |
| `ocr_openai_api_key` | 视觉服务 Key |
| `ocr_openai_model` | 默认 `gpt-4o-mini` |
| `tesseract_command` | 默认 `tesseract` |

环境变量：

```text
AIBOX_DEMO_OCR=1
AIBOX_OCR_PROVIDER=auto
AIBOX_GLM_API_KEY=
AIBOX_GLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4
AIBOX_GLM_OCR_MODEL=glm-ocr
AIBOX_OCR_OPENAI_URL=
AIBOX_OCR_OPENAI_API_KEY=
AIBOX_OCR_OPENAI_MODEL=gpt-4o-mini
AIBOX_TESSERACT_COMMAND=tesseract
```

## 协议

GLM-OCR 与 OpenAI 视觉服务使用：

```http
POST {base}/chat/completions
Authorization: Bearer <key>

{
  "model": "glm-ocr",
  "messages": [{
    "role": "user",
    "content": [
      {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}},
      {"type": "text", "text": "识别图片中的所有文字…"}
    ]
  }]
}
```

`base` 以 `/v1` 或 `/v4` 结尾时直接追加 `/chat/completions`，否则追加 `/v1/chat/completions`。

Tesseract：

```bash
tesseract image.png stdout -l chi_sim+eng
```

## API

```http
GET    /api/ocr/status
GET    /api/ocr
POST   /api/ocr
GET    /api/ocr/images/{id}
DELETE /api/ocr/{id}
```

`POST /api/ocr` 使用 multipart：

```text
file=@image.png
provider=glm
model=glm-ocr
language=zh
```

## 存储

```text
<data>/ocr/<uuid>.<ext>
<data>/<database>.db  # ocr_records 表
```

## 限制

- GLM-OCR / OpenAI 视觉需要用户提供 API Key；AIBox 不内置视觉模型权重。
- GLM-OCR 的实际可用模型名取决于智谱账号，默认值为 `glm-ocr`，可在设置中修改。
- Tesseract 的中文识别需要 `chi_sim` 语言包。
- 识别是同步请求，大图或慢速上游可能耗时较长。
- 演示 OCR 不调用真实模型。
