"""Community adapter registry and execution tests."""

from __future__ import annotations

import io
import json
import sys
import threading
import time
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from fastapi.testclient import TestClient

from aibox_api.config import AppConfig
from aibox_api.main import create_app


def make_wav(seconds: float = 0.5, sample_rate: int = 16000) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(b"\x00\x00" * int(sample_rate * seconds))
    return buffer.getvalue()


def make_app(tmp_path: Path, **overrides) -> TestClient:
    values = {
        "data_dir": tmp_path / "data",
        "mock_asr": True,
        "demo_tts": True,
        "grpc_port": 0,
        "mrcp_port": 0,
        "allow_adapter_commands": True,
    }
    values.update(overrides)
    return TestClient(create_app(AppConfig(**values)))


def import_and_enable(client: TestClient, manifest: dict) -> dict:
    created = client.post("/api/community/adapters", json={"manifest": manifest})
    assert created.status_code == 201, created.text
    adapter_id = created.json()["id"]
    enabled = client.patch(
        f"/api/community/adapters/{adapter_id}", json={"enabled": True}
    )
    assert enabled.status_code == 200, enabled.text
    return enabled.json()


def test_builtin_templates_cover_mainstream_models(tmp_path):
    with make_app(tmp_path) as client:
        payload = client.get("/api/community").json()
        assert payload["summary"]["templates"] >= 14
        kinds = {item["kind"] for item in payload["templates"]}
        assert kinds == {"asr", "tts"}
        names = {item["id"] for item in payload["templates"]}
        assert {"sensevoice-small", "piper-zh-huayan", "kokoro-82m"} <= names
        manifest = client.get("/api/community/templates/piper-zh-huayan")
        assert manifest.status_code == 200
        body = manifest.json()
        assert body["kind"] == "tts"
        assert body["adapter"]["type"] == "command"


def test_import_external_model_and_toggle(tmp_path):
    with make_app(tmp_path) as client:
        manifest = {
            "id": "community-tts",
            "name": "Community TTS",
            "kind": "tts",
            "description": "test",
            "adapter": {
                "type": "openai-http",
                "base_url": "http://127.0.0.1:9999/v1",
                "model": "community-tts",
            },
        }
        adapter = import_and_enable(client, manifest)
        assert adapter["status"] == "ready"
        models = client.get("/api/models").json()
        entry = next(item for item in models["catalog"] if item["id"] == "community-tts")
        assert entry["installed"] is True
        assert entry["external"] is True
        assert entry["adapter_id"] == "community-tts"

        disabled = client.patch(
            "/api/community/adapters/community-tts", json={"enabled": False}
        )
        assert disabled.status_code == 200
        assert disabled.json()["status"] == "disabled"
        assert "community-tts" not in {
            item["id"] for item in client.get("/api/models").json()["catalog"]
        }

        assert client.delete("/api/community/adapters/community-tts").status_code == 200
        assert "community-tts" not in {
            item["id"] for item in client.get("/api/models").json()["catalog"]
        }


def test_command_asr_adapter_end_to_end(tmp_path):
    runner = tmp_path / "fake_asr.py"
    runner.write_text(
        "\n".join(
            [
                "import argparse, json",
                "p = argparse.ArgumentParser()",
                "p.add_argument('--audio')",
                "p.add_argument('--output')",
                "a = p.parse_args()",
                "json.dump({'text': 'community asr works', 'language': 'en',",
                "           'segments': [{'start': 0, 'end': 0.5, 'text': 'community asr works'}]},",
                "          open(a.output, 'w'), ensure_ascii=False)",
            ]
        ),
        encoding="utf-8",
    )
    with make_app(tmp_path) as client:
        manifest = {
            "id": "community-asr",
            "name": "Community ASR",
            "kind": "asr",
            "adapter": {
                "type": "command",
                "command": [
                    sys.executable,
                    str(runner),
                    "--audio",
                    "{audio}",
                    "--output",
                    "{output}",
                ],
                "output": "json",
            },
        }
        import_and_enable(client, manifest)
        created = client.post(
            "/api/transcriptions",
            files={"file": ("sample.wav", make_wav(), "audio/wav")},
            data={"model_id": "community-asr"},
        )
        assert created.status_code == 202, created.text
        transcription_id = created.json()["id"]
        record = None
        for _ in range(40):
            record = client.get(f"/api/transcriptions/{transcription_id}").json()
            if record["status"] in {"completed", "failed", "cancelled"}:
                break
            time.sleep(0.1)
        assert record is not None
        assert record["status"] == "completed", record
        assert record["text"] == "community asr works"
        assert record["engine"] == "community:command"


