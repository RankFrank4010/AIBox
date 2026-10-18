"""Fine-tuning dataset validation and training job execution.

Real training is intentionally delegated to an external command so AIBox does
not force a particular PyTorch/TRL/DeepSpeed stack into the API environment.
A deterministic demo runner keeps the management UI and CI self-contained.
"""

from __future__ import annotations

import csv
import json
import logging
import shlex
import subprocess
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from .config import AppConfig
from .training_store import TrainingStore

logger = logging.getLogger("aibox.training")

TRAINING_MODELS = [
    {
        "id": "qwen3-8b",
        "name": "Qwen3 8B",
        "hf_id": "Qwen/Qwen3-8B",
        "parameters": "8B",
        "license": "Apache-2.0",
        "qlora_gb": 12,
        "full_gb": 80,
    },
    {
        "id": "qwen2.5-7b",
        "name": "Qwen2.5 7B",
        "hf_id": "Qwen/Qwen2.5-7B-Instruct",
        "parameters": "7B",
        "license": "Apache-2.0",
        "qlora_gb": 10,
        "full_gb": 70,
    },
    {
        "id": "llama-3.1-8b",
        "name": "Llama 3.1 8B",
        "hf_id": "meta-llama/Llama-3.1-8B-Instruct",
        "parameters": "8B",
        "license": "Llama 3.1 Community",
        "qlora_gb": 12,
        "full_gb": 80,
    },
    {
        "id": "mistral-7b",
        "name": "Mistral 7B",
        "hf_id": "mistralai/Mistral-7B-Instruct-v0.3",
        "parameters": "7B",
        "license": "Apache-2.0",
        "qlora_gb": 10,
        "full_gb": 70,
    },
    {
        "id": "gemma-3-12b",
        "name": "Gemma 3 12B",
        "hf_id": "google/gemma-3-12b-it",
        "parameters": "12B",
        "license": "Gemma Terms",
        "qlora_gb": 16,
        "full_gb": 120,
    },
    {
        "id": "phi-3.5-mini",
        "name": "Phi-3.5 mini",
        "hf_id": "microsoft/Phi-3.5-mini-instruct",
        "parameters": "3.8B",
        "license": "MIT",
        "qlora_gb": 6,
        "full_gb": 40,
    },
]

METHODS = [
    {"id": "qlora", "label": "QLoRA", "note": "4-bit 量化，显存最省"},
    {"id": "lora", "label": "LoRA", "note": "16-bit 适配器"},
    {"id": "full", "label": "全量微调", "note": "显存需求最高"},
]

PARALLELISM = [
    {"id": "single", "label": "单卡"},
    {"id": "ddp", "label": "DDP 数据并行"},
    {"id": "fsdp", "label": "FSDP 分片"},
    {"id": "deepspeed", "label": "DeepSpeed ZeRO"},
]


class TrainingUnavailable(RuntimeError):
    pass


class TrainingCancelled(RuntimeError):
    pass


