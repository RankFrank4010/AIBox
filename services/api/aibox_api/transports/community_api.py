"""Community adapter management API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..community import AdapterError, CommunityRegistry
from ..config import AppConfig


class ImportAdapterRequest(BaseModel):
    manifest: str | dict[str, Any]


class ToggleAdapterRequest(BaseModel):
    enabled: bool


def create_community_router(
    config: AppConfig, registry: CommunityRegistry
) -> APIRouter:
    router = APIRouter(prefix="/api/community", tags=["community"])

    @router.get("")
    async def list_community() -> dict[str, Any]:
        return registry.list_public()

    @router.get("/templates/{template_id}")
    async def template_manifest(template_id: str) -> dict[str, Any]:
        try:
            return registry.template_manifest(template_id)
        except AdapterError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/adapters", status_code=201)
    async def import_adapter(payload: ImportAdapterRequest) -> dict[str, Any]:
        try:
            adapter = registry.import_manifest(payload.manifest)
            return registry.adapters[adapter.id].to_dict()
        except AdapterError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.patch("/adapters/{adapter_id}")
    async def toggle_adapter(
        adapter_id: str, payload: ToggleAdapterRequest
    ) -> dict[str, Any]:
        try:
            adapter = registry.set_enabled(adapter_id, payload.enabled)
            return adapter.to_dict()
        except AdapterError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.delete("/adapters/{adapter_id}")
    async def delete_adapter(adapter_id: str) -> dict[str, Any]:
        try:
            deleted = registry.delete(adapter_id)
        except AdapterError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not deleted:
            raise HTTPException(status_code=404, detail="适配器不存在")
        return {"ok": True}

    @router.post("/reload")
    async def reload_community() -> dict[str, Any]:
        registry.reload()
        return registry.list_public()

    return router
