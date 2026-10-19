"""Translation API and provider tests."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from aibox_api.config import AppConfig
from aibox_api.main import create_app
from aibox_api.translation import TranslationService


def make_client(tmp_path: Path) -> TestClient:
    config = AppConfig(
        data_dir=tmp_path / "data",
        mock_asr=True,
        demo_translation=True,
    )
    return TestClient(create_app(config))


def test_demo_translation_history_and_delete(tmp_path):
    client = make_client(tmp_path)
    status = client.get("/api/translations/status")
    assert status.status_code == 200
    assert status.json()["resolved_provider"] == "demo"

    response = client.post(
        "/api/translations",
        json={
            "text": "Hello AIBox",
            "source": "en",
            "target": "zh",
            "provider": "demo",
        },
    )
    assert response.status_code == 200
    record = response.json()["translation"]
    assert record["translated"].startswith("[演示翻译")
    assert record["provider"] == "demo"
    assert record["id"].startswith("tr_")

    history = client.get("/api/translations").json()["translations"]
    assert len(history) == 1
    assert history[0]["text"] == "Hello AIBox"

    deleted = client.delete(f"/api/translations/{record['id']}")
    assert deleted.status_code == 200
    assert client.get("/api/translations").json()["translations"] == []


def test_translation_validation(tmp_path):
    client = make_client(tmp_path)
    response = client.post(
        "/api/translations",
        json={"text": "hello", "source": "en", "target": "en", "provider": "demo"},
    )
    assert response.status_code == 400
    assert "不能相同" in response.json()["detail"]

    repeated = client.post(
        "/api/translations",
        json={"text": "", "source": "en", "target": "zh", "provider": "demo"},
    )
    assert repeated.status_code == 422


def test_libre_provider_payload(tmp_path, monkeypatch):
    config = AppConfig(
        data_dir=tmp_path / "data",
        mock_asr=True,
        libre_url="http://libre.test",
        libre_api_key="secret",
    )
    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "translatedText": "你好",
                "detectedLanguage": {"language": "en"},
            }

    def fake_post(url, json, timeout):
        captured.update({"url": url, "json": json, "timeout": timeout})
        return Response()

    monkeypatch.setattr("aibox_api.translation.httpx.post", fake_post)
    result = TranslationService(config).translate(
        text="Hello",
        source="en",
        target="zh",
        provider="libre",
    )
    assert result["translated"] == "你好"
    assert result["detected_language"] == "en"
    assert captured["url"] == "http://libre.test/translate"
    assert captured["json"]["api_key"] == "secret"
    assert captured["json"]["target"] == "zh"


def test_index_openai_compatible_payload(tmp_path, monkeypatch):
    config = AppConfig(
        data_dir=tmp_path / "data",
        mock_asr=True,
        index_url="http://index.test/v1",
        index_api_key="index-secret",
        index_model="Index-Translate",
    )
    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "你好，世界"}}]}

    def fake_post(url, headers, json, timeout):
        captured.update(
            {"url": url, "headers": headers, "json": json, "timeout": timeout}
        )
        return Response()

    monkeypatch.setattr("aibox_api.translation.httpx.post", fake_post)
    result = TranslationService(config).translate(
        text="Hello world",
        source="en",
        target="zh",
        provider="index",
    )
    assert result["translated"] == "你好，世界"
    assert captured["url"] == "http://index.test/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer index-secret"
    assert captured["json"]["model"] == "Index-Translate"
    assert "Translate from" in captured["json"]["messages"][0]["content"]
