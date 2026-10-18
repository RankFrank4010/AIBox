"""Credential helpers for external transport servers."""

from __future__ import annotations

import hmac

from .config import AppConfig


def bearer_token(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    if value.lower().startswith("bearer "):
        return value[7:].strip()
    return value


def token_matches(config: AppConfig, supplied: str | None) -> bool:
    if not config.api_token:
        return True
    candidate = bearer_token(supplied)
    if not candidate:
        return False
    return hmac.compare_digest(candidate, config.api_token)


def websocket_token(headers: dict[str, str], query_params: dict[str, str]) -> str | None:
    return bearer_token(headers.get("authorization")) or query_params.get("token")
