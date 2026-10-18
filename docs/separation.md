# 人声 / 伴奏分离

AIBox 用 **Demucs** 与 **UVR / audio-separator** 做本地人声、伴奏与乐器分离。默认界面只要求上传音频、选择“去人声 / 去背景 / 全部分轨”和一个模型，不暴露频谱、chunk、overlap 等复杂参数。

## 模式

| 模式 | 输出 | 典型用途 |
| --- | --- | --- |
| `instrumental` | 伴奏（无人声） | 卡拉 OK、翻唱伴奏 |
| `vocals` | 人声 | 提取干净人声、去背景音乐 |
| `stems` | 人声 / 鼓 / 贝斯 / 其他 | 混音、采样、二次制作 |

UVR / MDX 模型只有 2 轨（人声 + 伴奏），选择“全部分轨”时也只返回这两轨；Demucs 模型支持 4 轨。

## 模型

| ID | 引擎 | 分轨 | 说明 |
| --- | --- | --- | --- |
| `htdemucs` | Demucs v4 | 4 | 默认，质量/速度平衡 |
| `htdemucs_ft` | Demucs v4 FT | 4 | 微调版，质量更高 |
| `mdx_extra` | Demucs MDX | 4 | 高质量离线四轨 |
| `uvr-mdx-inst-hq3` | audio-separator | 2 | UVR 伴奏 HQ3 |
| `uvr-mdx-voc-ft` | audio-separator | 2 | UVR 人声 FT |
| `uvr-mdx-inst-main` | audio-separator | 2 | UVR 通用伴奏 |

Demucs 权重在首次运行时由上游自动下载到 Torch 缓存；UVR 模型文件放在 `models/separator`，文件名需与模型 ID 对应（例如 `UVR-MDX-NET-Inst_HQ_3.onnx`）。

## 运行时

分离运行时需要 PyTorch，建议使用独立环境：

```powershell
py -3.12 -m venv C:\aibox\separation-venv
C:\aibox\separation-venv\Scripts\python.exe -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu124
C:\aibox\separation-venv\Scripts\python.exe -m pip install demucs
# 可选：UVR / MDX
C:\aibox\separation-venv\Scripts\python.exe -m pip install "audio-separator[gpu]"
$env:AIBOX_SEPARATION_PYTHON="C:\aibox\separation-venv\Scripts\python.exe"
$env:AIBOX_SEPARATION_DEVICE="auto"
```

重启 AIBox 后 `/api/separations/status`：

- `demucs_ready` 表示 `python -c "import demucs"` 成功；
- `audio_separator_ready` 表示 `audio-separator` 命令或 Python 包存在；
- 模型列表的 `available` 根据运行时与是否处于演示模式计算。

也可以只安装 Demucs，此时选 UVR 模型会提示运行时未安装。

## 演示引擎

```powershell
$env:AIBOX_DEMO_SEPARATION="1"
```

演示模式用 FFmpeg 的高/低通滤波生成“人声/伴奏/鼓/贝斯/其他”示意分轨，用于验证 UI、任务、音频播放和下载，**不是真实分离**。

## API

```http
GET  /api/separations/status
GET  /api/separations?limit=30
POST /api/separations          (multipart: file, model_id, mode)
GET  /api/separations/{id}
POST /api/separations/{id}/cancel
DELETE /api/separations/{id}
GET  /api/separations/files/{job_id}/{filename}
```

创建：

```bash
curl http://127.0.0.1:8765/api/separations \
  -F "file=@song.wav" \
  -F "model_id=htdemucs" \
  -F "mode=instrumental"
```

返回任务对象，包含 `status`、`progress`、`outputs[]`（role / label / url）。通过 `GET /api/separations/{id}` 轮询；`outputs[].url` 可直接播放或下载 WAV。

## 存储

- 上传源文件：`<data>/uploads/sep_<id>.<ext>`
- 分轨：`<data>/separations/<id>/`
- 数据库：`<data>/state/aibox.db` 的 `separations` 表
- 删除记录会同步删除源文件与分轨。

## 限制

- 默认单任务串行，避免多个 Demucs 同时占满显存。
- Demucs 首次运行需要下载权重，可能较慢；无网络时会失败。
- UVR 模型文件需要提前放入 `models/separator`，AIBox 不自动下载 UVR 权重。
- 真实 Demucs / UVR 权重尚未在本机下载实测；演示模式与 API 流程已通过测试。
- 输出为 WAV；如需 MP3，可在下载后用 FFmpeg 转换。
- 分离不进入 ASR/TTS/Image 弹性槽位；运行时由 Demucs/audio-separator 子进程管理。
