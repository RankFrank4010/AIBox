"""OCR providers: GLM-OCR, OpenAI-compatible vision, Tesseract and demo."""

from __future__ import annotations

import base64
import mimetypes
import shlex
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import httpx
from PIL import Image

from .config import AppConfig

LANGUAGES: tuple[dict[str, str], ...] = (
    {"code": "auto", "name": "自动"},
    {"code": "zh", "name": "中文"},
    {"code": "en", "name": "英语"},
    {"code": "ja", "name": "日语"},
    {"code": "ko", "name": "韩语"},
    {"code": "fr", "name": "法语"},
    {"code": "de", "name": "德语"},
    {"code": "es", "name": "西班牙语"},
    {"code": "ru", "name": "俄语"},
)

PROVIDERS: tuple[dict[str, Any], ...] = (
    {
        "id": "glm",
        "name": "GLM-OCR",
        "kind": "vision",
        "model": "glm-ocr",
        "description": "智谱 GLM-OCR / 视觉模型 OpenAI 兼容接口。",
    },
    {
        "id": "openai",
        "name": "OpenAI 兼容视觉",
        "kind": "vision",
        "model": "gpt-4o-mini",
        "description": "任意支持图片输入的 /v1/chat/completions 服务。",
    },
    {
        "id": "tesseract",
        "name": "Tesseract",
        "kind": "command",
        "model": "tesseract",
        "description": "本机 Tesseract CLI，需安装对应语言包。",
    },
    {
        "id": "demo",
        "name": "演示 OCR",
        "kind": "demo",
        "model": "demo",
        "description": "用于 UI 验证的占位 OCR。",
    },
)

PROVIDER_IDS = {item["id"] for item in PROVIDERS}
LANGUAGE_NAMES = {item["code"]: item["name"] for item in LANGUAGES}
TESSERACT_LANGS = {
    "auto": "eng",
    "zh": "chi_sim+eng",
    "en": "eng",
    "ja": "jpn",
    "ko": "kor",
    "fr": "fra",
    "de": "deu",
    "es": "spa",
    "ru": "rus",
}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}


class OcrError(RuntimeError):
    pass


