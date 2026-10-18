# 图像生成

AIBox 的图像生成支持三条路径：

| 路径 | 说明 | 适合 |
| --- | --- | --- |
| 本地 Diffusers worker | SD / SDXL / FLUX / Qwen-Image，独立 Python 环境 | 希望 AIBox 全托管模型、进度、历史与 OpenAI 接口 |
| ComfyUI | 调用已运行的 ComfyUI `/prompt` API，模型与节点由 ComfyUI 管理 | 已有 ComfyUI、LoRA / ControlNet 工作流 |
| 演示引擎 | 程序生成示意图，不加载模型 | UI / CI / 首次体验 |

默认界面对用户只显示：提示词、画面比例、模型、数量、生成按钮。步数、种子、ComfyUI checkpoint 与自定义工作流放在折叠的“高级设置”中；**默认不要求用户理解节点图**。

## 模型

| ID | 模型 | 体积 | 建议显存 | pipeline |
| --- | --- | --- | --- | --- |
| `sd15` | Stable Diffusion 1.5 | 约 4.2 GB | 6 GB+ | `stable-diffusion` |
| `sdxl` | Stable Diffusion XL | 约 6.9 GB | 10 GB+ | `stable-diffusion-xl` |
| `flux1-schnell` | FLUX.1 schnell | 约 23.8 GB | 20 GB+ | `flux` |
| `flux1-dev` | FLUX.1 dev | 约 23.8 GB | 20 GB+ | `flux` |
| `qwen-image` | Qwen-Image | 约 40 GB | 32 GB+ / 量化 | `qwen-image` |

模型从 Hugging Face 递归下载，保存在 `models/image/<id>`，要求存在 `model_index.json`。FLUX.1 dev 需要接受上游许可并配置 `HF_TOKEN`；Qwen-Image 权重很大，建议先确认磁盘与显存。

## 本地 Diffusers

安装到独立 Python 环境（避免与 FastAPI / CTranslate2 冲突）：

```powershell
py -3.12 -m venv C:\aibox\image-venv
C:\aibox\image-venv\Scripts\python.exe -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124
C:\aibox\image-venv\Scripts\python.exe -m pip install diffusers transformers accelerate safetensors
$env:AIBOX_IMAGE_PYTHON="C:\aibox\image-venv\Scripts\python.exe"
```

重启 AIBox 后：

- `/api/images/status` 的 `diffusers.runtime_ready` 为 `true`；
- 模型安装后，`auto` 优先选择本地 Diffusers；
- worker 只在需要时加载模型，卸载时终止进程并释放显存；
- 图像 worker 使用 `image` 槽位参与弹性预算；大模型会按显存预留拒绝或换出其他空闲模型。

worker 使用 `inspect.signature` 过滤 pipeline 参数，因此 SD / FLUX / Qwen-Image 共用同一个协议。FLUX 不支持 `negative_prompt` 时会自动忽略；Qwen/FLUX 的引导参数由 pipeline 决定。

## ComfyUI

```powershell
$env:AIBOX_COMFYUI_URL="http://127.0.0.1:8188"
```

AIBox 调用：

1. `GET /system_stats` 检查可用性；
2. `POST /prompt` 提交工作流；
3. 轮询 `GET /history/{prompt_id}`；
4. `GET /view` 下载结果到 `images/<job_id>/`。

默认使用内置 checkpoint 工作流（SD / SDXL）：

```text
CheckpointLoaderSimple → CLIPTextEncode ×2 → EmptyLatentImage
→ KSampler → VAEDecode → SaveImage
```

用户可以在高级设置中禁用默认工作流并粘贴 ComfyUI **API 格式** JSON。模板支持：

| 占位符 | 含义 |
| --- | --- |
| `{{prompt}}` | 正向提示词 |
| `{{negative_prompt}}` | 负向提示词 |
| `{{width}}` / `{{height}}` | 尺寸 |
| `{{steps}}` / `{{guidance}}` | 步数 / 引导 |
| `{{seed}}` / `{{batch}}` | 种子 / 张数 |
| `{{checkpoint}}` | checkpoint 文件名 |

节点标题含 `positive` / `negative` 的 `CLIPTextEncode` 会被自动写入对应提示词。FLUX / Qwen-Image 的 ComfyUI 工作流因安装的节点包与权重文件名不同，建议在 ComfyUI 中导出一次 API workflow，再粘贴到高级设置。

ComfyUI 默认没有鉴权。不要把它直接暴露到公网；跨机访问应通过 VPN / 反向代理 / 防火墙限制。

## 演示引擎

```powershell
$env:AIBOX_DEMO_IMAGE="1"
```

输出为程序生成的渐变示意图，用于验证 UI、任务队列、历史与 OpenAI 接口，不是真实模型推理。

## API

### 本地

```http
GET  /api/images/status
GET  /api/images/generations?limit=30
POST /api/images/generations
GET  /api/images/generations/{id}
POST /api/images/generations/{id}/cancel
DELETE /api/images/generations/{id}
GET  /api/images/files/{job_id}/{filename}
```

```json
{
  "prompt": "云海上的未来图书馆，清晨金色光线，电影感",
  "negative_prompt": "低清晰度, 文字",
  "model": "sdxl",
  "provider": "auto",
  "width": 1024,
  "height": 1024,
  "steps": 28,
  "guidance_scale": 3.5,
  "seed": null,
  "batch": 1,
  "workflow": null,
  "checkpoint": null
}
```

`provider` 可为 `auto` / `diffusers` / `comfyui` / `demo`。返回任务对象，通过 `GET` 轮询 `status`、`progress`、`image_urls`。

### OpenAI Images

```http
POST /v1/images/generations
Authorization: Bearer <token>
Content-Type: application/json
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

支持 `response_format`：

- `url`：返回 `/api/images/files/...` 绝对 URL；
- `b64_json`：直接返回 Base64 PNG。

```python
from openai import OpenAI

client = OpenAI(base_url="http://127.0.0.1:8765/v1", api_key="change-me")
result = client.images.generate(
    model="sdxl",
    prompt="云海上的未来图书馆，清晨金色光线",
    size="1024x1024",
    n=1,
    response_format="b64_json",
)
print(result.data[0].b64_json[:32])
```

OpenAI 风格请求会先创建本地任务，然后同步等待完成（最长约 900 秒）。超时返回 504，失败返回 502。

## 限制

- 本地 Diffusers worker 需要单独安装 PyTorch/diffusers，且未在本机用真实 SD/FLUX/Qwen 权重做端到端实测；ComfyUI 与 demo 路径已用 fake 服务/演示引擎验证。
- FLUX.1 dev 需要接受上游许可；Qwen-Image 需要很大的显存/磁盘。
- ComfyUI 默认工作流只保证通用 checkpoint 节点；特殊模型请使用高级工作流。
- 图像任务默认串行执行（1 个 worker），避免显存争用；可在后续版本扩展并发。
- 生成图像保存在 `<data>/images/<job_id>/`，删除记录会同步删除文件。
