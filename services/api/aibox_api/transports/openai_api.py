"""OpenAI-compatible HTTP API for AIBox ASR."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from starlette.concurrency import run_in_threadpool

from ..auth import token_matches
from ..config import AppConfig
from ..external import AUDIO_EXTENSIONS, ExternalAsrGateway, ExternalServiceError
from ..store import render_export


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


async def _save_upload(config: AppConfig, file: UploadFile) -> Path:
    original = Path(file.filename or "audio.wav")
    suffix = original.suffix.lower()
    if suffix not in AUDIO_EXTENSIONS:
        suffix = ".wav"
    target = config.uploads_dir / f".incoming_{uuid.uuid4().hex}{suffix}"
    max_bytes = config.max_upload_mb * 1024 * 1024
    written = 0
    try:
        with target.open("wb") as handle:
            while True:
                chunk = await file.read(4 * 1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > max_bytes:
                    raise ExternalServiceError(
                        f"Audio exceeds the {config.max_upload_mb} MB limit.",
                        status_code=413,
                        code="audio_too_large",
                        param="file",
                    )
                handle.write(chunk)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    finally:
        await file.close()
    if written == 0:
        target.unlink(missing_ok=True)
        raise ExternalServiceError(
            "Audio file is empty.", status_code=400, code="empty_audio", param="file"
        )
    return target


def _verbose_payload(record: dict[str, Any], temperature: float) -> dict[str, Any]:
    segments = []
    all_words: list[dict[str, Any]] = []
    for segment in record.get("segments") or []:
        words = segment.get("words")
        item = {
            "id": segment.get("id", 0),
            "seek": 0,
            "start": segment.get("start", 0.0),
            "end": segment.get("end", 0.0),
            "text": segment.get("text", ""),
            "tokens": [],
            "temperature": temperature,
            "avg_logprob": -0.25,
            "compression_ratio": 1.0,
            "no_speech_prob": 0.0,
        }
        if words:
            converted = [
                {
                    "word": word.get("word", ""),
                    "start": word.get("start", 0.0),
                    "end": word.get("end", 0.0),
                }
                for word in words
            ]
            item["words"] = converted
            all_words.extend(converted)
        segments.append(item)
    payload = {
        "task": record.get("task", "transcribe"),
        "language": record.get("detected_language") or record.get("language") or "unknown",
        "duration": record.get("duration") or 0.0,
        "text": record.get("text") or "",
        "segments": segments,
    }
    if all_words:
        payload["words"] = all_words
    return payload


def create_openai_router(
    config: AppConfig,
    gateway: ExternalAsrGateway,
    extra_models: Callable[[], list[dict[str, Any]]] | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/v1", tags=["openai"])
    auth = _require_token(config)

    def all_models() -> list[dict[str, Any]]:
        items = list(gateway.model_list_for_openai())
        if extra_models:
            items.extend(extra_models())
        seen: set[str] = set()
        result = []
        for item in items:
            if item.get("id") in seen:
                continue
            seen.add(str(item.get("id")))
            result.append(item)
        return result

    @router.get("/models", dependencies=[Depends(auth)])
    async def list_models() -> dict[str, Any]:
        return {"object": "list", "data": all_models()}

    @router.get("/models/{model_id}", dependencies=[Depends(auth)])
    async def get_model(model_id: str) -> dict[str, Any]:
        for item in all_models():
            if item["id"] == model_id:
                return item
        raise ExternalServiceError(
            f"The model '{model_id}' does not exist.",
            status_code=404,
            code="model_not_found",
            param="model",
        )

    @router.post("/audio/transcriptions", dependencies=[Depends(auth)])
    async def create_transcription(
        file: UploadFile = File(...),
        model: str = Form("whisper-1"),
        language: str | None = Form(None),
        prompt: str | None = Form(None),
        response_format: str = Form("json"),
        temperature: float = Form(0.0),
        timestamp_granularities: list[str] | None = Form(
            default=None, alias="timestamp_granularities[]"
        ),
    ) -> Response:
        del prompt  # Reserved for a future initial-prompt passthrough.
        fmt = (response_format or "json").lower()
        if fmt not in {"json", "text", "srt", "verbose_json", "vtt"}:
            raise ExternalServiceError(
                "response_format must be one of json, text, srt, verbose_json, vtt.",
                status_code=400,
                code="unsupported_response_format",
                param="response_format",
            )
        word_timestamps = bool(
            timestamp_granularities and "word" in timestamp_granularities
        )
        temp = await _save_upload(config, file)
        options = {
            "language": language or "auto",
            "task": "transcribe",
            "word_timestamps": word_timestamps,
        }
        try:
            record = await run_in_threadpool(
                gateway.submit_and_wait,
                temp,
                filename=file.filename,
                model=model,
                options=options,
                transport="openai",
            )
        finally:
            temp.unlink(missing_ok=True)

        text = record.get("text") or ""
        headers = {
            "X-AIBox-Model": str(record.get("model_id") or ""),
            "X-AIBox-Device": str(record.get("device") or ""),
        }
        if fmt == "text":
            return PlainTextResponse(text, headers=headers)
        if fmt in {"srt", "vtt"}:
            content, media_type, _ = render_export(record, fmt)
            return Response(content=content, media_type=media_type, headers=headers)
        if fmt == "verbose_json":
            return JSONResponse(_verbose_payload(record, temperature), headers=headers)
        return JSONResponse({"text": text}, headers=headers)

    return router
