# AI 去水印（图片 / 视频）

AIBOX 新增「AI 去水印」页面，支持图片和视频。

## 工作方式

1. 上传图片或视频；
2. 在预览上拖动框选水印区域，可框选多个区域；
3. 选择修复服务；
4. 图片同步返回结果；视频逐帧修复并保留原音轨。

## 修复服务

| Provider | 说明 |
| --- | --- |
| `auto` | IOPaint → Simple LaMa → demo 自动选择 |
| `iopaint` | 外部 [IOPaint](https://github.com/Sanster/IOPaint) HTTP 服务，推荐生产 |
| `lama` | 本地 `simple-lama-inpainting`（可选安装） |
| `demo` | 无模型演示修复，用于 UI / CI |

IOPaint 默认地址：

```text
http://127.0.0.1:8080
```

接口使用：

```http
POST {IOPAINT_URL}/api/v1/inpaint
multipart: image, mask, model=lama
```

## 配置

设置页「AI 去水印」：

```text
watermark_provider: auto | iopaint | lama | demo
iopaint_url:       http://127.0.0.1:8080
watermark_model:   lama
```

环境变量：

```text
AIBOX_DEMO_WATERMARK=1
AIBOX_IOPAINT_URL=http://127.0.0.1:8080
AIBOX_WATERMARK_MODEL=lama
AIBOX_FFMPEG=ffmpeg
```

## API

```http
GET    /api/watermarks/status
GET    /api/watermarks
POST   /api/watermarks/images
POST   /api/watermarks/videos
GET    /api/watermarks/{id}
GET    /api/watermarks/{id}/file
DELETE /api/watermarks/{id}
```

图片：

```text
file=<image>
provider=auto
regions=[{"x":0.7,"y":0.8,"w":0.25,"h":0.15}]
```

`regions` 为归一化坐标；也兼容像素坐标（任一项 > 1 时按像素解释）。

视频：

```text
file=<video>
regions=[...]
```

返回 `202` 任务，轮询 `/api/watermarks/{id}`，完成后从
`/api/watermarks/{id}/file` 下载 MP4。

## 视频处理

- `ffprobe` 读取尺寸和帧率；
- `ffmpeg` 拆帧；
- 逐帧修复；
- `ffmpeg` 重新编码 H.264，并复制原音轨；
- 处理队列单并发，避免同时占用显存/CPU。

## 限制

- 视频逐帧修复速度取决于帧数和修复服务；
- IOPaint / LaMa 需要单独部署或安装，AIBox 不内置模型权重；
- 演示修复不是生成式 AI，仅用于验证流程；
- 静态框选适用于固定位置水印；移动水印需要逐帧/跟踪掩码，尚未实现；
- 没有视频字幕/动态物体跟踪去水印。
