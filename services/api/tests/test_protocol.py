"""AIBOX Unified Protocol discovery tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from aibox_api.config import AppConfig
from aibox_api.main import create_app


def test_protocol_manifest_and_header(tmp_path):
    client = TestClient(create_app(AppConfig(data_dir=tmp_path / "data", mock_asr=True)))
    response = client.get("/api/protocol")
    assert response.status_code == 200
    assert response.headers["X-AIBox-Protocol"] == "1.0"
    payload = response.json()
    assert payload["protocol"] == "aibox-unified"
    assert payload["version"] == "1.0"
    assert payload["compatibility"] == "1.x"
    assert payload["capabilities"]["chat_streaming"] is True
    assert payload["job_states"]["completed"] == "terminal success"
    ids = {item["id"] for item in payload["endpoints"]}
    assert {"chat", "transcribe", "speech", "translation", "ocr"} <= ids
    assert client.get("/api/health").headers["X-AIBox-Protocol"] == "1.0"
