# 硬件与模型支持矩阵

## 原则

AIBox 把硬件状态拆成三层，界面上不混用：

1. **检测到设备**：驱动 / 总线 / PnP 能看到设备；
2. **运行时可用**：推理库真正能加载所需用户态库；
3. **ASR / TTS 可用**：当前版本的 Whisper / IndexTTS 引擎能实际选择该后端。

只有第 3 层才会出现在可执行的推理设备选项中。

## 当前推理后端

| 后端 | 平台 | 状态 | 计算类型 | 备注 |
| --- | --- | --- | --- | --- |
| CTranslate2 CPU | Windows / macOS / Linux | ✅ 可用 | int8 / int8_float32 / float32 | 默认 CPU int8 |
| CTranslate2 CUDA | Windows / Linux + NVIDIA | ✅ 可用（需运行时） | float16 / int8_float16 / float32 | 需要 cuBLAS + cuDNN 9 |
| IndexTTS (PyTorch) | Windows / Linux + NVIDIA / CPU | ✅ 可用（需独立运行时） | bf16 / fp16（以模型为准） | 独立 worker；模型 5 GB+ |
| Apple Metal | macOS + Apple Silicon | 🟡 部分 | — | WebUI 与桌面壳可用；Whisper 当前走 CPU |
| NPU（OpenVINO / QNN） | Windows / Linux | 🟡 仅检测与编排 | — | 设备发现、展示、能力矩阵；ASR 适配中 |
| DirectML / ROCm | Windows / Linux | ⚪ 计划 | — | 未来多厂商 GPU 加速 |
| Core ML / ANE | iOS | ⚪ 规划 | — | 移动端规划，不执行 |

### CUDA 运行时

CTranslate2 的 CUDA 设备枚举只代表驱动可见。实际推理还需要：

- NVIDIA 驱动；
- CUDA 12 运行时；
- cuBLAS 12；
- cuDNN 9。

推荐使用 pip 版用户态库，不需要安装完整 CUDA Toolkit：

```powershell
.\.venv\Scripts\python.exe -m pip install -e "services/api[cuda12]"
```

或：

```bash
.venv/bin/python -m pip install -e "services/api[cuda12]"
```

AIBox 会自动把 `site-packages/nvidia/*/{bin,lib}` 加入加载路径。

如果只检测到驱动、缺少 cuBLAS / cuDNN：

- 系统页显示“运行时缺失”；
- GPU 不会出现在可执行 ASR 设备中；
- `device=auto` 回退 CPU；
- 极少见的推理期 CUDA 错误也会触发一次 CPU 重试。

## 已完成的实测

在 Windows 11 + Intel i9-13900K + NVIDIA RTX 4070 Ti SUPER 16 GB 上：

- 硬件识别：CPU 32 线程 / 31.7 GB 内存 / RTX 4070 Ti SUPER / CUDA 12 运行时；
- `Whisper Tiny`：CUDA float16 转写成功；
- `Whisper Small`：CUDA float16 转写中文语音成功；
- 故意移除 CUDA 用户态库时：自动识别为 runtime-missing，CPU int8 转写成功；
- 真实上传 9 秒 WAV，返回 2–3 个带时间轴的中文段落；
- SRT / VTT / TXT / JSON 导出通过测试。

macOS 与 Linux 的代码路径已实现，桌面壳需要在对应平台构建。macOS 的 Metal Whisper 后端尚未启用。

## Whisper 模型

| ID | 名称 | 体积 | 参数 | 速度 | 精度 | 建议设备 | 语言 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `tiny` | Whisper Tiny | 75 MB | 39M | 5.0 | 1.6 | 低功耗 CPU | 99 |
| `base` | Whisper Base | 145 MB | 74M | 4.6 | 2.2 | 日常 CPU | 99 |
| `small` | Whisper Small | 484 MB | 244M | 3.7 | 3.2 | CPU 甜点 | 99 |
| `medium` | Whisper Medium | 1.53 GB | 769M | 2.4 | 4.0 | GPU 6 GB+ | 99 |
| `large-v3-turbo` | Whisper Large v3 Turbo | 1.62 GB | 809M | 3.9 | 4.3 | GPU 6 GB+ | 99 |
| `large-v3` | Whisper Large v3 | 3.09 GB | 1.55B | 2.0 | 4.8 | GPU 10 GB+ | 99 |
| `distil-large-v3` | Distil Whisper Large v3 | 1.51 GB | 756M | 4.2 | 4.2 | 英文长音频 | 英语 |

速度为相对主观评分（1–5），用于 UI 比较，不是 benchmark。实际速度取决于设备、音频长度、VAD、beam size 和并发。

### 推荐策略

- CUDA 可用且显存 ≥ 10 GB：`large-v3`
- CUDA 可用且显存 ≥ 6 GB：`large-v3-turbo`
- CUDA 可用且显存 ≥ 3 GB：`small`
- CPU / 系统内存 ≥ 16 GB：`small`
- CPU / 系统内存 ≥ 8 GB：`base`
- 其他：`tiny`

推荐只是默认值，用户始终可以在模型库下载任意模型并手动选择。

## IndexTTS 模型

| ID | 名称 | 体积 | 语言 | 建议 | 备注 |
| --- | --- | --- | --- | --- | --- |
| `indextts-2.5` | IndexTTS 2.5 | 5.11 GB | 中 / 英 / 日 / 西 / 阿 | 10 GB+ 显存 | 音色克隆 + 情绪 + 语速 |
| `indextts-2` | IndexTTS 2 | 5.49 GB | 中 / 英 | 10 GB+ 显存 | 稳定兼容 |

