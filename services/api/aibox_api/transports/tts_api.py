"""TTS HTTP APIs: local endpoint, voice profiles, and OpenAI compatibility."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ..auth import token_matches
from ..config import AppConfig
from ..external import ExternalServiceError
from ..tts import SUPPORTED_FORMATS, TtsEngine, TtsUnavailable
from ..voices import VoiceError


class SpeechInput(BaseModel):
    input: str = Field(default="", description="Text to synthesize")
    text: str | None = None
    model: str = "tts-1"
    voice: str = "default"
    language: str = "auto"
    speed: float = 1.0
    response_format: str = "mp3"
    instructions: str | None = None


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


def _text_of(payload: SpeechInput) -> str:
    return (payload.text or payload.input or "").strip()


def _speak(engine: TtsEngine, payload: SpeechInput, default_format: str) -> Response:
    text = _text_of(payload)
    if not text:
        raise ExternalServiceError(
            "input must not be empty.",
            status_code=400,
            code="empty_input",
            param="input",
        )
    fmt = (payload.response_format or default_format).lower()
    if fmt not in SUPPORTED_FORMATS:
        raise ExternalServiceError(
            f"response_format must be one of {', '.join(sorted(SUPPORTED_FORMATS))}.",
            status_code=400,
            code="unsupported_format",
            param="response_format",
        )
    try:
        result = engine.synthesize(
            text=text,
            model_id=payload.model,
            voice=payload.voice,
            language=payload.language,
            speed=payload.speed,
            response_format=fmt,
        )
    except TtsUnavailable as exc:
        raise ExternalServiceError(
            str(exc),
            status_code=503
            if "未安装" in str(exc) or "运行时" in str(exc) or "参考音频" in str(exc)
            else 400,
            code="tts_unavailable",
            error_type="invalid_request_error",
        ) from exc
    path: Path = result["path"]
    try:
        content = path.read_bytes()
    finally:
        path.unlink(missing_ok=True)
    headers = {
        "X-AIBox-Model": payload.model,
        "X-AIBox-Format": result["format"],
    }
    if result.get("warning"):
        headers["X-AIBox-Warning"] = "demo-engine"
    return Response(content=content, media_type=result["media_type"], headers=headers)


def create_tts_router(config: AppConfig, engine: TtsEngine) -> APIRouter:
    router = APIRouter(prefix="/api/tts", tags=["tts"])

    @router.get("/status")
    async def status() -> dict[str, Any]:
        return engine.status()

    @router.get("/voices")
    async def voices() -> dict[str, Any]:
        return {"voices": engine.voices.list()}

    @router.post("/voices", status_code=201)
    async def create_voice(
        file: UploadFile = File(...),
        name: str = Form("自定义音色"),
        language: str = Form("auto"),
    ) -> dict[str, Any]:
        try:
            content = await file.read()
            return engine.voices.create(
                name=name,
                filename=file.filename or "voice.wav",
                content=content,
                language=language,
            )
        except VoiceError as exc:
            raise ExternalServiceError(
                str(exc), status_code=400, code="invalid_voice", param="file"
            ) from exc
        finally:
            await file.close()

    @router.delete("/voices/{voice_id}")
    async def delete_voice(voice_id: str) -> dict[str, Any]:
        if not engine.voices.delete(voice_id):
            raise ExternalServiceError(
                "Voice not found.", status_code=404, code="voice_not_found"
            )
        return {"ok": True}

    @router.post("/synthesize")
    async def synthesize(payload: SpeechInput) -> Response:
        return _speak(engine, payload, "wav")

    return router


def create_openai_tts_router(config: AppConfig, engine: TtsEngine) -> APIRouter:
    router = APIRouter(prefix="/v1", tags=["openai-tts"])
    auth = _require_token(config)

    @router.post("/audio/speech", dependencies=[Depends(auth)])
    async def speech(payload: SpeechInput) -> Response:
        response = _speak(engine, payload, "mp3")
        # OpenAI clients usually do not need a filename header.
        response.headers.setdefault(
            "Content-Disposition",
            f'inline; filename="aibox-{uuid.uuid4().hex[:8]}.{payload.response_format or "mp3"}"',
        )
        return response

    @router.get("/audio/voices", dependencies=[Depends(auth)])
    async def list_voices() -> dict[str, Any]:
        return {
            "voices": engine.voices.list(),
            "formats": sorted(SUPPORTED_FORMATS),
        }

    return router
