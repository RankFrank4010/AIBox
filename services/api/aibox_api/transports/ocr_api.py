"""OCR REST API."""

from __future__ import annotations

import mimetypes
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from ..config import AppConfig
from ..ocr import IMAGE_SUFFIXES, OcrError, OcrService
from ..ocr_store import OcrStore


def create_ocr_router(
    config: AppConfig, service: OcrService, store: OcrStore
) -> APIRouter:
    router = APIRouter(prefix="/api/ocr", tags=["ocr"])

    @router.get("/status")
    def status() -> dict[str, Any]:
        payload = service.status()
        payload["history_count"] = len(store.list(200))
        return payload

    @router.get("")
    def history(limit: int = 50) -> dict[str, Any]:
        return {"records": store.list(limit)}

    @router.post("")
    async def recognize(
        file: UploadFile = File(...),
        provider: str = Form("auto"),
        model: str = Form(""),
        language: str = Form("auto"),
    ) -> dict[str, Any]:
        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in IMAGE_SUFFIXES:
            raise HTTPException(status_code=400, detail="仅支持 PNG / JPEG / WebP / BMP / TIFF 图片。")
        data = await file.read()
        if not data:
            raise HTTPException(status_code=400, detail="图片文件为空。")
        if len(data) > 20 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="图片不能超过 20 MB。")
        config.ocr_dir.mkdir(parents=True, exist_ok=True)
        image_path = config.ocr_dir / f"{uuid.uuid4().hex}{suffix}"
        image_path.write_bytes(data)
        try:
            result = service.recognize(
                image_path=image_path,
                provider=provider,
                model=model or None,
                language=language,
            )
        except OcrError as exc:
            image_path.unlink(missing_ok=True)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        record = store.create(
            {
                **result,
                "image_path": str(image_path),
                "filename": file.filename or image_path.name,
            }
        )
        return {"record": record}

    @router.get("/images/{record_id}")
    def image(record_id: str) -> FileResponse:
        record = store.get_raw(record_id)
        if not record:
            raise HTTPException(status_code=404, detail="OCR 记录不存在。")
        path = Path(record["image_path"])
        try:
            path.resolve().relative_to(config.ocr_dir.resolve())
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="图片路径无效。") from exc
        if not path.is_file():
            raise HTTPException(status_code=404, detail="图片文件不存在。")
        media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return FileResponse(path, media_type=media_type)

    @router.delete("/{record_id}")
    def delete(record_id: str) -> dict[str, bool]:
        record = store.get_raw(record_id)
        if not record:
            raise HTTPException(status_code=404, detail="OCR 记录不存在。")
        path = Path(record["image_path"])
        try:
            path.resolve().relative_to(config.ocr_dir.resolve())
            path.unlink(missing_ok=True)
        except (ValueError, OSError):
            pass
        if not store.delete(record_id):
            raise HTTPException(status_code=404, detail="OCR 记录不存在。")
        return {"deleted": True}

    return router
