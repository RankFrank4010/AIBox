# 模型微调与训练管理

AIBox 新增「模型微调」WebUI，用于管理数据集、微调任务、训练日志和产物。默认界面是简单表单；学习率、LoRA rank、序列长度等放在高级设置。

## 页面能力

- 上传 / 校验数据集（JSONL、JSON、CSV）；
- 选择基础模型、LoRA / QLoRA / 全量微调；
- 选择设备与训练并行策略；
- 训练任务排队、进度、日志、取消、删除；
- 产物列表与下载；
- 演示训练运行器，用于 UI 与 CI。

## 数据集

支持格式：

```jsonl
{"messages":[{"role":"user","content":"你好"},{"role":"assistant","content":"你好！"}]}
```

也支持：

- `{"text":"..."}`
- `{"prompt":"...","completion":"..."}`
- `{"instruction":"...", ...}`

JSON 文件必须是对象数组；CSV 使用表头 + 行。上传后会做基础校验并显示行数。

数据集保存在：

```text
<data>/training/datasets/
```

## 训练任务

字段：

| 字段 | 说明 |
| --- | --- |
| `name` | 任务名 |
| `base_model` | Hugging Face repo id 或预设 |
| `method` | `qlora` / `lora` / `full` |
| `dataset_id` | 已上传数据集 |
| `epochs` / `batch_size` / `grad_accum` | 训练超参 |
| `learning_rate` / `max_seq` | 优化与上下文 |
| `lora_r` / `lora_alpha` | LoRA 维度 |
| `device` | `auto` / `cuda:0` / `cpu` |
| `parallel_strategy` | `single` / `ddp` / `fsdp` / `deepspeed` |

任务与产物：

```text
<data>/training/runs/<job_id>/
<data>/training/logs/<job_id>.log
```

## 运行器

AIBox 不把 PyTorch / TRL / DeepSpeed 强塞进 API 环境，训练通过外部命令运行。

### 演示运行器

```powershell
$env:AIBOX_DEMO_TRAINING="1"
```

演示运行器写入占位适配器、训练摘要和日志，用于验证页面、任务、取消、日志与产物，不产生真实权重。

### 外部训练命令

```powershell
$env:AIBOX_TRAIN_COMMAND="C:\train-venv\Scripts\python.exe C:\train\finetune.py --base {base_model} --data {dataset} --out {output_dir} --method {method} --epochs {epochs} --parallel {parallel}"
```

支持占位符：

| 占位符 | 含义 |
| --- | --- |
| `{base_model}` | 基础模型 repo |
| `{dataset}` | 数据集绝对路径 |
| `{output_dir}` | 产物目录 |
| `{method}` | qlora / lora / full |
| `{epochs}` `{batch_size}` `{grad_accum}` | 训练超参 |
| `{lr}` `{max_seq}` `{lora_r}` `{lora_alpha}` | 优化参数 |
| `{device}` `{parallel}` | 设备与并行策略 |
| `{job_id}` | 任务 ID |

示例训练脚本可自行使用 Transformers + PEFT + TRL / DeepSpeed。AIBox 负责调度、日志与产物管理。

## 并行策略

- `single`：单卡；
- `ddp`：`torchrun` / DDP 数据并行；
- `fsdp`：FSDP 参数分片；
- `deepspeed`：DeepSpeed ZeRO。

这些是传给外部训练命令的语义字段，具体实现由训练脚本决定。AIBox 不内置分布式启动器。

## API

```http
GET  /api/training/status
GET  /api/training/datasets
POST /api/training/datasets          (multipart)
DELETE /api/training/datasets/{id}
GET  /api/training/jobs
POST /api/training/jobs
GET  /api/training/jobs/{id}
POST /api/training/jobs/{id}/cancel
DELETE /api/training/jobs/{id}
GET  /api/training/jobs/{id}/logs
GET  /api/training/artifacts/{job_id}/{file}
```

## 限制

- 当前仓库不包含真实训练脚本；演示运行器只生成占位产物。
- 外部训练命令由用户提供，AIBox 不校验其 GPU 使用、数据安全或模型许可。
- 训练任务默认串行，避免多个训练同时占满显存。
- 基础模型、数据集和训练依赖需要用户自行准备。
- 真实 QLoRA / LoRA 训练未在本机运行；数据集、任务、日志、产物与 UI 流程已测试。
