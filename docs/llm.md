# 大语言模型

AIBox 支持两类语言模型运行方式：

| Provider | 适用 | 说明 |
| --- | --- | --- |
| `llama.cpp` | 本地 GGUF | 通过 `llama-server` 加载单个 GGUF 文件，OpenAI 兼容 |
| `openai` | 任意 OpenAI 兼容服务 | Ollama、LM Studio、vLLM、llama.cpp server、云端 API |
| `demo` | UI / CI | 确定性演示回复，不加载模型 |

默认界面只保留模型、输入框和发送按钮；系统提示、温度、最大 Token 放在「高级设置」。

## 本地 GGUF 模型

模型库的「语言模型」页签提供：

| ID | 参数 | 量化 | 体积 | 适合 |
| --- | --- | --- | --- | --- |
| `qwen3-8b` | 8B | Q4_K_M | 约 4.7 GB | 中文 / 推理 / 通用 |
| `qwen2.5-7b` | 7B | Q4_K_M | 约 4.4 GB | 中文写作 / 客服 |
| `llama-3.1-8b` | 8B | Q4_K_M | 约 4.6 GB | 英文 / 总结 / 代码 |
| `llama-3.2-3b` | 3B | Q4_K_M | 约 1.9 GB | 低显存 / 快速草稿 |
| `mistral-7b` | 7B | Q4_K_M | 约 4.1 GB | 英文 / RAG |
| `deepseek-r1-7b` | 7B | Q4_K_M | 约 4.4 GB | 推理 / 数学 |
| `gemma-3-12b` | 12B | Q4_K_M | 约 6.8 GB | 长文档 / 多语言 |
| `phi-3.5-mini` | 3.8B | Q4_K_M | 约 2.2 GB | 低显存 / 快速回答 |

下载时只拉取对应的单个 `.gguf` 文件，保存在：

```text
<data>/models/llm/<model_id>/<file>.gguf
```

## llama-server

