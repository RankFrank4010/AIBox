"""Cluster registry and task dispatch API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..cluster import ClusterError, ClusterManager
from ..config import AppConfig


class NodeRegistration(BaseModel):
    id: str = Field(min_length=1, max_length=128)
    url: str
    capabilities: list[str] = Field(default_factory=list)
    labels: dict[str, Any] = Field(default_factory=dict)
    work_config: dict[str, Any] = Field(default_factory=dict)
    max_concurrency: int = Field(default=1, ge=1, le=64)
    version: str = "1.0"


class NodeConfigUpdate(BaseModel):
    work_config: dict[str, Any] = Field(default_factory=dict)


class ClusterTaskRequest(BaseModel):
    kind: str = Field(min_length=1, max_length=64)
    payload: dict[str, Any] = Field(default_factory=dict)
    timeout: float = Field(default=180, ge=1, le=3600)


def _require_token(config: AppConfig, request: Request) -> None:
    if not config.cluster_token:
        return
    supplied = request.headers.get("Authorization", "")
    if supplied != f"Bearer {config.cluster_token}":
        raise HTTPException(status_code=401, detail="集群 Token 无效。")


def create_cluster_router(
    config: AppConfig, manager: ClusterManager
) -> APIRouter:
    router = APIRouter(prefix="/api/cluster", tags=["cluster"])

    @router.get("/status")
    def status() -> dict[str, Any]:
        return manager.status()

    @router.get("/nodes")
    def nodes() -> dict[str, Any]:
        return {"nodes": manager.nodes()}

    @router.post("/nodes")
    def register(payload: NodeRegistration, request: Request) -> dict[str, Any]:
        _require_token(config, request)
        try:
            return manager.register(payload.model_dump())
        except ClusterError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/nodes/{node_id}/heartbeat")
    def heartbeat(node_id: str, request: Request) -> dict[str, Any]:
        _require_token(config, request)
        try:
            return manager.heartbeat(node_id)
        except ClusterError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.patch("/nodes/{node_id}/config")
    def update_config(node_id: str, payload: NodeConfigUpdate) -> dict[str, Any]:
        try:
            return manager.update_config(node_id, payload.work_config)
        except ClusterError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/nodes/{node_id}/drain")
    def drain(node_id: str, request: Request) -> dict[str, Any]:
        _require_token(config, request)
        try:
            return manager.drain(node_id)
        except ClusterError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/tasks")
    def tasks(limit: int = 50) -> dict[str, Any]:
        return {"tasks": manager.tasks(limit)}

    @router.post("/tasks")
    def dispatch(payload: ClusterTaskRequest) -> dict[str, Any]:
        if not config.cluster_enabled:
            raise HTTPException(status_code=409, detail="集群调度未启用。")
        try:
            return manager.dispatch(
                payload.kind,
                payload.payload,
                timeout=payload.timeout,
            )
        except ClusterError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @router.get("/tasks/{task_id}")
    def task(task_id: str) -> dict[str, Any]:
        record = manager.task(task_id)
        if not record:
            raise HTTPException(status_code=404, detail="集群任务不存在。")
        return record

    return router
