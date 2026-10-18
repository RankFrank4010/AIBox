"""Image generation HTTP APIs, including OpenAI-compatible Images."""

from __future__ import annotations

import base64
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..auth import token_matches
from ..config import AppConfig
from ..external import ExternalServiceError
from ..image import ImageEngine, ImageUnavailable
from ..image_jobs import ImageJobs
from ..image_store import ImageStore


class ImageRequest(BaseModel):
    prompt: str = ""
    negative_prompt: str = ""
    model: str | None = None
    provider: str = "auto"
    width: int | None = None
    height: int | None = None
    size: str | None = "1024x1024"
    steps: int | None = None
    guidance_scale: float | None = None
    guidance: float | None = None
    seed: int | None = None
    batch: int = 1
    n: int | None = None
    workflow: dict[str, Any] | None = None
    checkpoint: str | None = None
    response_format: str = "url"


def _dimensions(payload: ImageRequest) -> tuple[int, int]:
    width = payload.width
    height = payload.height
    if (width is None or height is None) and payload.size:
        try:
            size_w, size_h = payload.size.lower().split("x", 1)
            width = int(size_w)
            height = int(size_h)
        except (TypeError, ValueError):
            width, height = 1024, 1024
    return int(width or 1024), int(height or 1024)


def _settings_defaults(config: AppConfig, payload: ImageRequest) -> tuple[int, int, int, float, int]:
    settings = config.settings()
    width, height = _dimensions(payload)
    steps = int(payload.steps or settings.get("image_steps") or 28)
    guidance = float(
        payload.guidance_scale
        if payload.guidance_scale is not None
        else payload.guidance
        if payload.guidance is not None
        else settings.get("image_guidance")
        or 3.5
    )
    batch = int(payload.n or payload.batch or 1)
    return width, height, steps, guidance, batch


def _payload(config: AppConfig, engine: ImageEngine, record: dict[str, Any]) -> dict[str, Any]:
    image_urls = []
    for path in record.get("image_paths") or []:
        file_path = Path(path)
        try:
            relative = file_path.relative_to(config.image_outputs_dir).as_posix()
        except ValueError:
            relative = file_path.name
        image_urls.append(f"/api/images/files/{relative}")
    base = config.public_base_url or ""
    public = {
        key: value
        for key, value in record.items()
        if key not in {"options", "image_paths"}
    }
    return {
        **public,
        "image_urls": image_urls,
        "image_absolute_urls": [f"{base}{url}" if base else url for url in image_urls],
        "preview_url": image_urls[0] if image_urls else None,
        "engine": engine.status(),
    }


def _require_token(config: AppConfig):
    def dependency(request: Request) -> None:
        if not token_matches(config, request.headers.get("authorization")):
            raise ExternalServiceError(
                "Incorrect API key provided.",
                status_code=401,
                code="invalid_api_key",
                error_type="invalid_request_error",
            )

    return dependency


def _create_job(
    *,
    config: AppConfig,
    store: ImageStore,
    jobs: ImageJobs,
    engine: ImageEngine,
    payload: ImageRequest,
) -> dict[str, Any]:
    prompt = payload.prompt.strip()
    if not prompt:
        raise ImageUnavailable("提示词不能为空。")
    if len(prompt) > 4000:
        raise ImageUnavailable("提示词不能超过 4000 字符。")
    width, height, steps, guidance, batch = _settings_defaults(config, payload)
    if batch < 1 or batch > 8:
        raise ImageUnavailable("单次图片数量必须在 1-8 之间。")
    if width < 256 or width > 2048 or height < 256 or height > 2048:
        raise ImageUnavailable("尺寸必须在 256-2048 之间。")
    model_id = payload.model or str(
        config.settings().get("default_image_model") or "sd15"
    )
    job_id = "img_" + uuid.uuid4().hex[:12]
    record = store.create(
        id=job_id,
        prompt=prompt,
        negative_prompt=payload.negative_prompt.strip(),
        model_id=model_id,
        provider=payload.provider,
        width=width,
        height=height,
        steps=steps,
        guidance=guidance,
        seed=payload.seed,
        batch=batch,
        options={
            "workflow": payload.workflow,
            "checkpoint": payload.checkpoint,
            "response_format": payload.response_format,
        },
    )
    jobs.submit(
        job_id,
        {
            **record,
            "prompt": prompt,
            "provider": payload.provider,
            "model_id": model_id,
            "width": width,
            "height": height,
            "steps": steps,
            "guidance": guidance,
            "seed": payload.seed,
            "batch": batch,
            "workflow": payload.workflow,
            "checkpoint": payload.checkpoint,
        },
    )
    return record