本地推理使用 [`llama.cpp`](https://github.com/ggml-org/llama.cpp) 的 `llama-server`：

```powershell
# 方式一：把 llama-server 放在 PATH
llama-server --version

# 方式二：指定可执行文件
$env:AIBOX_LLAMA_SERVER="C:\llama.cpp\build\bin\llama-server.exe"
$env:AIBOX_LLM_GPU_LAYERS="99"
$env:AIBOX_LLM_CONTEXT="8192"
```

AIBox 首次对话时启动：

```text
llama-server -m <gguf> --host 127.0.0.1 --port <free> -c 8192 --n-gpu-layers 99 --parallel 1
```

启动日志写入 `<data>/logs/llama-server.log`。切换模型或卸载时自动停止旧进程。

> `--n-gpu-layers` 是 GPU 卸载层数。没有 CUDA 的机器可设置为 `0` 使用 CPU。

## OpenAI 兼容服务

任意实现 `/v1/chat/completions` 的服务都可以接入：

```powershell
# Ollama
$env:AIBOX_LLM_BASE_URL="http://127.0.0.1:11434/v1"
$env:AIBOX_LLM_MODEL="qwen2.5:7b"

# LM Studio
$env:AIBOX_LLM_BASE_URL="http://127.0.0.1:1234/v1"
$env:AIBOX_LLM_MODEL="local-model"

# vLLM / llama.cpp server
$env:AIBOX_LLM_BASE_URL="http://127.0.0.1:8000/v1"
$env:AIBOX_LLM_API_KEY="optional"
```

AIBox 会从 `/v1/models` 读取可用模型，在语言模型页展示。`llm_provider` 设置：

- `auto`：外部地址优先，其次本地 llama-server，最后 demo；
- `llama-cpp`：强制本地；
- `openai`：强制外部；
- `demo`：演示。

### NewAPI

NewAPI 是兼容 OpenAI 的模型网关，可以直接作为外部服务：

```powershell
$env:AIBOX_LLM_BASE_URL="https://newapi.franj2.top/v1"
$env:AIBOX_LLM_API_KEY="<NewAPI Token>"
$env:AIBOX_LLM_MODEL="<NewAPI Model ID>"
```

四号服务器的部署、模型池和双向接入方式见 [与 NewAPI 结合](newapi.md)。

## 对话 UI

- 流式输出与「停止」；
- Enter 发送，Shift+Enter 换行；
- 新对话、卸载模型；
- 温度、最大 Token、系统提示在高级设置；
- 本地/外部模型统一选择；
- 12 项导航，390px 移动端可用。

## OpenAI 兼容 API

```http
POST /v1/chat/completions
GET  /v1/models
```

非流式：

```bash
curl http://127.0.0.1:8765/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen3-8b","messages":[{"role":"user","content":"你好"}]}'
```

流式：

```bash
curl -N http://127.0.0.1:8765/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen3-8b","messages":[{"role":"user","content":"你好"}],"stream":true}'
```

本地 UI 使用：

```http
GET  /api/llm/status
POST /api/llm/chat
POST /api/llm/unload
```

`/api/llm/chat` 与 OpenAI 端点共用引擎；`stream=true` 返回 SSE `data:` 块。

## 弹性与资源

本地 GGUF 注册为 `llm` 弹性槽位，使用模型元数据中的内存估算参与预算。默认最多 4 个常驻模型（可在设置调整），LLM 空闲时可被换出。

MiniMax / 云端 LLM 不占本地预算；外部 OpenAI 服务由服务端管理资源。

## 限制

- 本地 GGUF 需要自行安装 `llama-server`；当前测试环境未下载真实 GGUF，演示与 fake OpenAI 服务已实测。
- 模型下载来自 Hugging Face，部分仓库可能受地区或授权限制。
- 当前对话仅保留在当前页面会话，不落库；刷新后清空。
- 未实现工具调用、函数调用、RAG、图片输入或语音对话。
- 温度/Top-p 等只暴露常用项；复杂采样参数由 llama-server / 上游默认值决定。


## 外置推理引擎

除 `llama.cpp` 外，设置中的 `llm_provider` 支持：

| Provider | 默认 Base URL | 说明 |
| --- | --- | --- |
| `vllm` | `http://127.0.0.1:8000/v1` | vLLM OpenAI Server，支持单机多卡 TP/PP |
| `sglang` | `http://127.0.0.1:30000/v1` | SGLang Runtime |
| `mlx` | `http://127.0.0.1:8080/v1` | Apple Silicon MLX / `mlx_lm.server` |
| `tensorrt-llm` | `http://127.0.0.1:8000/v1` | TensorRT-LLM OpenAI Server |
| `lmstudio` | `http://127.0.0.1:1234/v1` | LM Studio 本地服务 |
| `ollama` | `http://127.0.0.1:11434/v1` | Ollama OpenAI 兼容端点 |

环境变量：

```text
AIBOX_VLLM_BASE_URL / AIBOX_VLLM_MODEL
AIBOX_SGLANG_BASE_URL / AIBOX_SGLANG_MODEL
AIBOX_MLX_BASE_URL / AIBOX_MLX_MODEL
AIBOX_TENSORRT_LLM_BASE_URL / AIBOX_TENSORRT_LLM_MODEL
AIBOX_LMSTUDIO_BASE_URL / AIBOX_LMSTUDIO_MODEL
AIBOX_OLLAMA_BASE_URL / AIBOX_OLLAMA_MODEL
AIBOX_LLM_TP_SIZE
AIBOX_LLM_PP_SIZE
AIBOX_LLM_DIST_BACKEND
```

跨物理机张量并行需要外置引擎先建立 Ray/NCCL 集群，再在启动参数中设置
`--tensor-parallel-size` / `--pipeline-parallel-size`；AIBox 负责选择模型、路由请求
和记录拓扑，不替代 vLLM/SGLang/TensorRT-LLM 的分布式启动器。

