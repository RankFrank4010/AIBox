# 多设备与并行推理

AIBox 把设备、模型和任务分成三层：

```text
设备池（cuda:0 / cuda:1 / cpu）
        │
任务调度（按策略选择设备）
        │
引擎（ASR / TTS / Image / LLM）
```

设置入口：**设置 → 多设备与并行推理**。

## 策略

| 策略 | 行为 | 适用 |
| --- | --- | --- |
| `auto` | 自动选择可用加速设备；LLM 单卡 | 默认 |
| `single` | 每个引擎使用一个设备 | 单卡 / 稳定优先 |
| `data` | 多个 ASR 任务按设备分配；每设备一个 Whisper 副本 | 多路转写 / 多 GPU |
| `tensor` | LLM 使用 llama.cpp `row` split，按 GPU 切张量 | 单模型多卡、低延迟 |
| `pipeline` | LLM 使用 llama.cpp `layer` split，按层切分 | 单模型多卡、显存不足 |
| `hybrid` | LLM tensor split + 其他任务数据并行 | 混合负载 |

单卡设备会自动退化为单设备，不会强行多卡。

## 设备池

`/api/devices` 返回：

- `devices`：`cuda:0`、`cuda:1`、`cpu` 等；
- `selected`：参与调度的设备；
- `assignments`：ASR / TTS / Image / LLM 当前分配；
- `active`：ASR 任务占用计数；
- `workers`：并发任务数。

设置中的“设备池”留空表示自动选择全部可用加速设备；CPU 始终可用。

## ASR 数据并行

当策略为 `data` 且设备池包含多个设备时，AIBox 为每个设备惰性创建独立 `WhisperEngine`：

- 每个副本有自己的 CTranslate2 模型与推理锁；
- 任务由调度器分配到不同 GPU；
- `parallel_workers` 控制转录并发数。

这适合批量音频、多路实时转写。ASR 副本不进入弹性预算的单一 `asr` 槽位，显存由设备池隔离；生产环境请按单卡显存选择模型大小。

## LLM 多 GPU

本地 llama.cpp 支持：

```text
--split-mode row      # tensor parallel
--split-mode layer    # pipeline parallel
--tensor-split 1,1    # 每张卡的比例
CUDA_VISIBLE_DEVICES  # 设备池映射
```

AIBox 根据策略与设备池生成这些参数，并设置 `--main-gpu`、`--parallel`。示例：

```text
策略 tensor + 设备池 cuda:0,cuda:1
→ CUDA_VISIBLE_DEVICES=0,1
→ --split-mode row --tensor-split 1,1
```

外部 vLLM / SGLang 的张量并行由上游服务自己配置；AIBox 只作为 OpenAI 兼容客户端。

## TTS / 图像

TTS 与 Diffusers worker 支持指定 `--device`，可以在不同 GPU 上并行运行 ASR + TTS + 图像任务。当前每个引擎仍是一个 worker；同模型多副本留给后续版本。

## API

```http
GET  /api/devices
POST /api/devices/refresh
PATCH /api/settings
```

设置字段：

```json
{
  "parallel_strategy": "data",
  "parallel_devices": ["cuda:0", "cuda:1"],
  "parallel_workers": 4,
  "asr_device": "auto",
  "tts_device": "cuda:1",
  "image_device": "cuda:0",
  "llm_device": "auto"
}
```

## 计算优先级

默认 **普通服务优先**：ASR / TTS / 图像等任务需要显存时，空闲的 LLM 会被换出；
新的 LLM 请求在普通服务有任务时会暂缓，但不会强制中断正在流式生成的 LLM。

设置字段：

```json
{
  "compute_priority_mode": "services_first",
  "compute_priority_windows": [
    {"start": "22:00", "end": "08:00", "days": [1, 2, 3, 4, 5]}
  ]
}
```

模式：

| 模式 | 行为 |
| --- | --- |
| `services_first` | 普通服务优先；无普通服务时 LLM 可用剩余资源 |
| `llm_first` | 始终优先大模型 |
| `scheduled` | 特殊时段内 LLM 优先，其余时间普通服务优先 |
| `auto` | 特殊时段优先 LLM；否则按普通服务需求自动平衡 |

时段使用服务器本地时间；`days` 采用周日=0、周一=1 … 周六=6。支持跨午夜，例如
`22:00 -> 08:00`。`/api/system` 的 `runtime.compute_priority` 返回当前生效策略、
是否处于 LLM 时段与普通服务压力。

> 已运行的 LLM 流不会因为普通服务到来而被强行终止；新请求会被暂缓，空闲 LLM
> 会在普通服务需要显存时被换出。

## 限制

- 张量 / 流水并行目前只接本地 llama.cpp；ComfyUI / Diffusers 的多卡切分由上游工作流负责。
- ASR 数据并行按设备复制模型，显存 × 设备数；没有跨设备张量切分。
- TTS / 图像当前是设备分配，不是同模型多副本。
- 切换策略或设备池后，已加载的本地模型建议重新加载 / 重启服务。
- 真实多卡机器未在本机验证；单卡设备路径已测试，调度与命令生成已做单元验证。
