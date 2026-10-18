from __future__ import annotations

import io
import time
import wave
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aibox_api.config import AppConfig
from aibox_api.main import create_app


def make_wav(seconds: float = 1.0) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x00\x00" * int(16000 * seconds))
    return buffer.getvalue()


def install_fake_model(config: AppConfig, model_id: str = "tiny") -> Path:
    model_dir = config.models_dir / model_id
    model_dir.mkdir(parents=True)
    (model_dir / "model.bin").write_bytes(b"\0" * 1_100_000)
    (model_dir / "config.json").write_text("{}", encoding="utf-8")
    (model_dir / "tokenizer.json").write_text("{}", encoding="utf-8")
    return model_dir


@pytest.fixture()
def client(tmp_path: Path):
    config = AppConfig(
        data_dir=tmp_path / "data",
        mock_asr=True,
        grpc_port=0,
        mrcp_port=0,
    )
    install_fake_model(config)
    app = create_app(config)
    with TestClient(app) as test_client:
        yield test_client, config


def test_health_and_settings(client):
    test_client, _ = client
    health = test_client.get("/api/health")
    assert health.status_code == 200
    payload = health.json()
    assert payload["status"] == "ok"
    assert payload["engine"]["demo"] is True
    settings = test_client.get("/api/settings").json()
    assert settings["language"] == "auto"
    patched = test_client.patch(
        "/api/settings", json={"language": "zh", "beam_size": 99, "device": "npu"}
    )
    assert patched.status_code == 200
    data = patched.json()
    assert data["language"] == "zh"
    assert data["beam_size"] == 10
    assert data["device"] == "npu"


def test_models_catalog_and_system(client):
    test_client, _ = client
    models = test_client.get("/api/models")
    assert models.status_code == 200
    data = models.json()
    assert len(data["catalog"]) >= 6
    assert data["installed"][0]["id"] == "tiny"
    assert data["catalog"][0]["engine"] == "faster-whisper"
    assert data["storage"]["installed_count"] == 1

    system = test_client.get("/api/system")
    assert system.status_code == 200
    payload = system.json()
    assert payload["platform"]["id"] in {"windows", "macos", "linux"}
    assert payload["cpu"]["cores"] >= 1
    assert any(item["kind"] == "cpu" for item in payload["accelerators"])


def test_unknown_model_download_is_rejected(client):
    test_client, _ = client
    response = test_client.post("/api/models/downloads", json={"model_id": "nope"})
    assert response.status_code == 404
    installed = test_client.post("/api/models/downloads", json={"model_id": "tiny"})
    assert installed.status_code == 409


def test_transcription_mock_roundtrip(client):
    test_client, config = client
    response = test_client.post(
        "/api/transcriptions",
        files={"file": ("demo.wav", make_wav(), "audio/wav")},
        data={
            "model_id": "tiny",
            "language": "auto",
            "device": "cpu",
            "compute_type": "int8",
            "beam_size": "5",
            "vad_filter": "true",
        },
    )
    assert response.status_code == 202, response.text
    record = response.json()
    assert record["status"] == "queued"
    transcription_id = record["id"]

    deadline = time.time() + 15
    latest = record
    while time.time() < deadline:
        latest = test_client.get(f"/api/transcriptions/{transcription_id}").json()
        if latest["status"] in {"completed", "failed"}:
            break
        time.sleep(0.15)

    assert latest["status"] == "completed", latest
    assert latest["text"]
    assert latest["segments"]
    assert latest["engine"] == "demo"
    assert latest["audio_url"].endswith("/audio")

    audio = test_client.get(latest["audio_url"])
    assert audio.status_code == 200
    assert len(audio.content) > 100

    srt = test_client.get(latest["export_urls"]["srt"])
    assert srt.status_code == 200
    assert "00:00:00,000 -->" in srt.text
    vtt = test_client.get(latest["export_urls"]["vtt"])
    assert vtt.text.startswith("WEBVTT")
    as_json = test_client.get(latest["export_urls"]["json"]).json()
    assert as_json["id"] == transcription_id

    history = test_client.get("/api/transcriptions").json()["items"]
    assert any(item["id"] == transcription_id for item in history)

    deleted = test_client.delete(f"/api/transcriptions/{transcription_id}")
    assert deleted.status_code == 200
    assert test_client.get(f"/api/transcriptions/{transcription_id}").status_code == 404


def test_transcription_rejects_empty_audio(client):
    test_client, _ = client
    response = test_client.post(
        "/api/transcriptions",
        files={"file": ("empty.wav", b"", "audio/wav")},
        data={"model_id": "tiny"},
    )
    assert response.status_code == 400


def test_delete_installed_model(client):
    test_client, config = client
    response = test_client.delete("/api/models/tiny")
    assert response.status_code == 200
    assert not (config.models_dir / "tiny").exists()
    assert test_client.get("/api/models").json()["storage"]["installed_count"] == 0
