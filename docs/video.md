# 视频生成

AIBox 的视频生成支持两类 provider：

| Provider | 模型 | 说明 |
| --- | --- | --- |
| `minimax` | MiniMax H3、Hailuo 02 | 云端 API，需要 `MINIMAX_API_KEY` |
| `comfyui` | Wan2.1、HunyuanVideo、LTX-Video | 本地 ComfyUI API workflow，高级模式 |
| `demo` | — | FFmpeg 生成测试视频，用于 UI/CI |

默认界面只要求：提示词、模型、时长、分辨率、画幅。ComfyUI 节点图与 workflow 放在“高级设置”中。

## MiniMax H3

MiniMax H3 是通用多模态生成模型，官方说明支持最高 **2K / 15 秒**、原生立体声音频和多模态参考。AIBox 通过 MiniMax 视频 API 接入：

```powershell
$env:MINIMAX_API_KEY="your-minimax-api-key"
# 可选，默认 https://api.minimax.io/v1
$env:AIBOX_MINIMAX_BASE_URL="https://api.minimax.io/v1"
# 可选，覆盖默认模型 ID
$env:AIBOX_MINIMAX_MODEL="MiniMax-H3"
```

AIBox 调用：

1. `POST {base}/video_generation` 创建任务；
2. `GET /query/video_generation?task_id=...` 轮询状态；
3. `GET /files/retrieve?file_id=...` 获取下载地址；
4. 下载 MP4 到 `<data>/videos/<job_id>/video.mp4`。

MiniMax 的模型 ID、区域域名、配额与内容政策由上游控制；如果 H3 在你的账号下使用不同的 model ID，用 `AIBOX_MINIMAX_MODEL` 覆盖。当前实现兼容常见的 `task_id` / `file_id` / `download_url` 返回结构。

## ComfyUI 视频

Wan2.1、HunyuanVideo、LTX-Video 等本地模型通过 ComfyUI 运行：

```powershell
$env:AIBOX_COMFYUI_URL="http://127.0.0.1:8188"
```

在 AIBox 视频页选择对应模型，打开「高级设置」，粘贴 ComfyUI **API 格式** workflow JSON。支持占位符：

| 占位符 | 含义 |
| --- | --- |
| `{{prompt}}` | 提示词 |
| `{{width}}` / `{{height}}` | 尺寸 |
| `{{duration}}` / `{{frames}}` / `{{fps}}` | 时长与帧率 |
| `{{seed}}` | 随机种子 |

工作流必须包含 `SaveVideo` / `VHS_VideoCombine` 等视频输出节点，输出 `.mp4` / `.webm` / `.mov` / `.gif`。如果 ComfyUI 只返回图片，AIBox 会报告没有视频输出。

## 演示引擎

```powershell
$env:AIBOX_DEMO_VIDEO="1"
```

使用 FFmpeg `testsrc2` 生成测试 MP4 与海报，用于验证 UI、任务、播放器、下载与历史，不加载真实模型。

## API

```http
GET  /api/videos/status
GET  /api/videos?limit=30
POST /api/videos
GET  /api/videos/{id}
POST /api/videos/{id}/cancel
DELETE /api/videos/{id}
GET  /api/videos/files/{job_id}/{filename}
```

创建：

```json
{
  "prompt": "雨夜的东京街头，霓虹灯倒映在湿润路面，镜头缓慢推进，电影感",
  "model": "minimax-h3",
  "duration": 6,
  "resolution": "1080P",
  "aspect": "16:9",
  "seed": null,
  "workflow": null
}
```

返回任务对象；轮询 `GET /api/videos/{id}` 获取 `status`、`progress`、`video_url`、`poster_url`。`workflow` 只用于 ComfyUI。

## 存储

- 视频：`<data>/videos/<job_id>/video.mp4`
- 海报：`<data>/videos/<job_id>/poster.jpg`
- 数据库：`<data>/state/aibox.db` 的 `video_generations` 表
- 删除记录会同步删除视频与海报。

## 限制

- MiniMax 是云端服务，需要网络、API Key 与上游配额；真实 H3 API 尚未在本机调用（无 Key），fake API 已验证协议流程。
- H3 的本地权重/本地推理尚未接入；本地 H3 可通过后续 ComfyUI workflow 或新 provider 扩展。
- ComfyUI 视频工作流因节点包与模型不同差异较大，AIBox 不内置固定节点图；需要高级用户提供一次 workflow。
- 默认视频任务串行执行，避免显存/配额争用。
- 输出为 MP4（ComfyUI webm 可能以 `.mp4` 保存，播放器通常可识别；必要时用 FFmpeg 转码）。