class OcrService:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    # ------------------------------------------------------------------ status
    def _tesseract_available(self) -> bool:
        command = shlex.split(self.config.tesseract_command)
        return bool(command and shutil.which(command[0]))

    def _available(self, provider: str) -> bool:
        if provider == "glm":
            return bool(self.config.glm_api_key)
        if provider == "openai":
            return bool(self.config.ocr_openai_url)
        if provider == "tesseract":
            return self._tesseract_available()
        if provider == "demo":
            return self.config.demo_ocr
        return False

    def _model(self, provider: str) -> str:
        if provider == "glm":
            return self.config.glm_ocr_model or "glm-ocr"
        if provider == "openai":
            return self.config.ocr_openai_model or "gpt-4o-mini"
        return next(
            (str(item["model"]) for item in PROVIDERS if item["id"] == provider),
            provider,
        )

    def _configured_provider(self) -> str:
        configured = str(self.config.settings().get("ocr_provider") or "auto")
        if configured == "auto" and self.config.ocr_provider != "auto":
            return self.config.ocr_provider
        return configured

    def resolve_provider(self, requested: str | None = None) -> str:
        requested = (requested or self._configured_provider() or "auto").strip()
        if requested in PROVIDER_IDS and requested != "auto":
            if not self._available(requested):
                raise OcrError(f"{self.provider_name(requested)} 尚未配置或不可用。")
            return requested
        if requested not in PROVIDER_IDS and requested != "auto":
            raise OcrError(f"未知 OCR 服务：{requested}")
        for candidate in ("glm", "openai", "tesseract", "demo"):
            if self._available(candidate):
                return candidate
        raise OcrError(
            "没有可用的 OCR 服务；请配置 GLM-OCR、OpenAI 兼容视觉或 Tesseract，"
            "或启用演示 OCR。"
        )

    @staticmethod
    def provider_name(provider: str) -> str:
        return next(
            (str(item["name"]) for item in PROVIDERS if item["id"] == provider),
            provider,
        )

    def status(self) -> dict[str, Any]:
        providers = [
            {**item, "available": self._available(str(item["id"]))}
            for item in PROVIDERS
        ]
        try:
            resolved = self.resolve_provider()
        except OcrError:
            resolved = None
        return {
            "default_provider": self._configured_provider(),
            "resolved_provider": resolved,
            "providers": providers,
            "languages": list(LANGUAGES),
            "demo": self.config.demo_ocr,
        }

    # ----------------------------------------------------------------- recognize
    def recognize(
        self,
        *,
        image_path: Path,
        provider: str | None = None,
        model: str | None = None,
        language: str = "auto",
    ) -> dict[str, Any]:
        if not image_path.is_file() or image_path.stat().st_size == 0:
            raise OcrError("图片文件不存在或为空。")
        if image_path.stat().st_size > 20 * 1024 * 1024:
            raise OcrError("图片不能超过 20 MB。")
        if image_path.suffix.lower() not in IMAGE_SUFFIXES:
            raise OcrError("仅支持 PNG / JPEG / WebP / BMP / TIFF 图片。")
        try:
            with Image.open(image_path) as image:
                image.verify()
        except Exception as exc:  # noqa: BLE001
            raise OcrError(f"无法读取图片：{exc}") from exc
        language = (language or "auto").strip()
        if language not in LANGUAGE_NAMES:
            raise OcrError(f"不支持的 OCR 语言：{language}")
        selected = self.resolve_provider(provider)
        chosen_model = (model or "").strip() or self._model(selected)
        started = time.monotonic()
        if selected == "demo":
            text = "[演示OCR] 已接收图片；配置 GLM-OCR / OpenAI 视觉 / Tesseract 后执行真实识别。"
        elif selected == "tesseract":
            text = self._tesseract(image_path, language)
        else:
            text = self._vision(image_path, selected, chosen_model, language)
        text = text.strip()
        if not text:
            raise OcrError("OCR 服务返回了空结果。")
        return {
            "text": text,
            "provider": selected,
            "provider_name": self.provider_name(selected),
            "model": chosen_model,
            "language": language,
            "latency_ms": int((time.monotonic() - started) * 1000),
        }

    def _vision(
        self,
        image_path: Path,
        provider: str,
        model: str,
        language: str,
    ) -> str:
        if provider == "glm":
            base = self.config.glm_base_url
            api_key = self.config.glm_api_key
        else:
            base = self.config.ocr_openai_url
            api_key = self.config.ocr_openai_api_key
        if not base:
            raise OcrError(f"{self.provider_name(provider)} 尚未配置 Base URL。")
        normalized = base.rstrip("/")
        endpoint = (
            f"{normalized}/chat/completions"
            if normalized.endswith(("/v1", "/v4"))
            else f"{normalized}/v1/chat/completions"
        )
        encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
        mime = mimetypes.guess_type(image_path.name)[0] or "image/png"
        language_name = LANGUAGE_NAMES.get(language, language)
        prompt = (
            "识别图片中的所有文字，保持阅读顺序和原有换行。"
            f"主要语言：{language_name}。只返回识别出的文字，不要解释。"
        )
        payload = {
            "model": model,
            "temperature": 0.1,
            "max_tokens": 4096,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime};base64,{encoded}"},
                        },
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        }
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        try:
            response = httpx.post(endpoint, headers=headers, json=payload, timeout=180)
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise OcrError(f"{self.provider_name(provider)} 调用失败：{exc}") from exc
        choices = body.get("choices")
        if not isinstance(choices, list) or not choices:
            raise OcrError(f"{self.provider_name(provider)} 返回格式不兼容。")
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, list):
            content = "".join(
                str(part.get("text") or "")
                for part in content
                if isinstance(part, dict)
            )
        if not isinstance(content, str) or not content.strip():
            raise OcrError(f"{self.provider_name(provider)} 没有返回文字。")
        return content

    def _tesseract(self, image_path: Path, language: str) -> str:
        command = shlex.split(self.config.tesseract_command)
        if not command:
            raise OcrError("AIBOX_TESSERACT_COMMAND 为空。")
        tesseract_lang = TESSERACT_LANGS.get(language, "eng")
        try:
            completed = subprocess.run(
                [*command, str(image_path), "stdout", "-l", tesseract_lang],
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise OcrError(f"Tesseract 启动失败：{exc}") from exc
        if completed.returncode != 0:
            error = (completed.stderr or completed.stdout).strip()
            raise OcrError(f"Tesseract 失败：{error[-1000:]}")
        return completed.stdout or ""
