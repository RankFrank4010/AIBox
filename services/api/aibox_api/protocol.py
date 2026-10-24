"""AIBOX Unified Protocol (AUP) manifest.

AUP is a thin contract over AIBox's native ``/api`` surface and its
OpenAI-compatible ``/v1`` surface. It deliberately keeps existing endpoint
shapes stable; SDKs normalize jobs, errors and streaming.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from .config import APP_NAME, APP_VERSION

PROTOCOL_NAME = "aibox-unified"
PROTOCOL_VERSION = "1.0"
PROTOCOL_HEADER = "X-AIBox-Protocol"

CAPABILITIES: dict[str, Any] = {
    "chat": True,
    "chat_streaming": True,
    "asr": True,
    "asr_streaming_websocket": True,
    "tts": True,
    "speech": True,
    "images": True,
    "videos": True,
    "separations": True,
    "training": True,
    "translation": True,
    "ocr": True,
    "watermark": True,
    "models": True,
    "community_adapters": True,
    "compute_priority": True,
    "multi_device": True,
    "openai_compatible": True,
    "cluster": True,
}

ENDPOINTS: list[dict[str, Any]] = [
    {
        "id": "protocol",
        "surface": "native",
        "method": "GET",
        "path": "/api/protocol",
        "description": "AUP discovery manifest.",
    },
    {
        "id": "health",
        "surface": "native",
        "method": "GET",
        "path": "/api/health",
        "description": "Liveness and engine summary.",
    },
    {
        "id": "models",
        "surface": "openai",
        "method": "GET",
        "path": "/v1/models",
        "description": "Model inventory in OpenAI list shape.",
    },
    {
        "id": "chat",
        "surface": "openai",
        "method": "POST",
        "path": "/v1/chat/completions",
        "description": "Chat completions; stream=true returns SSE.",
        "streaming": "text/event-stream",
    },
    {
        "id": "transcribe",
        "surface": "openai",
        "method": "POST",
        "path": "/v1/audio/transcriptions",
        "description": "Synchronous ASR, multipart audio upload.",
    },
    {
        "id": "speech",
        "surface": "openai",
        "method": "POST",
        "path": "/v1/audio/speech",
        "description": "Synchronous TTS, returns audio bytes.",
    },
    {
        "id": "transcriptions_job",
        "surface": "native",
        "method": "POST",
        "path": "/api/transcriptions",
        "description": "Asynchronous transcription job with progress.",
    },
    {
        "id": "images",
        "surface": "native",
        "method": "POST",
        "path": "/api/images/generations",
        "description": "Asynchronous image generation job.",
    },
    {
        "id": "videos",
        "surface": "native",
        "method": "POST",
        "path": "/api/videos",
        "description": "Asynchronous video generation job.",
    },
    {
        "id": "separations",
        "surface": "native",
        "method": "POST",
        "path": "/api/separations",
        "description": "Asynchronous vocal/background separation job.",
    },
    {
        "id": "training",
        "surface": "native",
        "method": "POST",
        "path": "/api/training/jobs",
        "description": "Asynchronous fine-tuning job.",
    },
    {
        "id": "translation",
        "surface": "native",
        "method": "POST",
        "path": "/api/translations",
        "description": "Synchronous text translation.",
    },
    {
        "id": "ocr",
        "surface": "native",
        "method": "POST",
        "path": "/api/ocr",
        "description": "Synchronous OCR, multipart image upload.",
    },
    {
        "id": "watermark_image",
        "surface": "native",
        "method": "POST",
        "path": "/api/watermarks/images",
        "description": "Image watermark removal with region masks.",
    },
    {
        "id": "watermark_video",
        "surface": "native",
        "method": "POST",
        "path": "/api/watermarks/videos",
        "description": "Frame-by-frame video watermark removal job.",
    },
    {
        "id": "websocket_asr",
        "surface": "native",
        "method": "WS",
        "path": "/ws/asr",
        "description": "Streaming microphone ASR.",
    },
    {
        "id": "cluster_status",
        "surface": "native",
        "method": "GET",
        "path": "/api/cluster/status",
        "description": "Multi-node registry, load and task counts.",
    },
    {
        "id": "cluster_task",
        "surface": "native",
        "method": "POST",
        "path": "/api/cluster/tasks",
        "description": "Dispatch a translation/OCR task to a worker node.",
    },
]

JOB_KINDS: dict[str, dict[str, str]] = {
    "transcription": {
        "create": "/api/transcriptions",
        "get": "/api/transcriptions/{id}",
        "cancel": "/api/transcriptions/{id}/cancel",
    },
    "image": {
        "create": "/api/images/generations",
        "get": "/api/images/generations/{id}",
        "cancel": "/api/images/generations/{id}/cancel",
    },
    "video": {
        "create": "/api/videos",
        "get": "/api/videos/{id}",
        "cancel": "/api/videos/{id}/cancel",
    },
    "separation": {
        "create": "/api/separations",
        "get": "/api/separations/{id}",
        "cancel": "/api/separations/{id}/cancel",
    },
    "training": {
        "create": "/api/training/jobs",
        "get": "/api/training/jobs/{id}",
        "cancel": "/api/training/jobs/{id}/cancel",
    },
}


def protocol_manifest() -> dict[str, Any]:
    return {
        "protocol": PROTOCOL_NAME,
        "version": PROTOCOL_VERSION,
        "compatibility": "1.x",
        "service": {
            "name": APP_NAME,
            "version": APP_VERSION,
            "media_type": "application/json",
            "encoding": "utf-8",
        },
        "auth": {
            "scheme": "bearer",
            "header": "Authorization",
            "env": "AIBOX_API_TOKEN",
            "required_for": ["/v1/*"],
            "optional_for": ["/api/*"],
        },
        "headers": {
            "protocol": PROTOCOL_HEADER,
            "request_id": "X-Request-ID",
            "idempotency": "Idempotency-Key",
            "client": "X-AIBox-Client",
        },
        "surfaces": {
            "native": {
                "base": "/api",
                "description": "Full AIBox capabilities; async jobs use the common job envelope.",
            },
            "openai": {
                "base": "/v1",
                "description": "OpenAI-compatible chat, ASR, TTS and model list.",
            },
        },
        "capabilities": CAPABILITIES,
        "job_kinds": JOB_KINDS,
        "job_states": {
            "queued": "accepted, waiting for a worker",
            "running": "active",
            "cancelling": "cancel requested",
            "completed": "terminal success",
            "failed": "terminal failure",
            "cancelled": "terminal cancellation",
        },
        "job_terminal_states": ["completed", "failed", "cancelled"],
        "streaming": {
            "chat": "text/event-stream",
            "event_data": "OpenAI-compatible JSON chunk or {error: {message, type}}",
            "terminator": "[DONE]",
            "websocket_asr": "/ws/asr",
        },
        "errors": {
            "native": {"shape": "{detail: string}", "source": "FastAPI HTTPException"},
            "openai": {"shape": "{error: {message, type, code, param}}"},
            "sdk": "normalize both shapes into AIBOXAPIError(status, code, message, details)",
        },
        "pagination": {"query": ["limit", "offset"], "default_limit": 50, "max_limit": 200},
        "idempotency": {
            "header": "Idempotency-Key",
            "scope": "job creation where supported",
        },
        "endpoints": ENDPOINTS,
    }


def create_protocol_router() -> APIRouter:
    router = APIRouter(tags=["protocol"])

    @router.get("/api/protocol")
    def protocol() -> JSONResponse:
        return JSONResponse(
            protocol_manifest(),
            headers={
                PROTOCOL_HEADER: PROTOCOL_VERSION,
                "Cache-Control": "public, max-age=300",
            },
        )

    return router
