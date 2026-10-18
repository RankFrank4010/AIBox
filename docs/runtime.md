# 多模型与弹性调度

## 当前驻留模型

AIBox v0.2 为每类引擎维护一个模型槽：

| 类型 | 引擎 | 槽位 |
| --- | --- | --- |
| ASR | faster-whisper / CTranslate2 | 1 个 Whisper 模型 |
| TTS | IndexTTS worker（独立 Python 进程） | 1 个 IndexTTS 模型 |
| Image | Diffusers worker（独立 Python 进程） | 1 个 SD / FLUX / Qwen-Image 模型 |
| LLM | llama-server（独立进程） | 1 个 GGUF 模型 |

因此同一台电脑可以同时加载 **ASR + TTS + Image + LLM**（受 `elastic_max_loaded_models` 与显存预算限制），例如：

```text
Whisper Small (CUDA, ~3 GB) + IndexTTS 2.5 (~10 GB) + SDXL (~10 GB) + Qwen3 8B (~8 GB)
```

同一类型切换模型时，旧模型被换出，新模型被换入。模型下载不占驻留预算；只有加载到内存/显存才计入。

## 预算

运行时会计算：

- 有 CUDA：预算 = GPU 显存 − `elastic_gpu_reserve_gb`（默认 1.5 GB）
- 无 CUDA：预算 = 系统内存 − `elastic_ram_reserve_gb`（默认 2 GB）

模型估算来自模型目录中的 `memory_gb`。当预算不足时：

1. 按策略选择可换出的空闲模型；
2. 正在推理（busy）或固定驻留（pinned）的模型不会被换出；
3. 仍不足时返回明确的资源不足错误，而不是静默 OOM。

## 弹性模式

| 模式 | 行为 | 适合 |
| --- | --- | --- |
| `auto` | 自动跟随近期 ASR/TTS 请求热度；两类都能容纳时保留两者 | 默认 |
| `balanced` | 尽量各保留一个 ASR + TTS | 两类都常用 |
| `asr_focus` | ASR 受到保护；TTS 按需加载并在空闲后卸载 | 会议/字幕为主 |
| `tts_focus` | TTS 受到保护；ASR 按需加载 | 配音/播报为主 |
| `time_slice` | 每隔一段时间把焦点切换到热度更高的类型 | 分时段集中处理 |
| `custom` | 使用固定驻留类型、上限、TTL、预留 | 手动控制 |

### 自动模式

- 维护一个最近请求窗口（默认 300 秒）。
- 当某类型占比超过约 72% 且样本足够时，把它设为焦点。
- 没有明显偏向时，两类平等竞争，优先用 LRU 换出。
- 如果两类能同时容纳，不主动换出；空闲 TTL 到期后再释放。

### 时间片模式

- 每 `elastic_switch_interval_seconds`（默认 300 秒）重新选择主导类型。
- 窗口内没有请求时，在 ASR / TTS 之间交替。
- 主导类型在容量竞争中拥有更高优先级；非主导类型在空闲后卸载。

### 自定义模式

- `elastic_pinned_kinds`：`["asr"]`、`["tts"]` 或两者。
- `elastic_max_loaded_models`：1–4。
- `elastic_idle_ttl_seconds`：0 表示不按空闲时间卸载。
- `elastic_gpu_reserve_gb` / `elastic_ram_reserve_gb`：设备预留。

## 配置入口

WebUI：

- 「设置 → 弹性调度」：模式、TTL、切换窗口、常驻上限、固定类型、预留。
- 「硬件与引擎」：实时预算、焦点、需求计数、已加载模型、最近换出。

API：

```http
GET /api/runtime
PATCH /api/runtime
POST /api/runtime/unload/{kind}
```

```json
{
  "elastic_mode": "time_slice",
  "elastic_idle_ttl_seconds": 600,
  "elastic_switch_interval_seconds": 300,
  "elastic_max_loaded_models": 4,
  "elastic_gpu_reserve_gb": 1.5,
  "elastic_ram_reserve_gb": 2,
  "elastic_pinned_kinds": ["asr"]
}
```

也可以直接通过 `PATCH /api/settings` 写入相同的 `elastic_*` 字段。

## 换入换出语义

- 任务提交时先记录需求计数；推理开始时标记 busy，结束释放。
- 加载新模型前调用容量检查；如需要会先卸载其他空闲类型。
- 卸载 ASR 会释放 CTranslate2 模型；卸载 TTS 会终止 IndexTTS worker 进程并回收 PyTorch 显存。
- 被换出的模型不会自动重新预加载；下一次请求会重新加载（首次加载可能较慢）。
- 空闲 TTL 从最后一次推理结束开始计算；固定驻留类型不会被 TTL 卸载。

## 限制

- 当前每个类型只有一个槽位，不支持同时加载两个 Whisper 或两个 IndexTTS 变体。
- 预算使用估算值，不是驱动级精确计量；建议保留 1–2 GB 显存余量。
- ASR 推理锁保证同一模型不并发解码；ASR 与 TTS 可以并行运行（如果显存足够）。
- 任务队列默认并发 1（可在设置中调整，重启后生效）；外部请求会排队。
- NPU 目前不参与驻留预算，因为 Whisper/IndexTTS 的 NPU 后端尚未启用。

## 未来

- 同类型多槽位与模型池。
- 真实显存/内存遥测与动态预算。
- 预加载热门模型、请求预热与更细粒度的优先级队列。
- NPU / Metal 加速 slot。