def create_images_router(
    config: AppConfig,
    store: ImageStore,
    jobs: ImageJobs,
    engine: ImageEngine,
) -> APIRouter:
    router = APIRouter(prefix="/api/images", tags=["images"])

    @router.get("/status")
    async def status() -> dict[str, Any]:
        return engine.status()

    @router.get("/generations")
    async def generations(limit: int = 50, offset: int = 0) -> dict[str, Any]:
        records = store.list(limit=max(1, min(200, limit)), offset=max(0, offset))
        return {"items": [_payload(config, engine, record) for record in records]}

    @router.post("/generations", status_code=202)
    async def generate(payload: ImageRequest) -> dict[str, Any]:
        try:
            record = _create_job(
                config=config, store=store, jobs=jobs, engine=engine, payload=payload
            )
        except ImageUnavailable as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _payload(config, engine, record)

    @router.get("/generations/{job_id}")
    async def generation(job_id: str) -> dict[str, Any]:
        record = store.get(job_id)
        if record is None:
            raise HTTPException(status_code=404, detail="图像任务不存在")
        return _payload(config, engine, record)

    @router.post("/generations/{job_id}/cancel")
    async def cancel(job_id: str) -> dict[str, Any]:
        record = store.get(job_id)
        if record is None:
            raise HTTPException(status_code=404, detail="图像任务不存在")
        jobs.cancel(job_id)
        return _payload(config, engine, store.get(job_id) or record)

    @router.delete("/generations/{job_id}")
    async def delete(job_id: str) -> dict[str, Any]:
        current = store.get(job_id)
        if current is None:
            raise HTTPException(status_code=404, detail="图像任务不存在")
        if current["status"] in {"queued", "running", "cancelling"}:
            raise HTTPException(status_code=409, detail="任务仍在进行，请先取消")
        record = store.delete(job_id)
        if record is None:
            raise HTTPException(status_code=404, detail="图像任务不存在")
        for path in record.get("image_paths") or []:
            try:
                Path(path).unlink(missing_ok=True)
            except OSError:
                pass
        return {"ok": True}

    @router.get("/files/{file_path:path}")
    async def file(file_path: str) -> FileResponse:
        candidate = (config.image_outputs_dir / file_path).resolve()
        root = config.image_outputs_dir.resolve()
        if root not in candidate.parents or not candidate.name.lower().endswith(
            (".png", ".jpg", ".jpeg", ".webp")
        ):
            raise HTTPException(status_code=400, detail="非法文件名")
        if not candidate.is_file():
            raise HTTPException(status_code=404, detail="图像不存在")
        return FileResponse(candidate)

    return router


def create_openai_images_router(
    config: AppConfig,
    store: ImageStore,
    jobs: ImageJobs,
    engine: ImageEngine,
) -> APIRouter:
    router = APIRouter(prefix="/v1", tags=["openai-images"])
    auth = _require_token(config)

    @router.post("/images/generations", dependencies=[Depends(auth)])
    def openai_generate(payload: ImageRequest) -> dict[str, Any]:
        try:
            record = _create_job(
                config=config, store=store, jobs=jobs, engine=engine, payload=payload
            )
        except ImageUnavailable as exc:
            raise ExternalServiceError(
                str(exc),
                status_code=400,
                code="image_generation_unavailable",
                param="prompt",
            ) from exc
        deadline = time.monotonic() + 900
        while time.monotonic() < deadline:
            current = store.get(record["id"]) or record
            if current["status"] in {"completed", "failed", "cancelled"}:
                break
            time.sleep(0.35)
        current = store.get(record["id"]) or record
        if current["status"] == "failed":
            raise ExternalServiceError(
                current.get("error") or "图像生成失败",
                status_code=502,
                code="image_generation_failed",
            )
        if current["status"] != "completed":
            raise ExternalServiceError(
                "图像生成超时",
                status_code=504,
                code="image_generation_timeout",
            )
        response_format = payload.response_format or "url"
        data: list[dict[str, Any]] = []
        for path in current.get("image_paths") or []:
            file_path = Path(path)
            if response_format == "b64_json":
                data.append(
                    {
                        "b64_json": base64.b64encode(file_path.read_bytes()).decode("ascii"),
                        "revised_prompt": payload.prompt,
                    }
                )
            else:
                base = config.public_base_url or f"http://127.0.0.1:{config.port}"
                try:
                    relative = file_path.relative_to(config.image_outputs_dir).as_posix()
                except ValueError:
                    relative = file_path.name
                data.append(
                    {
                        "url": f"{base}/api/images/files/{relative}",
                        "revised_prompt": payload.prompt,
                    }
                )
        if not data:
            raise ExternalServiceError(
                "图像生成没有返回结果",
                status_code=502,
                code="image_generation_empty",
            )
        return {"created": int(time.time()), "data": data}

    return router
