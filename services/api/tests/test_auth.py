"""Built-in accounts, sessions, RBAC and external-header auth tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from aibox_api.config import AppConfig
from aibox_api.main import create_app


def make_client(tmp_path, **overrides) -> TestClient:
    config = AppConfig(
        data_dir=tmp_path / "data",
        mock_asr=True,
        demo_tts=True,
        demo_image=True,
        demo_separation=True,
        demo_video=True,
        demo_llm=True,
        demo_training=True,
        demo_translation=True,
        demo_ocr=True,
        grpc_port=0,
        mrcp_port=0,
        auth_enabled=True,
        **overrides,
    )
    return TestClient(create_app(config))


def test_bootstrap_login_and_viewer_permissions(tmp_path):
    client = make_client(tmp_path)
    assert client.get("/api/health").status_code == 200
    status = client.get("/api/auth/status").json()
    assert status["enabled"] is True
    assert status["needs_setup"] is True

    boot = client.post(
        "/api/auth/bootstrap",
        json={"username": "admin", "password": "admin-pass-123"},
    )
    assert boot.status_code == 200
    admin_token = boot.json()["token"]
    headers = {"Authorization": f"Bearer {admin_token}"}
    assert client.get("/api/settings", headers=headers).status_code == 200

    created = client.post(
        "/api/auth/users",
        headers=headers,
        json={"username": "viewer", "password": "viewer-pass-123", "role": "viewer"},
    )
    assert created.status_code == 201

    login = client.post(
        "/api/auth/login",
        json={"username": "viewer", "password": "viewer-pass-123"},
    )
    assert login.status_code == 200
    viewer_headers = {"Authorization": f"Bearer {login.json()['token']}"}
    assert client.get("/api/settings", headers=viewer_headers).status_code == 200
    assert (
        client.post(
            "/api/settings",
            headers=viewer_headers,
            json={"llm_provider": "demo"},
        ).status_code
        == 403
    )
    assert client.get("/api/auth/users", headers=viewer_headers).status_code == 403
    assert client.get("/api/settings").status_code == 401


def test_external_header_auth(tmp_path):
    client = make_client(tmp_path, auth_mode="external")
    assert client.get("/api/auth/status").json()["mode"] == "external"
    assert client.get("/api/settings").status_code == 401
    headers = {
        "X-Forwarded-User": "alice",
        "X-Forwarded-Roles": "operator",
    }
    response = client.get("/api/settings", headers=headers)
    assert response.status_code == 200
    assert client.get("/api/auth/me", headers=headers).json()["user"]["username"] == "alice"