def test_command_tts_adapter_end_to_end(tmp_path):
    runner = tmp_path / "fake_tts.py"
    runner.write_text(
        "\n".join(
            [
                "import argparse, math, wave",
                "p = argparse.ArgumentParser()",
                "p.add_argument('--text')",
                "p.add_argument('--output')",
                "a = p.parse_args()",
                "with wave.open(a.output, 'wb') as f:",
                "    f.setnchannels(1); f.setsampwidth(2); f.setframerate(16000)",
                "    f.writeframes(b''.join(int(8000*math.sin(i/8)).to_bytes(2,'little',signed=True) for i in range(1600)))",
            ]
        ),
        encoding="utf-8",
    )
    with make_app(tmp_path) as client:
        manifest = {
            "id": "community-command-tts",
            "name": "Community Command TTS",
            "kind": "tts",
            "adapter": {
                "type": "command",
                "command": [
                    sys.executable,
                    str(runner),
                    "--text",
                    "{text}",
                    "--output",
                    "{output}",
                ],
                "output": "wav",
            },
        }
        import_and_enable(client, manifest)
        response = client.post(
            "/v1/audio/speech",
            json={
                "model": "community-command-tts",
                "input": "hello community",
                "voice": "default",
                "response_format": "wav",
            },
        )
        assert response.status_code == 200, response.text
        assert response.content.startswith(b"RIFF")


def test_openai_http_adapters_end_to_end(tmp_path):
    wav = make_wav()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            length = int(self.headers.get("content-length") or 0)
            self.rfile.read(length)
            if self.path.endswith("/audio/speech"):
                self.send_response(200)
                self.send_header("content-type", "audio/wav")
                self.end_headers()
                self.wfile.write(wav)
            elif self.path.endswith("/audio/transcriptions"):
                body = json.dumps(
                    {
                        "text": "http adapter asr",
                        "language": "en",
                        "segments": [{"start": 0, "end": 0.5, "text": "http adapter asr"}],
                    }
                ).encode()
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_error(404)

        def log_message(self, *_args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}/v1"
    try:
        with make_app(tmp_path) as client:
            import_and_enable(
                client,
                {
                    "id": "http-asr",
                    "name": "HTTP ASR",
                    "kind": "asr",
                    "adapter": {
                        "type": "openai-http",
                        "base_url": base_url,
                        "model": "http-asr",
                    },
                },
            )
            import_and_enable(
                client,
                {
                    "id": "http-tts",
                    "name": "HTTP TTS",
                    "kind": "tts",
                    "adapter": {
                        "type": "openai-http",
                        "base_url": base_url,
                        "model": "http-tts",
                    },
                },
            )
            created = client.post(
                "/api/transcriptions",
                files={"file": ("sample.wav", make_wav(), "audio/wav")},
                data={"model_id": "http-asr"},
            )
            assert created.status_code == 202, created.text
            transcription_id = created.json()["id"]
            record = None
            for _ in range(40):
                record = client.get(f"/api/transcriptions/{transcription_id}").json()
                if record["status"] in {"completed", "failed", "cancelled"}:
                    break
                time.sleep(0.1)
            assert record is not None
            assert record["status"] == "completed", record
            assert record["text"] == "http adapter asr"

            speech = client.post(
                "/v1/audio/speech",
                json={
                    "model": "http-tts",
                    "input": "hello",
                    "voice": "default",
                    "response_format": "wav",
                },
            )
            assert speech.status_code == 200, speech.text
            assert speech.content.startswith(b"RIFF")
    finally:
        server.shutdown()
        server.server_close()


def test_command_and_remote_security_gates(tmp_path):
    with make_app(tmp_path, allow_adapter_commands=False) as client:
        command_manifest = {
            "id": "gated-command",
            "name": "Gated command",
            "kind": "asr",
            "adapter": {"type": "command", "command": ["python", "-V"]},
        }
        adapter = import_and_enable(client, command_manifest)
        assert adapter["status"] == "needs-command-gate"
        assert "gated-command" not in {
            item["id"] for item in client.get("/api/models").json()["catalog"]
        }

    with make_app(tmp_path / "remote", allow_remote_adapters=False) as client:
        remote_manifest = {
            "id": "remote-tts",
            "name": "Remote TTS",
            "kind": "tts",
            "adapter": {
                "type": "openai-http",
                "base_url": "https://example.com/v1",
                "model": "tts-1",
            },
        }
        adapter = import_and_enable(client, remote_manifest)
        assert adapter["status"] == "needs-remote-gate"
        assert "remote-tts" not in {
            item["id"] for item in client.get("/api/models").json()["catalog"]
        }
