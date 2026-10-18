"""Vocal / background separation API tests."""

from __future__ import annotations

import io
import time
import wave
from pathlib import Path

from fastapi.testclient import TestClient

from aibox_api.config import AppConfig
from aibox_api.main import create_app


def make_wav(seconds: float = 1.0, rate: int = 44100) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x00\x00\x00\x00" * int(rate * seconds))
    return buffer.getvalue()


def make_app(tmp_path: Path) -> TestClient:
    return TestClient(
        create_app(
            AppConfig(
                data_dir=tmp_path / "data",
                mock_asr=True,
                demo_tts=True,
                demo_image=True,
                demo_separation=True,
                grpc_port=0,
                mrcp_port=0,
            )
        )
    )


def wait_job(client: TestClient, job_id: str, timeout: float = 20.0) -> dict:
    deadline = time.monotonic() + timeout
    record = {}
    while time.monotonic() < deadline:
        record = client.get(f"/api/separations/{job_id}").json()
        if record["status"] in {"completed", "failed", "cancelled"}:
            return record
        time.sleep(0.1)
    return record


def test_separation_models_and_demo(tmp_path):
    with make_app(tmp_path) as client:
        status = client.get("/api/separations/status").json()
        assert status["demo"] is True
        model_ids = {item["id"] for item in status["models"]}
        assert {"htdemucs", "htdemucs_ft", "uvr-mdx-inst-hq3"} <= model_ids

        created = client.post(
            "/api/separations",
            files={"file": ("song.wav", make_wav(), "audio/wav")},
            data={"model_id": "htdemucs", "mode": "instrumental"},
        )
        assert created.status_code == 202, created.text
        job = wait_job(client, created.json()["id"])
        assert job["status"] == "completed", job
        assert len(job["outputs"]) == 1
        assert job["outputs"][0]["role"] == "instrumental"
        response = client.get(job["outputs"][0]["url"])
        assert response.status_code == 200
        assert response.content.startswith(b"RIFF")

        stems = client.post(
            "/api/separations",
            files={"file": ("song.wav", make_wav(), "audio/wav")},
            data={"model_id": "htdemucs", "mode": "stems"},
        )
        assert stems.status_code == 202, stems.text
        job = wait_job(client, stems.json()["id"])
        assert job["status"] == "completed", job
        assert {item["role"] for item in job["outputs"]} == {
            "vocals",
            "drums",
            "bass",
            "other",
        }
        assert client.delete(f"/api/separations/{job['id']}").status_code == 200
        assert client.get(f"/api/separations/{job['id']}").status_code == 404


def test_separation_vocals_mode(tmp_path):
    with make_app(tmp_path) as client:
        created = client.post(
            "/api/separations",
            files={"file": ("vocals.wav", make_wav(), "audio/wav")},
            data={"model_id": "uvr-mdx-voc-ft", "mode": "vocals"},
        )
        assert created.status_code == 202, created.text
        job = wait_job(client, created.json()["id"])
        assert job["status"] == "completed", job
        assert [item["role"] for item in job["outputs"]] == ["vocals"]
