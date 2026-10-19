"""OCR API and provider tests."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from aibox_api.config import AppConfig
from aibox_api.main import create_app
from aibox_api.ocr import OcrService


def make_client(tmp_path: Path) -> TestClient:
    config = AppConfig(
        data_dir=tmp_path / "data",
        mock_asr=True,
        demo_ocr=True,
    )
    return TestClient(create_app(config))


def png_bytes(text: str = "AIBox OCR") -> bytes:
    image = Image.new("RGB", (420, 120), "white")
    ImageDraw.Draw(image).text((20, 40), text, fill="black")
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def test_demo_ocr_history_image_and_delete(tmp_path):
    client = make_client(tmp_path)
    status = client.get("/api/ocr/status")
    assert status.status_code == 200
    assert status.json()["resolved_provider"] == "demo"

    response = client.post(
        "/api/ocr",
        files={"file": ("sample.png", png_bytes(), "image/png")},
        data={"provider": "demo", "language": "en"},
    )
    assert response.status_code == 200
    record = response.json()["record"]
    assert record["text"].startswith("[演示OCR]")
    assert record["provider"] == "demo"
    assert record["image_url"].endswith(record["id"])

    image = client.get(record["image_url"])
    assert image.status_code == 200
    assert image.headers["content-type"].startswith("image/")

    history = client.get("/api/ocr").json()["records"]
    assert len(history) == 1
    deleted = client.delete(f"/api/ocr/{record['id']}")
    assert deleted.status_code == 200
    assert client.get("/api/ocr").json()["records"] == []
    assert client.get(record["image_url"]).status_code == 404


def test_ocr_rejects_non_image(tmp_path):
    client = make_client(tmp_path)
    response = client.post(
        "/api/ocr",
        files={"file": ("notes.txt", b"hello", "text/plain")},
        data={"provider": "demo"},
    )
    assert response.status_code == 400
    assert "图片" in response.json()["detail"]


def test_glm_vision_payload(tmp_path, monkeypatch):
    image_path = tmp_path / "sample.png"
    image_path.write_bytes(png_bytes())
    config = AppConfig(
        data_dir=tmp_path / "data",
        mock_asr=True,
        glm_api_key="glm-secret",
        glm_base_url="https://open.bigmodel.cn/api/paas/v4",
        glm_ocr_model="glm-ocr",
    )
    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "识别结果"}}]}

    def fake_post(url, headers, json, timeout):
        captured.update(
            {"url": url, "headers": headers, "json": json, "timeout": timeout}
        )
        return Response()

    monkeypatch.setattr("aibox_api.ocr.httpx.post", fake_post)
    result = OcrService(config).recognize(
        image_path=image_path,
        provider="glm",
        language="zh",
    )
    assert result["text"] == "识别结果"
    assert captured["url"].endswith("/chat/completions")
    assert captured["headers"]["Authorization"] == "Bearer glm-secret"
    assert captured["json"]["model"] == "glm-ocr"
    content = captured["json"]["messages"][0]["content"]
    assert content[0]["type"] == "image_url"
    assert content[0]["image_url"]["url"].startswith("data:image/png;base64,")
