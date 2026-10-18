"""Fine-tuning datasets and training job HTTP API."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..config import AppConfig
from ..training import (
    METHODS,
    PARALLELISM,
    TRAINING_MODELS,
    TrainingEngine,
    TrainingJobs,
    TrainingUnavailable,
    validate_dataset,
)
from ..training_store import TrainingStore

DATASET_SUFFIXES = {".jsonl", ".json", ".csv"}


class TrainingRequest(BaseModel):
    name: str = "my-finetune"
    base_model: str = "Qwen/Qwen3-8B"
    method: str = "qlora"
    dataset_id: str
    output_name: str | None = None
    epochs: int = 3
    batch_size: int = 1
    grad_accum: int = 8
    learning_rate: float = 2e-4
    max_seq: int = 2048
    lora_r: int = 16
    lora_alpha: int = 32
    device: str = "auto"
    parallel_strategy: str = "single"
    quantization: str = "4bit"


def _dataset_payload(record: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in record.items()
        if key not in {"path", "preview_json"}
    }


def _job_payload(config: AppConfig, record: dict[str, Any]) -> dict[str, Any]:
    public = {
        key: value
        for key, value in record.items()
        if key not in {"config_json", "output_dir", "log_path"}
    }
    public["artifacts"] = _artifacts(Path(record.get("output_dir") or ""))
    public["log_url"] = f"/api/training/jobs/{record['id']}/logs"
    return public


def _artifacts(output_dir: Path) -> list[dict[str, Any]]:
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
                    "url": f"/api/training/artifacts/{output_dir.name}/{path.relative_to(output_dir).as_posix()}",
                }
            )
    return result


def create_training_router(
    config: AppConfig,
    store: TrainingStore,
    jobs: TrainingJobs,
    engine: TrainingEngine,
) -> APIRouter:
    router = APIRouter(prefix="/api/training", tags=["training"])

    @router.get("/status")
    async def status() -> dict[str, Any]:
        return {
            **engine.status(),
            "jobs": [_job_payload(config, record) for record in store.list_jobs(30)],
        }

    # -------------------------------------------------------------- datasets
    @router.get("/datasets")
    async def list_datasets() -> dict[str, Any]:
        return {"items": [_dataset_payload(item) for item in store.list_datasets()]}

    @router.post("/datasets", status_code=201)
    async def upload_dataset(
        file: UploadFile = File(...),
        name: str = Form(""),
    ) -> dict[str, Any]:
        filename = file.filename or "dataset.jsonl"
        suffix = Path(filename).suffix.lower()
        if suffix not in DATASET_SUFFIXES:
            raise HTTPException(status_code=400, detail="仅支持 .jsonl / .json / .csv")
        dataset_id = "ds_" + uuid.uuid4().hex[:12]
        target = config.training_datasets_dir / f"{dataset_id}{suffix}"
        size = 0
        try:
            with target.open("wb") as handle:
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > config.max_upload_mb * 1024 * 1024:
                        raise HTTPException(status_code=413, detail="数据集文件过大")
                    handle.write(chunk)
        except HTTPException:
            target.unlink(missing_ok=True)
            raise
        except OSError as exc:
            target.unlink(missing_ok=True)
            raise HTTPException(status_code=500, detail=f"保存数据集失败：{exc}") from exc
        finally:
            await file.close()
        if size == 0:
            target.unlink(missing_ok=True)
            raise HTTPException(status_code=400, detail="数据集为空")
        try:
            meta = validate_dataset(target, filename)
        except TrainingUnavailable as exc:
            target.unlink(missing_ok=True)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        record = store.create_dataset(
            id=dataset_id,
            name=name.strip() or Path(filename).stem,
            path=str(target),
            format=meta["format"],
            size_bytes=size,
            rows=meta["rows"],
            preview=meta["preview"],
        )
        return _dataset_payload(record)

    @router.delete("/datasets/{dataset_id}")
    async def delete_dataset(dataset_id: str) -> dict[str, Any]:
        record = store.get_dataset(dataset_id)
        if record is None:
            raise HTTPException(status_code=404, detail="数据集不存在")
        if any(job["dataset_id"] == dataset_id for job in store.list_jobs(200)):
            raise HTTPException(status_code=409, detail="数据集仍被训练任务引用")
        record = store.delete_dataset(dataset_id)
        if record is None:
            raise HTTPException(status_code=404, detail="数据集不存在")
        try:
            Path(record["path"]).unlink(missing_ok=True)
        except OSError:
            pass
        return {"ok": True}

    # ------------------------------------------------------------------- jobs
    @router.get("/jobs")
    async def list_jobs(limit: int = 30) -> dict[str, Any]:
        return {
            "items": [
                _job_payload(config, item)
                for item in store.list_jobs(max(1, min(200, limit)))
            ]
        }

    @router.post("/jobs", status_code=202)
    async def create_job(payload: TrainingRequest) -> dict[str, Any]:
        if payload.method not in {item["id"] for item in METHODS}:
            raise HTTPException(status_code=400, detail="未知训练方法")
        if payload.parallel_strategy not in {item["id"] for item in PARALLELISM}:
            raise HTTPException(status_code=400, detail="未知训练并行策略")
        dataset = store.get_dataset(payload.dataset_id)
        if dataset is None:
            raise HTTPException(status_code=404, detail="数据集不存在")
        base_model = payload.base_model.strip()
        if not base_model:
            raise HTTPException(status_code=400, detail="基础模型不能为空")
        preset = next(
            (item for item in TRAINING_MODELS if item["hf_id"] == base_model or item["id"] == payload.base_model),
            None,
        )
        if preset is None and "/" not in base_model:
            raise HTTPException(status_code=400, detail="自定义基础模型请填写 Hugging Face repo id")
        job_id = "train_" + uuid.uuid4().hex[:10]
        output_dir = config.training_outputs_dir / job_id
        config_values = {
            "epochs": max(1, min(20, int(payload.epochs))),
            "batch_size": max(1, min(128, int(payload.batch_size))),
            "grad_accum": max(1, min(256, int(payload.grad_accum))),
            "learning_rate": max(1e-8, min(1.0, float(payload.learning_rate))),
            "max_seq": max(128, min(131072, int(payload.max_seq))),
            "lora_r": max(1, min(512, int(payload.lora_r))),
            "lora_alpha": max(1, min(1024, int(payload.lora_alpha))),
            "quantization": payload.quantization,
            "preset": preset["id"] if preset else None,
        }
        record = store.create_job(
            id=job_id,
            name=(payload.name.strip() or "my-finetune")[:80],
            base_model=base_model,
            method=payload.method,
            dataset_id=payload.dataset_id,
            output_dir=str(output_dir),
            device=payload.device,
            parallel_strategy=payload.parallel_strategy,
            config=config_values,
        )
        jobs.submit(job_id)
        return _job_payload(config, record)

    @router.get("/jobs/{job_id}")
    async def get_job(job_id: str) -> dict[str, Any]:
        record = store.get_job(job_id)
        if record is None:
            raise HTTPException(status_code=404, detail="训练任务不存在")
        return _job_payload(config, record)

    @router.post("/jobs/{job_id}/cancel")
    async def cancel_job(job_id: str) -> dict[str, Any]:
        record = store.get_job(job_id)
        if record is None:
            raise HTTPException(status_code=404, detail="训练任务不存在")
        jobs.cancel(job_id)
        return _job_payload(config, store.get_job(job_id) or record)

    @router.delete("/jobs/{job_id}")
    async def delete_job(job_id: str) -> dict[str, Any]:
        record = store.get_job(job_id)
        if record is None:
            raise HTTPException(status_code=404, detail="训练任务不存在")
        if record["status"] in {"queued", "running", "cancelling"}:
            raise HTTPException(status_code=409, detail="任务仍在进行，请先取消")
        record = store.delete_job(job_id)
        if record is None:
            raise HTTPException(status_code=404, detail="训练任务不存在")
        for path in (Path(record.get("log_path") or ""), Path(record["output_dir"])):
            try:
                if path.is_dir():
                    import shutil

                    shutil.rmtree(path, ignore_errors=True)
                else:
                    path.unlink(missing_ok=True)
            except OSError:
                pass
        return {"ok": True}

    @router.get("/jobs/{job_id}/logs")
    async def get_logs(job_id: str, tail: int = 200) -> dict[str, Any]:
        record = store.get_job(job_id)
        if record is None:
            raise HTTPException(status_code=404, detail="训练任务不存在")
        path = Path(record.get("log_path") or "")
        if not path.is_file():
            return {"lines": [], "text": ""}
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        tail = max(1, min(2000, tail))
        return {"lines": lines[-tail:], "text": "\n".join(lines[-tail:])}

    @router.get("/artifacts/{job_id}/{file_path:path}")
    async def artifact(job_id: str, file_path: str) -> FileResponse:
        root = (config.training_outputs_dir / job_id).resolve()
        candidate = (root / file_path).resolve()
        if root not in candidate.parents or not candidate.is_file():
            raise HTTPException(status_code=404, detail="文件不存在")
        return FileResponse(candidate)

    return router
