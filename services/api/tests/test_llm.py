"""Language model catalog, demo chat and OpenAI-compatible tests."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from fastapi.testclient import TestClient

from aibox_api.catalog import get_llm_model, llm_models
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
        "demo_llm": True,
        "grpc_port": 0,
        "mrcp_port": 0,
    }
    values.update(overrides)
    return TestClient(create_app(AppConfig(**values)))


def test_llm_catalog(tmp_path):
    assert len(llm_models()) >= 6
    spec = get_llm_model("qwen3-8b")
    assert spec is not None
    assert spec.download_files == ("Qwen3-8B-Q4_K_M.gguf",)
    assert spec.context_length > 0
    with make_app(tmp_path) as client:
        payload = client.get("/api/models").json()
        llm = [item for item in payload["catalog"] if item["kind"] == "llm"]
        assert len(llm) == len(llm_models())
        assert payload["llm_recommendation"]["model_id"]


def test_llm_installed_model_and_openai_models(tmp_path):
    model_dir = tmp_path / "data" / "models" / "llm" / "qwen3-8b"
    model_dir.mkdir(parents=True)
    (model_dir / "Qwen3-8B-Q4_K_M.gguf").write_bytes(b"GGUF" + b"\x00" * 64)
    with make_app(tmp_path) as client:
        payload = client.get("/api/models").json()
        qwen = next(item for item in payload["catalog"] if item["id"] == "qwen3-8b")
        assert qwen["installed"] is True
        models = client.get("/v1/models").json()
        assert any(item["id"] == "qwen3-8b" for item in models["data"])


def test_llm_demo_chat_and_openai(tmp_path):
    with make_app(tmp_path) as client:
        status = client.get("/api/llm/status").json()
        assert status["demo"] is True
        assert status["models"] == []

        response = client.post(
            "/api/llm/chat",
            json={
                "model": "qwen3-8b",
                "messages": [{"role": "user", "content": "你好"}],
                "stream": False,
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["choices"][0]["message"]["role"] == "assistant"
        assert body["choices"][0]["message"]["content"]

        stream = client.post(
            "/api/llm/chat",
            json={
                "model": "qwen3-8b",
                "messages": [{"role": "user", "content": "你好"}],
                "stream": True,
            },
        )
        assert stream.status_code == 200
        text = stream.text
        assert "data: " in text
        assert "[DONE]" in text

        openai = client.post(
            "/v1/chat/completions",
            json={
                "model": "qwen3-8b",
                "messages": [{"role": "user", "content": "hello"}],
            },
        )
        assert openai.status_code == 200, openai.text
        assert openai.json()["object"] == "chat.completion"


def test_external_openai_compatible_chat(tmp_path):
    def handler_factory():
        class Handler(BaseHTTPRequestHandler):
            def _json(self, payload):
                body = json.dumps(payload).encode()
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):  # noqa: N802
                if self.path.startswith("/v1/models"):
                    self._json(
                        {
                            "object": "list",
                            "data": [{"id": "fake-model", "object": "model"}],
                        }
                    )
                else:
                    self.send_error(404)

            def do_POST(self):  # noqa: N802
                length = int(self.headers.get("content-length") or 0)
                payload = json.loads(self.rfile.read(length) or b"{}")
                if self.path != "/v1/chat/completions":
                    self.send_error(404)
                    return
                if payload.get("stream"):
                    self.send_response(200)
                    self.send_header("content-type", "text/event-stream")
                    self.end_headers()
                    chunk = {
                        "id": "chatcmpl-test",
                        "object": "chat.completion.chunk",
                        "created": 0,
                        "model": "fake-model",
                        "choices": [
                            {
                                "index": 0,
                                "delta": {"content": "外部模型回答"},
                                "finish_reason": None,
                            }
                        ],
                    }
                    self.wfile.write(
                        ("data: " + json.dumps(chunk, ensure_ascii=False) + "\n\n").encode()
                    )
                    self.wfile.write(b"data: [DONE]\n\n")
                else:
                    self._json(
                        {
                            "id": "chatcmpl-test",
                            "object": "chat.completion",
                            "created": 0,
                            "model": "fake-model",
                            "choices": [
                                {
                                    "index": 0,
                                    "message": {
                                        "role": "assistant",
                                        "content": "外部模型回答",
                                    },
                                    "finish_reason": "stop",
                                }
                            ],
                        }
                    )

            def log_message(self, *_args):
                return

        return Handler

    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_factory())
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with make_app(
            tmp_path,
            demo_llm=False,
            llm_base_url=f"http://127.0.0.1:{server.server_port}/v1",
            llm_model="fake-model",
        ) as client:
            status = client.get("/api/llm/status").json()
            assert status["external"]["configured"] is True
            assert status["external"]["models"] == ["fake-model"]

            response = client.post(
                "/api/llm/chat",
                json={
                    "model": "fake-model",
                    "messages": [{"role": "user", "content": "hi"}],
                    "stream": False,
                },
            )
            assert response.status_code == 200, response.text
            assert response.json()["choices"][0]["message"]["content"] == "外部模型回答"

            stream = client.post(
                "/api/llm/chat",
                json={
                    "model": "fake-model",
                    "messages": [{"role": "user", "content": "hi"}],
                    "stream": True,
                },
            )
            assert stream.status_code == 200
            assert "外部模型回答" in stream.text
    finally:
        server.shutdown()
        server.server_close()

def test_external_runtime_providers(tmp_path):
    from aibox_api.llm import LLMEngine

    config = AppConfig(
        data_dir=tmp_path / "data",
        mock_asr=True,
        vllm_base_url="http://vllm.test/v1",
        vllm_model="Qwen/Qwen3-8B",
        llm_tensor_parallel_size=4,
        llm_pipeline_parallel_size=2,
    )
    config.update_settings({"llm_provider": "vllm"})
    engine = LLMEngine(config)
    model, provider = engine.resolve_model(None)
    assert provider == "vllm"
    assert model == "Qwen/Qwen3-8B"
    status = engine.status()
    assert status["distributed"]["tensor_parallel_size"] == 4
    assert any(item["id"] == "sglang" for item in status["external_providers"])
