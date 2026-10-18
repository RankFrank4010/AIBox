"""Chat UI API and OpenAI-compatible chat completions."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict

from ..config import AppConfig
from ..external import ExternalServiceError
from ..llm import LLMEngine, LLMUnavailable
from .openai_api import _require_token


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    model: str | None = None
    messages: list[dict[str, Any]]
    stream: bool = False
    temperature: float | None = None
    max_tokens: int | None = None
    system_prompt: str | None = None


def _sse(chunks: Iterator[dict[str, Any]]) -> Iterator[str]:
    try:
        for chunk in chunks:
            yield "data: " + json.dumps(chunk, ensure_ascii=False) + "\n\n"
    except LLMUnavailable as exc:
        payload = {"error": {"message": str(exc), "type": "aibox_error"}}
        yield "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"
    except Exception as exc:  # noqa: BLE001
        payload = {
            "error": {
                "message": f"LLM 流式响应失败：{exc}",
                "type": "aibox_error",
            }
        }
        yield "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"
    finally:
        yield "data: [DONE]\n\n"


def _validate(payload: ChatRequest) -> None:
    if not payload.messages:
        raise HTTPException(status_code=400, detail="messages 不能为空")
    for item in payload.messages:
        if not isinstance(item, dict) or not item.get("role"):
            raise HTTPException(status_code=400, detail="messages 格式不正确")


def create_llm_router(config: AppConfig, engine: LLMEngine) -> APIRouter:
    router = APIRouter(prefix="/api/llm", tags=["llm"])

    @router.get("/status")
    async def status() -> dict[str, Any]:
        return engine.status()

    @router.post("/chat")
    async def chat(payload: ChatRequest):
        _validate(payload)
        system_prompt = payload.system_prompt
        if system_prompt is None:
            system_prompt = str(config.settings().get("llm_system_prompt") or "")
        try:
            result = engine.chat(
                messages=payload.messages,
                model_id=payload.model,
                stream=payload.stream,
                temperature=payload.temperature,
                max_tokens=payload.max_tokens,
                system_prompt=system_prompt,
            )
        except LLMUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        if payload.stream:
            return StreamingResponse(
                _sse(result),  # type: ignore[arg-type]
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                },
            )
        return result

    @router.post("/unload")
    async def unload() -> dict[str, Any]:
        engine.unload()
        return {"ok": True}

    return router


def create_openai_chat_router(config: AppConfig, engine: LLMEngine) -> APIRouter:
    router = APIRouter(prefix="/v1", tags=["openai-chat"])
    auth = _require_token(config)

    @router.post("/chat/completions", dependencies=[Depends(auth)])
    async def chat_completions(payload: ChatRequest):
        _validate(payload)
        try:
            result = engine.chat(
                messages=payload.messages,
                model_id=payload.model,
                stream=payload.stream,
                temperature=payload.temperature,
                max_tokens=payload.max_tokens,
                system_prompt=None,
            )
        except LLMUnavailable as exc:
            raise ExternalServiceError(
                str(exc),
                status_code=503,
                code="model_unavailable",
                param="model",
            ) from exc
        if payload.stream:
            return StreamingResponse(
                _sse(result),  # type: ignore[arg-type]
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                },
            )
        return result

    return router
