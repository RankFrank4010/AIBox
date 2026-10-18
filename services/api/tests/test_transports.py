from __future__ import annotations

import io
import socket
import sys
import wave

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from aibox_api.config import AppConfig
from aibox_api.main import create_app


def make_wav(seconds: float = 1.0, sample_rate: int = 16000) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(b"\x00\x00" * int(sample_rate * seconds))
    return buffer.getvalue()


def make_app(tmp_path, **overrides):
    values = {
        "data_dir": tmp_path / "data",
        "mock_asr": True,
        "demo_tts": True,
        "grpc_port": 0,
        "mrcp_port": 0,
    }
    values.update(overrides)
    config = AppConfig(**values)
    model_dir = config.models_dir / "tiny"
    model_dir.mkdir(parents=True)
    (model_dir / "model.bin").write_bytes(b"\0" * 1_100_000)
    (model_dir / "config.json").write_text("{}", encoding="utf-8")
    (model_dir / "tokenizer.json").write_text("{}", encoding="utf-8")
    return create_app(config)


def free_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture()
def client(tmp_path):
    with TestClient(make_app(tmp_path)) as test_client:
        yield test_client


def test_services_and_models(client):
    services = client.get("/api/services")
    assert services.status_code == 200
    payload = services.json()
    assert payload["openai"]["transcriptions"] == "/v1/audio/transcriptions"
    assert payload["websocket"]["path"] == "/ws/asr"
    assert payload["grpc"]["status"] == "disabled"
    assert payload["mrcp"]["status"] == "disabled"

    models = client.get("/v1/models")
    assert models.status_code == 200
    ids = [item["id"] for item in models.json()["data"]]
    assert "whisper-1" in ids
    assert "tiny" in ids


def test_openai_transcription_formats(client):
    audio = make_wav()
    base = {
        "model": "whisper-1",
        "language": "en",
    }
    json_response = client.post(
        "/v1/audio/transcriptions",
        files={"file": ("demo.wav", audio, "audio/wav")},
        data=base,
    )
    assert json_response.status_code == 200, json_response.text
    assert json_response.json()["text"]
    assert json_response.headers["x-aibox-model"] == "tiny"

    text_response = client.post(
        "/v1/audio/transcriptions",
        files={"file": ("demo.wav", audio, "audio/wav")},
        data={**base, "response_format": "text"},
    )
    assert text_response.status_code == 200
    assert "AIBox" in text_response.text or text_response.text.strip()

    verbose_response = client.post(
        "/v1/audio/transcriptions",
        files={"file": ("demo.wav", audio, "audio/wav")},
        data={**base, "response_format": "verbose_json"},
    )
    assert verbose_response.status_code == 200
    verbose = verbose_response.json()
    assert verbose["segments"]
    assert verbose["task"] == "transcribe"
    assert verbose["duration"] > 0

    srt_response = client.post(
        "/v1/audio/transcriptions",
        files={"file": ("demo.wav", audio, "audio/wav")},
        data={**base, "response_format": "srt"},
    )
    assert srt_response.status_code == 200
    assert "-->" in srt_response.text


def test_openai_model_errors(client):
    audio = make_wav(0.2)
    missing = client.post(
        "/v1/audio/transcriptions",
        files={"file": ("demo.wav", audio, "audio/wav")},
        data={"model": "large-v3"},
    )
    assert missing.status_code == 404
    body = missing.json()
    assert body["error"]["code"] == "model_not_installed"

    unknown = client.post(
        "/v1/audio/transcriptions",
        files={"file": ("demo.wav", audio, "audio/wav")},
        data={"model": "does-not-exist"},
    )
    assert unknown.status_code == 404
    assert unknown.json()["error"]["code"] == "model_not_found"


def test_openai_bearer_auth(tmp_path):
    app = make_app(tmp_path, api_token="secret-token")
    with TestClient(app) as client:
        unauthorized = client.get("/v1/models")
        assert unauthorized.status_code == 401
        assert unauthorized.json()["error"]["code"] == "invalid_api_key"
        authorized = client.get(
            "/v1/models", headers={"Authorization": "Bearer secret-token"}
        )
        assert authorized.status_code == 200


