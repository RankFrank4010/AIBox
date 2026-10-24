"""Watermark removal API: image and video."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from ..watermark import WatermarkError, WatermarkService
from ..watermark_store import WatermarkJobs, WatermarkStore

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".mkv", ".avi"}


def _suffix(filename: str | None, allowed: set[str], fallback: str) -> str:
    suffix = Path(filename or "").suffix.lower()
    return suffix if suffix in allowed else fallback


def _regions(raw: str) -> list[dict[str, Any]]:
    try:
        value = json.loads(raw or "[]")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="regions 不是合法 JSON。") from exc
    if not isinstance(value, list):
        raise HTTPException(status_code=400, detail="regions 必须是数组。")
    return [item for item in value if isinstance(item, dict)][:64]


def create_watermark_router(
    service: WatermarkService,
    store: WatermarkStore,
    jobs: WatermarkJobs,
) -> APIRouter:
    router = APIRouter(prefix="/api/watermarks", tags=["watermarks"])

    @router.get("/status")
    def status() -> dict[str, Any]:
        return service.status()

    @router.get("")
    def history(limit: int = 50) -> dict[str, Any]:
        return {"records": store.list(limit)}

    @router.post("/images")
    async def remove_image(
        file: UploadFile = File(...),
        mask: UploadFile | None = File(default=None),
        provider: str = Form("auto"),
        regions: str = Form("[]"),
    ) -> dict[str, Any]:
        suffix = _suffix(file.filename, IMAGE_EXTENSIONS, ".png")
        job_id = "wm_" + uuid.uuid4().hex[:14]
        work_dir = service.config.watermarks_dir / job_id
        work_dir.mkdir(parents=True, exist_ok=True)
        input_path = work_dir / f"input{suffix}"
        output_path = work_dir / "output.png"
        mask_path = work_dir / "mask.png" if mask else None
        input_path.write_bytes(await file.read())
        if mask and mask_path:
            mask_path.write_bytes(await mask.read())
        record = store.create(
            kind="image",
            provider=provider,
            filename=file.filename or f"image{suffix}",
            input_path=input_path,
            output_path=output_path,
            mask_path=mask_path,
            regions=_regions(regions),
        )
        try:
            result = service.remove_image(
                input_path=input_path,
                output_path=output_path,
                mask_path=mask_path,
                regions=_regions(regions),
                provider=provider,
            )
        except WatermarkError as exc:
            store.update(record["id"], status="failed", error=str(exc))
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        store.update(record["id"], status="completed", progress=1)
        record = store.get(record["id"]) or record
        record["result"] = result
        return record

    @router.post("/videos", status_code=202)
    async def remove_video(
        file: UploadFile = File(...),
        mask: UploadFile | None = File(default=None),
        provider: str = Form("auto"),
        regions: str = Form("[]"),
    ) -> dict[str, Any]:
        suffix = _suffix(file.filename, VIDEO_EXTENSIONS, ".mp4")
        job_id = "wm_" + uuid.uuid4().hex[:14]
        work_dir = service.config.watermarks_dir / job_id
        work_dir.mkdir(parents=True, exist_ok=True)
        input_path = work_dir / f"input{suffix}"
        output_path = work_dir / "output.mp4"
        mask_path = work_dir / "mask.png" if mask else None
        input_path.write_bytes(await file.read())
        if mask and mask_path:
            mask_path.write_bytes(await mask.read())
        return jobs.submit_video(
            provider=provider,
            filename=file.filename or f"video{suffix}",
            input_path=input_path,
            output_path=output_path,
            mask_path=mask_path,
            regions=_regions(regions),
        )

    @router.get("/{job_id}")
    def record(job_id: str) -> dict[str, Any]:
        item = store.get(job_id)
        if not item:
            raise HTTPException(status_code=404, detail="去水印任务不存在。")
        return item

    @router.get("/{job_id}/file")
    def output(job_id: str) -> FileResponse:
        row = store.raw(job_id)
        if not row or row["status"] != "completed":
            raise HTTPException(status_code=404, detail="结果尚未生成。")
        path = Path(row["output_path"])
        if not path.is_file():
            raise HTTPException(status_code=404, detail="结果文件不存在。")
        media = "video/mp4" if row["kind"] == "video" else "image/png"
        return FileResponse(path, media_type=media, filename=f"{job_id}{path.suffix}")

    @router.delete("/{job_id}")
    def delete(job_id: str) -> dict[str, Any]:
        if not store.delete(job_id):
            raise HTTPException(status_code=404, detail="去水印任务不存在。")
        return {"ok": True}

    return router
