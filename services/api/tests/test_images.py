"""Image generation API and ComfyUI adapter tests."""

from __future__ import annotations

import io
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from aibox_api.config import AppConfig
from aibox_api.main import create_app


def make_png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (32, 32), (30, 120, 200)).save(buffer, format="PNG")
    return buffer.getvalue()


def make_app(tmp_path: Path, **overrides) -> TestClient:
    values = {
        "data_dir": tmp_path / "data",
        "mock_asr": True,
        "demo_tts": True,
        "demo_image": True,
        "grpc_port": 0,
        "mrcp_port": 0,
    }
    values.update(overrides)
    return TestClient(create_app(AppConfig(**values)))


def wait_job(client: TestClient, job_id: str, timeout: float = 15.0) -> dict:
    deadline = time.monotonic() + timeout
    record = {}
    while time.monotonic() < deadline:
        record = client.get(f"/api/images/generations/{job_id}").json()
        if record["status"] in {"completed", "failed", "cancelled"}:
            return record
        time.sleep(0.1)
    return record


def test_image_catalog_and_demo_job(tmp_path):
    with make_app(tmp_path) as client:
        models = client.get("/api/models").json()
        image_models = [item for item in models["catalog"] if item["kind"] == "image"]
        assert {item["id"] for item in image_models} >= {
            "sd15",
            "sdxl",
            "flux1-schnell",
            "qwen-image",
        }
        assert models["image_recommendation"]["model_id"]

        created = client.post(
            "/api/images/generations",
            json={
                "prompt": "a demo image",
                "model": "sd15",
                "provider": "demo",
                "width": 512,
                "height": 512,
                "batch": 1,
            },
        )
        assert created.status_code == 202, created.text
        job = wait_job(client, created.json()["id"])
        assert job["status"] == "completed", job
        assert job["provider"] == "demo"
        assert job["image_urls"]
        image = client.get(job["image_urls"][0])
        assert image.status_code == 200
        assert image.content.startswith(b"\x89PNG")
        assert client.get("/api/images/generations").json()["items"]

        opened = client.post(
            "/v1/images/generations",
            json={
                "prompt": "openai compatible image",
                "model": "sd15",
                "n": 1,
                "size": "512x512",
                "response_format": "b64_json",
            },
        )
        assert opened.status_code == 200, opened.text
        payload = opened.json()
        assert payload["data"][0]["b64_json"]
        assert payload["data"][0]["revised_prompt"] == "openai compatible image"

        deleted = client.delete(f"/api/images/generations/{job['id']}")
        assert deleted.status_code == 200
        assert client.get(f"/api/images/generations/{job['id']}").status_code == 404


def test_comfyui_adapter_with_fake_server(tmp_path):
    captured: dict = {}
    png = make_png()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            if self.path == "/system_stats":
                body = json.dumps({"system": {"comfyui_version": "test"}}).encode()
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.end_headers()
                self.wfile.write(body)
            elif self.path.startswith("/history/"):
                prompt_id = captured.get("prompt_id", "p1")
                body = json.dumps(
                    {
                        prompt_id: {
                            "outputs": {
                                "9": {
                                    "images": [
                                        {
                                            "filename": "fake.png",
                                            "subfolder": "",
                                            "type": "output",
                                        }
                                    ]
                                }
                            }
                        }
                    }
                ).encode()
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.end_headers()
                self.wfile.write(body)
            elif self.path.startswith("/view"):
                self.send_response(200)
                self.send_header("content-type", "image/png")
                self.end_headers()
                self.wfile.write(png)
            else:
                self.send_error(404)

        def do_POST(self):  # noqa: N802
            length = int(self.headers.get("content-length") or 0)
            captured["body"] = json.loads(self.rfile.read(length))
            captured["prompt_id"] = "p1"
            body = json.dumps({"prompt_id": "p1", "number": 1}).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    import threading

    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with make_app(
            tmp_path,
            demo_image=False,
            comfyui_url=f"http://127.0.0.1:{server.server_port}",
        ) as client:
            created = client.post(
                "/api/images/generations",
                json={
                    "prompt": "comfy prompt",
                    "negative_prompt": "bad",
                    "model": "sd15",
                    "provider": "comfyui",
                    "width": 512,
                    "height": 512,
                    "steps": 8,
                    "guidance_scale": 5,
                    "seed": 42,
                    "checkpoint": "fake.safetensors",
                },
            )
            assert created.status_code == 202, created.text
            job = wait_job(client, created.json()["id"])
            assert job["status"] == "completed", job
            assert job["provider"] == "comfyui"
            workflow = captured["body"]["prompt"]
            assert workflow["4"]["inputs"]["ckpt_name"] == "fake.safetensors"
            assert workflow["6"]["inputs"]["text"] == "comfy prompt"
            assert workflow["7"]["inputs"]["text"] == "bad"
            assert workflow["3"]["inputs"]["seed"] == 42
            assert workflow["3"]["inputs"]["steps"] == 8
            assert job["image_urls"]
            assert client.get(job["image_urls"][0]).content.startswith(b"\x89PNG")
    finally:
        server.shutdown()
        server.server_close()
