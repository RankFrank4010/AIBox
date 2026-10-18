"""Video generation API and MiniMax provider tests."""

from __future__ import annotations

import json
import shutil
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aibox_api.config import AppConfig
from aibox_api.main import create_app


def make_app(tmp_path: Path, **overrides) -> TestClient:
    values = {
        "data_dir": tmp_path / "data",
        "mock_asr": True,
        "demo_tts": True,
        "demo_image": True,
        "demo_separation": True,
        "demo_video": True,
        "grpc_port": 0,
        "mrcp_port": 0,
    }
    values.update(overrides)
    return TestClient(create_app(AppConfig(**values)))


def wait_job(client: TestClient, job_id: str, timeout: float = 30) -> dict:
    deadline = time.monotonic() + timeout
    record = {}
    while time.monotonic() < deadline:
        record = client.get(f"/api/videos/{job_id}").json()
        if record["status"] in {"completed", "failed", "cancelled"}:
            return record
        time.sleep(0.15)
    return record


def test_video_catalog_and_demo(tmp_path):
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg is required for demo video")
    with make_app(tmp_path) as client:
        status = client.get("/api/videos/status").json()
        assert status["demo"] is True
        ids = {item["id"] for item in status["models"]}
        assert {"minimax-h3", "minimax-hailuo-02", "wan2.1-t2v"} <= ids

        created = client.post(
            "/api/videos",
            json={
                "prompt": "a short demo shot",
                "model": "minimax-h3",
                "duration": 2,
                "resolution": "768P",
                "aspect": "16:9",
            },
        )
        assert created.status_code == 202, created.text
        job = wait_job(client, created.json()["id"])
        assert job["status"] == "completed", job
        assert job["provider"] == "demo"
        assert job["video_url"]
        video = client.get(job["video_url"])
        assert video.status_code == 200
        assert b"ftyp" in video.content[:32]
        assert job["poster_url"]
        assert client.get(job["poster_url"]).status_code == 200
        assert client.delete(f"/api/videos/{job['id']}").status_code == 200
        assert client.get(f"/api/videos/{job['id']}").status_code == 404


def test_minimax_provider_with_fake_api(tmp_path):
    fake_video = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64

    class Handler(BaseHTTPRequestHandler):
        def _json(self, payload):
            body = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):  # noqa: N802
            self.rfile.read(int(self.headers.get("content-length") or 0))
            if self.path.endswith("/video_generation"):
                self._json({"task_id": "task-1", "base_resp": {"status_code": 0}})
            else:
                self.send_error(404)

        def do_GET(self):  # noqa: N802
            if self.path.startswith("/v1/query/video_generation"):
                self._json({"status": "Success", "file_id": "file-1"})
            elif self.path.startswith("/v1/files/retrieve"):
                self._json(
                    {
                        "file": {
                            "download_url": f"http://127.0.0.1:{self.server.server_port}/download"
                        }
                    }
                )
            elif self.path == "/download":
                self.send_response(200)
                self.send_header("content-type", "video/mp4")
                self.end_headers()
                self.wfile.write(fake_video)
            else:
                self.send_error(404)

        def log_message(self, *_args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    import threading

    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with make_app(
            tmp_path,
            demo_video=False,
            minimax_api_key="test-key",
            minimax_base_url=f"http://127.0.0.1:{server.server_port}/v1",
        ) as client:
            created = client.post(
                "/api/videos",
                json={
                    "prompt": "minimax fake",
                    "model": "minimax-h3",
                    "duration": 6,
                    "resolution": "1080P",
                },
            )
            assert created.status_code == 202, created.text
            job = wait_job(client, created.json()["id"])
            assert job["status"] == "completed", job
            assert job["provider"] == "minimax"
            assert job["video_url"]
            data = client.get(job["video_url"]).content
            assert data.startswith(b"\x00\x00\x00\x18ftyp")
    finally:
        server.shutdown()
        server.server_close()
