"""Translation REST API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..translation import TranslationError, TranslationService
from ..translation_store import TranslationStore


class TranslationRequest(BaseModel):
    text: str = Field(min_length=1, max_length=20000)
    source: str = Field(default="auto")
    target: str = Field(default="zh")
    provider: str = Field(default="auto")
    model: str | None = None


def create_translation_router(
    service: TranslationService, store: TranslationStore
) -> APIRouter:
    router = APIRouter(prefix="/api/translations", tags=["translations"])

    @router.get("/status")
    def status() -> dict[str, Any]:
        payload = service.status()
        payload["history_count"] = len(store.list(200))
        return payload

    @router.get("")
    def history(limit: int = 50) -> dict[str, Any]:
        return {"translations": store.list(limit)}

    @router.post("")
    def translate(payload: TranslationRequest) -> dict[str, Any]:
        try:
            result = service.translate(
                text=payload.text,
                source=payload.source,
                target=payload.target,
                provider=payload.provider,
                model=payload.model,
            )
        except TranslationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        record = store.create(result)
        return {"translation": record}

    @router.delete("/{record_id}")
    def delete(record_id: str) -> dict[str, bool]:
        if not store.delete(record_id):
            raise HTTPException(status_code=404, detail="翻译记录不存在。")
        return {"deleted": True}

    return router
