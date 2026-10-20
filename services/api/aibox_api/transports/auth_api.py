"""Built-in login, session and RBAC endpoints."""

from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..auth import bearer_token
from ..auth_store import ROLES, AuthStore
from ..config import AppConfig

PUBLIC_API = {
    "/api/auth/status",
    "/api/auth/login",
    "/api/auth/bootstrap",
    "/api/health",
    "/api/protocol",
}


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class BootstrapRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=8, max_length=256)


class UserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=8, max_length=256)
    role: str = "viewer"


class UserUpdate(BaseModel):
    role: str | None = None
    active: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=256)


def _token(request: Request) -> str | None:
    return bearer_token(request.headers.get("authorization"))


def current_user(config: AppConfig, store: AuthStore, request: Request) -> dict[str, Any] | None:
    if not config.auth_enabled:
        return None
    if config.auth_mode == "external":
        username = request.headers.get(config.auth_external_header)
        if not username:
            return None
        user = store.get_by_username(username)
        if user is None:
            roles = [
                item.strip()
                for item in request.headers.get(
                    config.auth_external_roles_header, "viewer"
                ).split(",")
                if item.strip()
            ]
            role = next((item for item in roles if item in ROLES), "viewer")
            user = store.create_user(username, None, role=role, external_subject=username)
        return user
    return store.resolve_session(_token(request))


def require_access(
    config: AppConfig,
    store: AuthStore,
    request: Request,
    path: str,
) -> dict[str, Any] | None:
    if not config.auth_enabled:
        return None
    if path in PUBLIC_API or not path.startswith(("/api/", "/v1/")):
        return None
    if path.startswith("/v1/"):
        # OpenAI-compatible surface uses AIBOX_API_TOKEN, not WebUI sessions.
        return None
    if path.startswith("/api/cluster/nodes") and config.cluster_token:
        if _token(request) == config.cluster_token:
            return None
    user = current_user(config, store, request)
    if not user:
        raise HTTPException(status_code=401, detail="需要登录。")
    if not user.get("active"):
        raise HTTPException(status_code=403, detail="账户已停用。")
    method = request.method.upper()
    role = str(user.get("role") or "viewer")
    required = "viewer" if method in {"GET", "HEAD", "OPTIONS"} else "operator"
    if path.startswith("/api/auth/users") or path.startswith("/api/settings"):
        required = "admin" if method not in {"GET", "HEAD"} else "viewer"
    if path.endswith("/drain") or path.endswith("/cancel"):
        required = "operator"
    levels = {"viewer": 1, "operator": 2, "admin": 3}
    if levels.get(role, 0) < levels[required]:
        raise HTTPException(status_code=403, detail="权限不足。")
    request.state.auth_user = user
    return user


def create_auth_router(config: AppConfig, store: AuthStore) -> APIRouter:
    router = APIRouter(prefix="/api/auth", tags=["auth"])

    @router.get("/status")
    def status(request: Request) -> dict[str, Any]:
        user = current_user(config, store, request)
        return {
            "enabled": config.auth_enabled,
            "mode": config.auth_mode,
            "needs_setup": config.auth_enabled
            and config.auth_mode == "builtin"
            and store.count_users() == 0,
            "user": user,
        }

    @router.post("/bootstrap")
    def bootstrap(payload: BootstrapRequest) -> dict[str, Any]:
        if not config.auth_enabled:
            raise HTTPException(status_code=409, detail="账户系统未启用。")
        if config.auth_mode != "builtin":
            raise HTTPException(status_code=409, detail="外部登录模式下不能创建本地账户。")
        if store.count_users() > 0:
            raise HTTPException(status_code=409, detail="管理员已初始化。")
        user = store.create_user(payload.username, payload.password, role="admin")
        token = store.create_session(user["id"])
        return {"token": token, "user": user}

    @router.post("/login")
    def login(payload: LoginRequest) -> dict[str, Any]:
        if not config.auth_enabled:
            raise HTTPException(status_code=409, detail="账户系统未启用。")
        if config.auth_mode != "builtin":
            raise HTTPException(status_code=409, detail="请使用外部登录。")
        user = store.authenticate(payload.username, payload.password)
        if not user:
            raise HTTPException(status_code=401, detail="用户名或密码错误。")
        token = store.create_session(user["id"])
        return {"token": token, "user": user}

    @router.post("/logout")
    def logout(request: Request) -> dict[str, Any]:
        store.revoke_session(_token(request))
        return {"ok": True}

    @router.get("/me")
    def me(request: Request) -> dict[str, Any]:
        user = current_user(config, store, request)
        if not user:
            raise HTTPException(status_code=401, detail="需要登录。")
        return {"user": user}

    @router.get("/users")
    def users(request: Request) -> dict[str, Any]:
        if not config.auth_enabled:
            raise HTTPException(status_code=409, detail="账户系统未启用。")
        require_access(config, store, request, "/api/auth/users")
        return {"users": store.list_users()}

    @router.post("/users", status_code=201)
    def create_user(payload: UserCreate, request: Request) -> dict[str, Any]:
        if not config.auth_enabled:
            raise HTTPException(status_code=409, detail="账户系统未启用。")
        require_access(config, store, request, "/api/auth/users")
        if payload.role not in ROLES:
            raise HTTPException(status_code=400, detail="角色非法。")
        try:
            return store.create_user(payload.username, payload.password, role=payload.role)
        except (ValueError, sqlite3.IntegrityError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.patch("/users/{user_id}")
    def update_user(
        user_id: str, payload: UserUpdate, request: Request
    ) -> dict[str, Any]:
        if not config.auth_enabled:
            raise HTTPException(status_code=409, detail="账户系统未启用。")
        require_access(config, store, request, "/api/auth/users")
        try:
            return store.update_user(
                user_id,
                role=payload.role,
                active=payload.active,
                password=payload.password,
            )
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.delete("/users/{user_id}")
    def delete_user(user_id: str, request: Request) -> dict[str, Any]:
        if not config.auth_enabled:
            raise HTTPException(status_code=409, detail="账户系统未启用。")
        actor = require_access(config, store, request, "/api/auth/users")
        if actor and actor["id"] == user_id:
            raise HTTPException(status_code=400, detail="不能删除当前登录账户。")
        try:
            store.delete_user(user_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"ok": True}

    return router
