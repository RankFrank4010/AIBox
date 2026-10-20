"""Unit tests for the Python AUP SDK."""

from __future__ import annotations

import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aibox_sdk import AIBOXAPIError, AIBOXClient


def test_client_headers_and_translation():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["protocol"] = request.headers.get("X-AIBox-Protocol")
        seen["auth"] = request.headers.get("Authorization")
        return httpx.Response(
            200,
            json={"translation": {"text": "Hello", "translated": "你好"}},
        )

    client = AIBOXClient(
        "http://test",
        api_key="secret",
        transport=httpx.MockTransport(handler),
    )
    result = client.translate("Hello", target="zh")
    assert result["translated"] == "你好"
    assert seen["path"] == "/api/translations"
    assert seen["protocol"] == "1.0"
    assert seen["auth"] == "Bearer secret"
    client.close()


def test_client_normalizes_native_error():
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"detail": "服务未配置"})

    client = AIBOXClient("http://test", transport=httpx.MockTransport(handler))
    try:
        client.translate("Hello")
    except AIBOXAPIError as exc:
        assert exc.status_code == 400
        assert "服务未配置" in str(exc)
        assert exc.details == {"detail": "服务未配置"}
    else:
        raise AssertionError("expected AIBOXAPIError")
    finally:
        client.close()


def test_wait_job_polls_until_terminal():
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/images/generations/job_1"
        calls["count"] += 1
        status = "running" if calls["count"] == 1 else "completed"
        return httpx.Response(200, json={"id": "job_1", "status": status})

    client = AIBOXClient("http://test", transport=httpx.MockTransport(handler))
    result = client.wait_job("image", "job_1", timeout=5, interval=0)
    assert result["status"] == "completed"
    assert calls["count"] == 2
    client.close()
