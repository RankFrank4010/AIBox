"""Standalone coordinator tests: control plane only, no inference."""

from __future__ import annotations

from fastapi.testclient import TestClient

from aibox_api.config import AppConfig
from aibox_api.coordinator import create_coordinator_app


def test_coordinator_has_no_inference(tmp_path):
    config = AppConfig(
        data_dir=tmp_path / "data",
        cluster_enabled=True,
        cluster_token="secret",
    )
    client = TestClient(create_coordinator_app(config))
    health = client.get("/api/health").json()
    assert health["role"] == "coordinator"
    assert health["ai_inference"] is False
    assert health["cluster"]["enabled"] is True
    assert client.get("/api/cluster/status").status_code == 200
    assert client.get("/api/transcriptions").status_code == 404