def validate_dataset(path: Path, filename: str) -> dict[str, Any]:
    suffix = path.suffix.lower()
    rows: list[dict[str, Any]] = []
    if suffix == ".jsonl":
        with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
            for index, line in enumerate(handle, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise TrainingUnavailable(f"JSONL 第 {index} 行不是合法 JSON：{exc}") from exc
                if not isinstance(item, dict):
                    raise TrainingUnavailable(f"JSONL 第 {index} 行必须是对象")
                if not any(key in item for key in ("messages", "text", "prompt", "completion", "instruction")):
                    raise TrainingUnavailable(
                        f"JSONL 第 {index} 行缺少 messages / text / prompt / instruction"
                    )
                if len(rows) < 5:
                    rows.append(item)
    elif suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise TrainingUnavailable("JSON 数据集必须是对象数组")
        rows = [item for item in data[:5] if isinstance(item, dict)]
        if not rows:
            raise TrainingUnavailable("JSON 数据集没有有效对象")
    elif suffix == ".csv":
        with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames:
                raise TrainingUnavailable("CSV 缺少表头")
            for index, item in enumerate(reader, start=1):
                if index <= 5:
                    rows.append(dict(item))
                if index > 100000:
                    break
    else:
        raise TrainingUnavailable("仅支持 .jsonl / .json / .csv")
    if suffix in {".jsonl", ".csv"}:
        count = 0
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if line.strip():
                    count += 1
        if suffix == ".csv":
            count = max(0, count - 1)
    else:
        count = len(json.loads(path.read_text(encoding="utf-8")))
    if count == 0:
        raise TrainingUnavailable("数据集为空")
    return {
        "format": suffix.lstrip("."),
        "rows": count,
        "preview": rows,
        "filename": filename,
    }


class TrainingEngine:
    def __init__(self, config: AppConfig, store: TrainingStore) -> None:
        self.config = config
        self.store = store

    def status(self) -> dict[str, Any]:
        return {
            "demo": self.config.demo_training,
            "command": bool(self.config.training_command),
            "models": TRAINING_MODELS,
            "methods": METHODS,
            "parallelism": PARALLELISM,
            "datasets": self.store.list_datasets(),
        }

    def run(
        self,
        job: dict[str, Any],
        dataset: dict[str, Any],
        log_path: Path,
        progress: Callable[[float, str], None],
        cancel_check: Callable[[], bool],
    ) -> dict[str, Any]:
        output_dir = Path(job["output_dir"])
        output_dir.mkdir(parents=True, exist_ok=True)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        if self.config.demo_training:
            return self._demo(job, dataset, output_dir, log_path, progress, cancel_check)
        if not self.config.training_command:
            raise TrainingUnavailable(
                "训练运行时未配置。请设置 AIBOX_TRAIN_COMMAND，"
                "或设置 AIBOX_DEMO_TRAINING=1 使用演示训练。"
            )
        return self._command(job, dataset, output_dir, log_path, progress, cancel_check)

    def _demo(
        self,
        job: dict[str, Any],
        dataset: dict[str, Any],
        output_dir: Path,
        log_path: Path,
        progress: Callable[[float, str], None],
        cancel_check: Callable[[], bool],
    ) -> dict[str, Any]:
        config = job.get("config") or {}
        stages = [
            "加载基础模型",
            "加载数据集",
            "构建 LoRA 适配器",
            "Tokenizer 预处理",
            "第 1 / 3 epoch",
            "第 2 / 3 epoch",
            "第 3 / 3 epoch",
            "保存适配器",
            "生成训练摘要",
        ]
        with log_path.open("w", encoding="utf-8") as log:
            log.write(f"AIBox demo training · {job['name']}\n")
            log.write(f"base_model={job['base_model']} method={job['method']}\n")
            log.write(f"dataset={dataset['name']} rows={dataset['rows']}\n")
            log.flush()
            for index, stage in enumerate(stages):
                if cancel_check():
                    raise TrainingCancelled("任务已取消")
                time.sleep(0.45)
                progress((index + 1) / len(stages) * 98, stage)
                log.write(f"[{index + 1}/{len(stages)}] {stage}\n")
                log.flush()
        (output_dir / "README.txt").write_text(
            "AIBox demo fine-tuning artifacts.\n"
            "This directory is a management-flow placeholder, not a trained adapter.\n",
            encoding="utf-8",
        )
        (output_dir / "adapter_config.json").write_text(
            json.dumps(
                {
                    "base_model_name_or_path": job["base_model"],
                    "peft_type": "LORA" if job["method"] != "full" else "FULL",
                    "r": config.get("lora_r", 16),
                    "lora_alpha": config.get("lora_alpha", 32),
                    "demo": True,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        summary = {
            "job_id": job["id"],
            "base_model": job["base_model"],
            "method": job["method"],
            "dataset_rows": dataset["rows"],
            "epochs": config.get("epochs", 3),
            "demo": True,
        }
        (output_dir / "training_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        progress(100, "演示训练完成")
        return {"summary": summary, "artifacts": self._artifacts(output_dir)}

    def _command(
        self,
        job: dict[str, Any],
        dataset: dict[str, Any],
        output_dir: Path,
        log_path: Path,
        progress: Callable[[float, str], None],
        cancel_check: Callable[[], bool],
    ) -> dict[str, Any]:
        config = job.get("config") or {}
        values = {
            "base_model": job["base_model"],
            "dataset": dataset["path"],
            "output_dir": str(output_dir),
            "method": job["method"],
            "epochs": config.get("epochs", 3),
            "batch_size": config.get("batch_size", 1),
            "grad_accum": config.get("grad_accum", 8),
            "lr": config.get("learning_rate", 2e-4),
            "max_seq": config.get("max_seq", 2048),
            "lora_r": config.get("lora_r", 16),
            "lora_alpha": config.get("lora_alpha", 32),
            "device": job["device"],
            "parallel": job["parallel_strategy"],
            "job_id": job["id"],
        }
        try:
            command = self.config.training_command.format(**values)
        except KeyError as exc:
            raise TrainingUnavailable(f"训练命令占位符未知：{exc}") from exc
        argv = shlex.split(command, posix=False)
        if not argv:
            raise TrainingUnavailable("AIBOX_TRAIN_COMMAND 为空。")
        progress(2, "启动训练进程")
        with log_path.open("w", encoding="utf-8") as log:
            process = subprocess.Popen(
                argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                cwd=str(output_dir),
                bufsize=1,
            )
            assert process.stdout is not None
            started = time.monotonic()
            for line in process.stdout:
                log.write(line)
                log.flush()
                if cancel_check():
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                    raise TrainingCancelled("任务已取消")
                elapsed = time.monotonic() - started
                progress(min(95, 5 + elapsed / 4), "训练中")
            code = process.wait()
        if code != 0:
            raise TrainingUnavailable(f"训练进程退出码 {code}，请查看日志。")
        summary = {
            "job_id": job["id"],
            "base_model": job["base_model"],
            "method": job["method"],
            "dataset_rows": dataset["rows"],
            "command": command,
        }
        (output_dir / "training_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        progress(100, "训练完成")
        return {"summary": summary, "artifacts": self._artifacts(output_dir)}

    def _artifacts(self, output_dir: Path) -> list[dict[str, Any]]:
        if not output_dir.is_dir():
            return []
        result = []
        for path in sorted(output_dir.rglob("*")):
            if path.is_file():
                result.append(
                    {
                        "name": path.name,
                        "path": path.relative_to(output_dir).as_posix(),
                        "bytes": path.stat().st_size,
                    }
                )
        return result


class TrainingJobs:
    def __init__(self, config: AppConfig, store: TrainingStore, engine: TrainingEngine) -> None:
        self.config = config
        self.store = store
        self.engine = engine
        self.executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="aibox-training"
        )
        self._events: dict[str, threading.Event] = {}
        self._lock = threading.Lock()

    def submit(self, job_id: str) -> None:
        event = threading.Event()
        with self._lock:
            self._events[job_id] = event
        self.executor.submit(self._run, job_id, event)

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            event = self._events.get(job_id)
        if event is None:
            return False
        event.set()
        self.store.update_job(job_id, status="cancelling", stage="正在取消")
        return True

    def shutdown(self) -> None:
        with self._lock:
            for event in self._events.values():
                event.set()
        self.executor.shutdown(wait=False, cancel_futures=True)

    def _run(self, job_id: str, event: threading.Event) -> None:
        record = self.store.get_job(job_id)
        if record is None:
            return
        dataset = self.store.get_dataset(record["dataset_id"])
        if dataset is None:
            self.store.update_job(
                job_id, status="failed", stage="训练失败", error="数据集不存在"
            )
            return
        log_path = self.config.training_logs_dir / f"{job_id}.log"
        last_write = 0.0

        def report(value: float, stage: str) -> None:
            nonlocal last_write
            now = time.monotonic()
            if now - last_write < 0.3 and value < 99:
                return
            self.store.update_job(
                job_id,
                status="running",
                stage=stage,
                progress=round(max(0.0, min(100.0, value)), 1),
            )
            last_write = now

        try:
            if event.is_set():
                raise TrainingCancelled("任务已取消")
            self.store.update_job(
                job_id,
                status="running",
                stage="准备训练",
                progress=1,
                log_path=str(log_path),
                error=None,
            )
            result = self.engine.run(
                record,
                dataset,
                log_path,
                report,
                event.is_set,
            )
            if event.is_set():
                raise TrainingCancelled("任务已取消")
            self.store.update_job(
                job_id,
                status="completed",
                stage="训练完成",
                progress=100,
                metrics_json=json.dumps(
                    {"summary": result.get("summary"), "artifacts": result.get("artifacts")},
                    ensure_ascii=False,
                ),
                log_path=str(log_path),
                error=None,
            )
        except TrainingCancelled:
            self.store.update_job(
                job_id, status="cancelled", stage="已取消", error=None
            )
        except TrainingUnavailable as exc:
            logger.warning("training %s unavailable: %s", job_id, exc)
            self.store.update_job(
                job_id, status="failed", stage="训练失败", error=str(exc)
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("training %s failed", job_id)
            self.store.update_job(
                job_id, status="failed", stage="训练失败", error=f"训练失败：{exc}"
            )
        finally:
            with self._lock:
                self._events.pop(job_id, None)
