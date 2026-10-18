"""Fine-tuning dataset and training job API tests."""

from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi.testclient import TestClient

from aibox_api.config import AppConfig
from aibox_api.main import create_app


def make_app(tmp_path: Path) -> TestClient:
    return TestClient(
        create_app(
            AppConfig(
                data_dir=tmp_path / "data",
                mock_asr=True,
                demo_tts=True,
                demo_image=True,
                demo_separation=True,
                demo_video=True,
                demo_llm=True,
                demo_training=True,
                grpc_port=0,
                mrcp_port=0,
            )
        )
    )


def wait_job(client: TestClient, job_id: str, timeout: float = 30) -> dict:
    deadline = time.monotonic() + timeout
    record = {}
    while time.monotonic() < deadline:
        record = client.get(f"/api/training/jobs/{job_id}").json()
        if record["status"] in {"completed", "failed", "cancelled"}:
            return record
        time.sleep(0.2)
    return record


def test_training_dataset_and_demo_job(tmp_path):
    with make_app(tmp_path) as client:
        status = client.get("/api/training/status").json()
        assert status["demo"] is True
        assert any(item["id"] == "qlora" for item in status["methods"])

        content = "\n".join(
            json.dumps({"messages": [{"role": "user", "content": f"hi {i}"}]})
            for i in range(3)
        )
        dataset = client.post(
            "/api/training/datasets",
            files={"file": ("tiny.jsonl", content.encode(), "application/jsonl")},
            data={"name": "tiny"},
        )
        assert dataset.status_code == 201, dataset.text
        ds = dataset.json()
        assert ds["rows"] == 3
        assert ds["preview"]

        job = client.post(
            "/api/training/jobs",
            json={
                "name": "demo-lora",
                "base_model": "Qwen/Qwen3-8B",
                "method": "qlora",
                "dataset_id": ds["id"],
                "epochs": 1,
                "batch_size": 1,
                "parallel_strategy": "single",
            },
        )
        assert job.status_code == 202, job.text
        record = wait_job(client, job.json()["id"])
        assert record["status"] == "completed", record
        assert record["artifacts"]
        logs = client.get(record["log_url"]).json()
        assert "AIBox demo training" in logs["text"]
        artifact = client.get(record["artifacts"][0]["url"])
        assert artifact.status_code == 200

        assert client.delete(f"/api/training/jobs/{record['id']}").status_code == 200
        assert client.delete(f"/api/training/datasets/{ds['id']}").status_code == 200


def test_training_rejects_bad_dataset(tmp_path):
    with make_app(tmp_path) as client:
        bad = client.post(
            "/api/training/datasets",
            files={"file": ("bad.jsonl", b'{"foo": 1}\n', "application/jsonl")},
        )
        assert bad.status_code == 400
        assert "messages" in bad.json()["detail"]