IndexTTS 通过独立 Python worker 加载，模型放在 `models/tts/`；运行前需设置 `AIBOX_INDEXTTS_HOME` 和 `AIBOX_INDEXTTS_PYTHON`，或运行 `scripts/setup-indextts.ps1`。`AIBOX_DEMO_TTS=1` 只输出提示音，用于 UI/协议验证。

## 图像模型

| ID | 名称 | 体积 | 建议显存 | 备注 |
| --- | --- | --- | --- | --- |
| `sd15` | Stable Diffusion 1.5 | 约 4.2 GB | 6 GB+ | LoRA / ControlNet 生态 |
| `sdxl` | SDXL | 约 6.9 GB | 10 GB+ | 1024 文生图 |
| `flux1-schnell` | FLUX.1 schnell | 约 23.8 GB | 20 GB+ | 快速、文字渲染 |
| `flux1-dev` | FLUX.1 dev | 约 23.8 GB | 20 GB+ | 需接受上游许可 |
| `qwen-image` | Qwen-Image | 约 40 GB | 32 GB+ / 量化 | 中文与文字排版 |

图像模型通过 `AIBOX_IMAGE_PYTHON` 指向的 Diffusers 环境或 ComfyUI 运行。`AIBOX_DEMO_IMAGE=1` 只生成示意图。详见 [图像生成](images.md)。

## 人声分离

| 模型 | 引擎 | 分轨 | 建议 |
| --- | --- | --- | --- |
| htdemucs / htdemucs_ft | Demucs | 4 | 6 GB+ 显存 / CPU 可用 |
| mdx_extra | Demucs MDX | 4 | 8 GB+ 显存 |
| UVR MDX Inst / Voc | audio-separator | 2 | 4 GB+ 显存 / CPU 可用 |

分离运行时通过 `AIBOX_SEPARATION_PYTHON` 指定，`AIBOX_DEMO_SEPARATION=1` 只做滤波示意。详见 [人声/伴奏分离](separation.md)。

## 视频生成

- MiniMax H3 / Hailuo 02：云端 API，不在本机加载权重，需要网络与 `MINIMAX_API_KEY`；
- Wan2.1 / HunyuanVideo / LTX-Video：通过 ComfyUI 本地运行，显存需求取决于工作流与量化；
- 演示视频：FFmpeg，仅用于 UI/CI。

视频默认串行执行，避免同时占用显存或云端配额。详见 [视频生成](video.md)。

## 语言模型

| 规模 | 量化 | 建议内存 / 显存 | 备注 |
| --- | --- | --- | --- |
| 3B | Q4_K_M | 4–5 GB | 低配 / 快速草稿 |
| 7B–8B | Q4_K_M | 7–8 GB | 默认本地助手 |
| 12B | Q4_K_M | 10 GB+ | 长文档 / 多语言 |

本地 GGUF 通过 `llama-server` 运行，`AIBOX_LLM_GPU_LAYERS` 控制 GPU 卸载；外部 OpenAI 兼容服务不占本地预算。详见 [大语言模型](llm.md)。

ASR 与 TTS 同时驻留时的预算、换出规则见 [多模型与弹性调度](runtime.md)。社区外部适配器（`openai-http` / `command`）由外部进程或服务管理资源，不进入本地驻留预算；详见 [社区适配](community.md)。

## 资源预算

| 模型 | 模型文件 | 运行时内存 / 显存（近似） | 适合 |
| --- | --- | --- | --- |
| Tiny | 75 MB | 1 GB | 实时字幕、低功耗、草稿 |
| Base | 145 MB | 1.5 GB | 语音笔记 |
| Small | 484 MB | 3 GB | 会议、中文、CPU 质量 |
| Medium | 1.53 GB | 6 GB | 访谈、GPU |
| Large v3 Turbo | 1.62 GB | 6 GB | GPU 实时、速度优先 |
| Large v3 | 3.09 GB | 10 GB | 专业字幕、复杂口音 |
| Distil Large v3 | 1.51 GB | 6 GB | 英文长音频 |

下载前会检查磁盘空间；推理时需要注意显存/内存峰值。

## 排查

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| GPU 显示“已检测 / 仅检测” | 缺少 cuBLAS / cuDNN | 安装 `[cuda12]` 或系统 CUDA 运行时 |
| `Library cublas64_12.dll is not found` | CUDA 用户态库缺失 | 同上；AIBox 会自动 CPU 回退 |
| 模型下载失败 | 网络 / 地区 / 授权 | 配置 `HF_TOKEN` 或 `AIBOX_HF_ENDPOINT` 镜像 |
| 音频解码失败 | 缺少 PyAV / FFmpeg 或格式异常 | 安装 `av` 与 ffmpeg；优先 WAV / MP3 / M4A |
| 首次推理很慢 | CTranslate2 初始化与模型加载 | 正常，后续任务会复用缓存模型 |
| 长音频转写慢 | CPU + beam size 偏高 | 用 `small` / `tiny`，降低 beam，开启 VAD，优先 GPU |

## 未来 NPU 接入

NPU 路径需要同时解决：

- 设备级运行时：Intel OpenVINO、AMD Vitis AI / XDNA、Qualcomm QNN；
- 模型格式：ONNX / OpenVINO IR，而不是 CTranslate2；
- 算子与量化：Whisper encoder / decoder 的 NPU 支持；
- 内存与分块：移动 NPU 内存有限，需要按音频窗口调度；
- 回退链：NPU → GPU → CPU，且能力矩阵必须真实。

在这些条件满足之前，AIBox 不会把 NPU 标记为 Whisper 可用后端。
