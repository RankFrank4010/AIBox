"""Video generation HTTP API."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..config import AppConfig
from ..video import VideoEngine
from ..video_jobs import VideoJobs
from ..video_store import VideoStore


class VideoRequest(BaseModel):
    prompt: str = ""
    model: str | None = None
    duration: int = 6
    resolution: str = "1080P"
    aspect: str = "16:9"
    seed: int | None = None
    workflow: dict[str, Any] | None = None


def _url_for(path: str | None, config: AppConfig) -> str | None:
    if not path:
        return None
    file_path = Path(path)
    try:
        relative = file_path.relative_to(config.video_outputs_dir).as_posix()
    except ValueError:
        relative = file_path.name
    return f"/api/videos/files/{relative}"


def _payload(config: AppConfig, record: dict[str, Any]) -> dict[str, Any]:
    public = {
        key: value
        for key, value in record.items()
        if key not in {"options", "video_path", "poster_path"}
    }
    return {
        **public,
        "video_url": _url_for(record.get("video_path"), config),
        "poster_url": _url_for(record.get("poster_path"), config),
    }


def create_video_router(
    config: AppConfig,
    store: VideoStore,
    jobs: VideoJobs,
    engine: VideoEngine,
) -> APIRouter:
    router = APIRouter(prefix="/api/videos", tags=["videos"])

    @router.get("/status")
    async def status() -> dict[str, Any]:
        return engine.status()

    @router.get("")
    async def list_jobs(limit: int = 30, offset: int = 0) -> dict[str, Any]:
        records = store.list(limit=max(1, min(100, limit)), offset=max(0, offset))
        return {"items": [_payload(config, record) for record in records]}

    @router.post("", status_code=202)
    async def create(payload: VideoRequest) -> dict[str, Any]:
        prompt = payload.prompt.strip()
        if not prompt:
            raise HTTPException(status_code=400, detail="提示词不能为空")
        if len(prompt) > 4000:
            raise HTTPException(status_code=400, detail="提示词不能超过 4000 字符")
        model = engine.resolve_model(payload.model)
        duration = max(1, min(model.max_duration, int(payload.duration)))
        resolution = payload.resolution if payload.resolution in model.resolutions else model.resolutions[-1]
        aspect = payload.aspect if payload.aspect in {"16:9", "9:16", "1:1", "4:5"} else "16:9"
        width, height = engine._dimensions(aspect, resolution)
        job_id = "vid_" + uuid.uuid4().hex[:12]
        record = store.create(
            id=job_id,
            prompt=prompt,
            model_id=model.id,
            provider=model.provider,
            duration=duration,
            resolution=resolution,
            aspect=aspect,
            width=width,
            height=height,
            seed=payload.seed,
            options={"workflow": payload.workflow},
        )
        jobs.submit(
            job_id,
            {
                "prompt": prompt,
                "model_id": model.id,
                "duration": duration,
                "resolution": resolution,
                "aspect": aspect,
                "seed": payload.seed,
                "workflow": payload.workflow,
            },
        )
        return _payload(config, record)

    @router.get("/{job_id}")
    async def get(job_id: str) -> dict[str, Any]:
        record = store.get(job_id)
        if record is None:
            raise HTTPException(status_code=404, detail="视频任务不存在")
        return _payload(config, record)

    @router.post("/{job_id}/cancel")
    async def cancel(job_id: str) -> dict[str, Any]:
        record = store.get(job_id)
        if record is None:
            raise HTTPException(status_code=404, detail="视频任务不存在")
        jobs.cancel(job_id)
        return _payload(config, store.get(job_id) or record)

    @router.delete("/{job_id}")
    async def delete(job_id: str) -> dict[str, Any]:
        record = store.get(job_id)
        if record is None:
            raise HTTPException(status_code=404, detail="视频任务不存在")
        if record["status"] in {"queued", "running", "cancelling"}:
            raise HTTPException(status_code=409, detail="任务仍在进行，请先取消")
        record = store.delete(job_id)
        if record is None:
            raise HTTPException(status_code=404, detail="视频任务不存在")
        for key in ("video_path", "poster_path"):
            try:
                Path(record.get(key) or "").unlink(missing_ok=True)
            except OSError:
                pass
        return {"ok": True}

    @router.get("/files/{file_path:path}")
    async def file(file_path: str) -> FileResponse:
        candidate = (config.video_outputs_dir / file_path).resolve()
        root = config.video_outputs_dir.resolve()
        if root not in candidate.parents or not candidate.name.lower().endswith(
            (".mp4", ".webm", ".mov", ".gif", ".jpg", ".jpeg", ".png")
        ):
            raise HTTPException(status_code=400, detail="非法文件名")
        if not candidate.is_file():
            raise HTTPException(status_code=404, detail="视频文件不存在")
        return FileResponse(candidate)

    return router