def test_websocket_pcm_transcription(client):
    pcm = b"\x00\x00" * 16000
    with client.websocket_connect("/ws/asr") as websocket:
        websocket.send_json(
            {
                "type": "start",
                "model": "tiny",
                "language": "en",
                "format": "pcm16",
                "sample_rate": 16000,
            }
        )
        started = websocket.receive_json()
        assert started["type"] == "ready"
        websocket.send_bytes(pcm)
        websocket.send_json({"type": "stop"})
        final = None
        for _ in range(200):
            event = websocket.receive_json()
            if event["type"] == "final":
                final = event
                break
            if event["type"] == "error":
                pytest.fail(event)
        assert final is not None
        assert final["text"]
        assert final["segments"]
        assert final["device"] == "demo"


def test_websocket_bearer_auth(tmp_path):
    app = make_app(tmp_path, api_token="secret-token")
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/ws/asr") as websocket:
                websocket.receive_json()


def test_tts_demo_endpoints(client):
    status = client.get("/api/tts/status")
    assert status.status_code == 200
    payload = status.json()
    assert payload["status"] == "demo"
    assert payload["engine"] == "indextts"

    voices = client.get("/api/tts/voices")
    assert voices.status_code == 200
    assert any(item["id"] == "default-en" for item in voices.json()["voices"])

    local = client.post(
        "/api/tts/synthesize",
        json={
            "text": "Hello from AIBox",
            "model": "indextts-2.5",
            "voice": "default-en",
            "response_format": "wav",
            "speed": 1.0,
        },
    )
    assert local.status_code == 200, local.text
    assert local.content.startswith(b"RIFF")
    assert local.headers["x-aibox-warning"] == "demo-engine"

    openai = client.post(
        "/v1/audio/speech",
        json={
            "model": "tts-1",
            "input": "Hello from AIBox",
            "voice": "alloy",
            "response_format": "wav",
        },
    )
    assert openai.status_code == 200, openai.text
    assert openai.content.startswith(b"RIFF")

    runtime = client.get("/api/runtime")
    assert runtime.status_code == 200
    assert runtime.json()["mode"] in runtime.json()["modes"]
    patched = client.patch("/api/runtime", json={"elastic_mode": "time_slice"})
    assert patched.status_code == 200
    assert patched.json()["mode"] == "time_slice"


def test_tts_worker_bridge_with_fake_indextts(tmp_path):
    """Exercise the real JSON-lines worker bridge without downloading weights."""
    repo = tmp_path / "index-tts"
    package = repo / "indextts"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "infer_v2_5.py").write_text(
        "\n".join(
            [
                "import math, wave",
                "class IndexTTS2:",
                "    def __init__(self, **kwargs):",
                "        pass",
                "    def infer(self, spk_audio_prompt, text, lang=None, output_path=None, duration_factor=1.0, verbose=False):",
                "        rate = 16000",
                "        duration = 0.35 * float(duration_factor or 1.0)",
                "        with wave.open(str(output_path), 'wb') as handle:",
                "            handle.setnchannels(1)",
                "            handle.setsampwidth(2)",
                "            handle.setframerate(rate)",
                "            frames = bytearray()",
                "            for i in range(int(rate * duration)):",
                "                value = int(10000 * math.sin(2 * math.pi * 440 * i / rate))",
                "                frames += value.to_bytes(2, 'little', signed=True)",
                "            handle.writeframes(bytes(frames))",
            ]
        ),
        encoding="utf-8",
    )
    config = AppConfig(
        data_dir=tmp_path / "data",
        mock_asr=True,
        demo_tts=False,
        indextts_home=str(repo),
        indextts_python=sys.executable,
        grpc_port=0,
        mrcp_port=0,
    )
    model_dir = config.tts_models_dir / "indextts-2.5"
    (model_dir / "qwen0.6bemo4-merge").mkdir(parents=True)
    for name in ("config.yaml", "gpt.pth", "codec.pth", "s2mel.pth"):
        (model_dir / name).write_bytes(b"x")
    (model_dir / "qwen0.6bemo4-merge" / "model.safetensors").write_bytes(b"x")

    app = create_app(config)
    with TestClient(app) as client:
        response = client.post(
            "/api/tts/synthesize",
            json={
                "text": "worker bridge",
                "model": "indextts-2.5",
                "voice": "default-en",
                "response_format": "wav",
                "speed": 1.0,
            },
        )
        assert response.status_code == 200, response.text
        assert response.content.startswith(b"RIFF")
        status = client.get("/api/tts/status").json()
        assert status["status"] == "ready"
        assert status["loaded_model"] == "indextts-2.5"
        assert client.get("/api/runtime").json()["loaded"][0]["kind"] == "tts"


