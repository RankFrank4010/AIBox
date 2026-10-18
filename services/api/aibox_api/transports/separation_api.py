"""Vocal / background separation HTTP API."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from ..config import AppConfig
from ..external import AUDIO_EXTENSIONS
from ..separation import SeparationEngine
from ..separation_jobs import SeparationJobs
from ..separation_store import SeparationStore


def _payload(config: AppConfig, record: dict[str, Any]) -> dict[str, Any]:
    outputs = []
    for item in record.get("outputs") or []:
        path = Path(item.get("path") or "")
        try:
            relative = path.relative_to(config.separation_outputs_dir).as_posix()
            url = f"/api/separations/files/{relative}"
        except ValueError:
            url = ""
        outputs.append(
            {
                "role": item.get("role"),
                "label": item.get("label") or item.get("role"),
                "filename": path.name,
                "url": url,
            }
        )
    public = {
        key: value
        for key, value in record.items()
        if key not in {"audio_path", "options", "outputs_json"}
    }
    return {
        **public,
        "outputs": outputs,
        "preview_url": outputs[0]["url"] if outputs else None,
    }


def create_separation_router(
    config: AppConfig,
    store: SeparationStore,
    jobs: SeparationJobs,
    engine: SeparationEngine,
) -> APIRouter:
    router = APIRouter(prefix="/api/separations", tags=["separations"])

    @router.get("/status")
    async def status() -> dict[str, Any]:
        return engine.status()

    @router.get("")
    async def list_jobs(limit: int = 30, offset: int = 0) -> dict[str, Any]:
        records = store.list(limit=max(1, min(100, limit)), offset=max(0, offset))
        return {"items": [_payload(config, record) for record in records]}

    @router.post("", status_code=202)
    async def create(
        file: UploadFile = File(...),
        model_id: str = Form("htdemucs"),
        mode: str = Form("instrumental"),
    ) -> dict[str, Any]:
        filename = file.filename or "audio.wav"
        suffix = Path(filename).suffix.lower()
        if suffix not in AUDIO_EXTENSIONS:
            raise HTTPException(status_code=400, detail="不支持的音频格式")
        if mode not in {"instrumental", "vocals", "stems"}:
            raise HTTPException(status_code=400, detail="mode 必须是 instrumental / vocals / stems")
        job_id = "sep_" + uuid.uuid4().hex[:12]
        target = config.uploads_dir / f"{job_id}{suffix}"
        size = 0
        try:
            with target.open("wb") as handle:
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > config.max_upload_mb * 1024 * 1024:
                        raise HTTPException(status_code=413, detail="音频文件过大")
                    handle.write(chunk)
        except HTTPException:
            target.unlink(missing_ok=True)
            raise
        except OSError as exc:
            target.unlink(missing_ok=True)
            raise HTTPException(status_code=500, detail=f"保存音频失败：{exc}") from exc
        finally:
            await file.close()
        if size == 0:
            target.unlink(missing_ok=True)
            raise HTTPException(status_code=400, detail="音频文件为空")
        record = store.create(
            id=job_id,
            filename=filename,
            audio_path=str(target),
            audio_size=size,
            model_id=model_id,
            mode=mode,
            options={},
        )
        jobs.submit(
            job_id,
            audio_path=target,
            model_id=model_id,
            mode=mode,
        )
        return _payload(config, record)

    @router.get("/{job_id}")
    async def get(job_id: str) -> dict[str, Any]:
        record = store.get(job_id)
        if record is None:
            raise HTTPException(status_code=404, detail="分离任务不存在")
        return _payload(config, record)

    @router.post("/{job_id}/cancel")
    async def cancel(job_id: str) -> dict[str, Any]:
        record = store.get(job_id)
        if record is None:
            raise HTTPException(status_code=404, detail="分离任务不存在")
        jobs.cancel(job_id)
        return _payload(config, store.get(job_id) or record)

    @router.delete("/{job_id}")
    async def delete(job_id: str) -> dict[str, Any]:
        record = store.get(job_id)
        if record is None:
            raise HTTPException(status_code=404, detail="分离任务不存在")
        if record["status"] in {"queued", "running", "cancelling"}:
            raise HTTPException(status_code=409, detail="任务仍在进行，请先取消")
        record = store.delete(job_id)
        if record is None:
            raise HTTPException(status_code=404, detail="分离任务不存在")
        for key in ("audio_path",):
            path = Path(record.get(key) or "")
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        for item in record.get("outputs") or []:
            try:
                Path(item.get("path") or "").unlink(missing_ok=True)
            except OSError:
                pass
        return {"ok": True}

    @router.get("/files/{file_path:path}")
    async def audio_file(file_path: str) -> FileResponse:
        candidate = (config.separation_outputs_dir / file_path).resolve()
        root = config.separation_outputs_dir.resolve()
        if root not in candidate.parents or not candidate.name.lower().endswith(
            (".wav", ".mp3", ".flac", ".ogg", ".m4a")
        ):
            raise HTTPException(status_code=400, detail="非法文件名")
        if not candidate.is_file():
            raise HTTPException(status_code=404, detail="分轨文件不存在")
        return FileResponse(candidate)

    return router