def test_tts_voice_upload_and_delete(client):
    voice = client.post(
        "/api/tts/voices",
        files={"file": ("reference.wav", make_wav(0.4), "audio/wav")},
        data={"name": "测试音色", "language": "zh"},
    )
    assert voice.status_code == 201, voice.text
    voice_id = voice.json()["id"]
    assert any(item["id"] == voice_id for item in client.get("/api/tts/voices").json()["voices"])
    deleted = client.delete(f"/api/tts/voices/{voice_id}")
    assert deleted.status_code == 200
    assert not any(
        item["id"] == voice_id for item in client.get("/api/tts/voices").json()["voices"]
    )


def test_grpc_auth(tmp_path):
    grpc = pytest.importorskip("grpc")
    from aibox_api.proto import aibox_asr_pb2 as pb
    from aibox_api.proto import aibox_asr_pb2_grpc as pb_grpc

    port = free_tcp_port()
    app = make_app(tmp_path, grpc_port=port, api_token="secret-token")
    audio = make_wav(1.0)

    async def run():
        async with grpc.aio.insecure_channel(f"127.0.0.1:{port}") as channel:
            stub = pb_grpc.AsrServiceStub(channel)
            request = pb.TranscribeRequest(
                audio=audio,
                filename="grpc.wav",
                options=pb.TranscribeOptions(model="tiny", language="en"),
            )
            with pytest.raises(grpc.aio.AioRpcError) as exc:
                await stub.Transcribe(request, timeout=10)
            assert exc.value.code() == grpc.StatusCode.UNAUTHENTICATED
            result = await stub.Transcribe(
                request,
                timeout=30,
                metadata=(("authorization", "Bearer secret-token"),),
            )
            assert result.text

    import asyncio

    with TestClient(app):
        asyncio.run(run())


def test_grpc_tts(tmp_path):
    grpc = pytest.importorskip("grpc")
    from aibox_api.proto import aibox_tts_pb2 as pb
    from aibox_api.proto import aibox_tts_pb2_grpc as pb_grpc

    port = free_tcp_port()
    app = make_app(tmp_path, grpc_port=port)
    async def run():
        async with grpc.aio.insecure_channel(f"127.0.0.1:{port}") as channel:
            stub = pb_grpc.TtsServiceStub(channel)
            response = await stub.Synthesize(
                pb.SynthesizeRequest(
                    text="Hello from gRPC",
                    model="tts-1",
                    voice="default-en",
                    format="wav",
                ),
                timeout=30,
            )
            assert response.audio.startswith(b"RIFF")
            chunks = b""
            final = False
            async for chunk in stub.SynthesizeStream(
                pb.SynthesizeRequest(
                    text="Hello from gRPC stream",
                    model="tts-1",
                    voice="default-en",
                    format="wav",
                ),
                timeout=30,
            ):
                chunks += chunk.data
                final = final or chunk.final
            assert chunks.startswith(b"RIFF")
            assert final

    import asyncio

    with TestClient(app):
        asyncio.run(run())


def test_grpc_unary_and_stream(tmp_path):
    grpc = pytest.importorskip("grpc")
    from aibox_api.proto import aibox_asr_pb2 as pb
    from aibox_api.proto import aibox_asr_pb2_grpc as pb_grpc

    port = free_tcp_port()
    app = make_app(tmp_path, grpc_port=port)
    audio = make_wav(1.0)

    async def run():
        async with grpc.aio.insecure_channel(f"127.0.0.1:{port}") as channel:
            stub = pb_grpc.AsrServiceStub(channel)
            unary = await stub.Transcribe(
                pb.TranscribeRequest(
                    audio=audio,
                    filename="grpc.wav",
                    options=pb.TranscribeOptions(model="tiny", language="en"),
                ),
                timeout=30,
            )
            assert unary.text
            assert unary.transcription_id

            async def chunks():
                yield pb.AudioChunk(
                    start=pb.StartSession(
                        options=pb.TranscribeOptions(model="whisper-1", language="en"),
                        filename="stream.wav",
                        format="wav",
                    )
                )
                for index in range(0, len(audio), 8192):
                    yield pb.AudioChunk(data=audio[index : index + 8192])
                yield pb.AudioChunk(end=True)

            result = None
            async for event in stub.TranscribeStream(chunks(), timeout=30):
                if event.WhichOneof("event") == "result":
                    result = event.result
                if event.WhichOneof("event") == "error":
                    pytest.fail(event.error.message)
            assert result is not None
            assert result.text
            assert result.transcription_id

    import asyncio

    with TestClient(app):
        asyncio.run(run())
