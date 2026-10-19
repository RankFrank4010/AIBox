"""Translation providers: LibreTranslate/Argos, Index-Translate, Hunyuan MT2.

Translation is intentionally synchronous: most engines answer in a few seconds
and do not need model residency like ASR/TTS. LibreTranslate and Argos are
used directly; Index-Translate and Hunyuan Hy-MT2 use an OpenAI-compatible
``/chat/completions`` gateway by default so they can also be reached through
NewAPI or a self-hosted inference server.
"""

from __future__ import annotations

import shlex
import shutil
import subprocess
import time
from typing import Any

import httpx

from .config import AppConfig

LANGUAGES: tuple[dict[str, str], ...] = (
    {"code": "auto", "name": "自动检测"},
    {"code": "zh", "name": "中文"},
    {"code": "en", "name": "英语"},
    {"code": "ja", "name": "日语"},
    {"code": "ko", "name": "韩语"},
    {"code": "fr", "name": "法语"},
    {"code": "de", "name": "德语"},
    {"code": "es", "name": "西班牙语"},
    {"code": "ru", "name": "俄语"},
    {"code": "pt", "name": "葡萄牙语"},
    {"code": "it", "name": "意大利语"},
    {"code": "ar", "name": "阿拉伯语"},
    {"code": "th", "name": "泰语"},
    {"code": "vi", "name": "越南语"},
)

PROVIDERS: tuple[dict[str, Any], ...] = (
    {
        "id": "libre",
        "name": "LibreTranslate / Argos",
        "kind": "http",
        "model": "libretranslate",
        "description": "LibreTranslate HTTP API；也适用于 Argos Translate 的 HTTP 服务。",
    },
    {
        "id": "argos",
        "name": "Argos Translate",
        "kind": "command",
        "model": "argos-translate",
        "description": "本机 Argos Translate CLI，需安装 argos-translate 和语言包。",
    },
    {
        "id": "index",
        "name": "Index-Translate",
        "kind": "openai",
        "model": "Index-Translate",
        "description": "Index-Translate 的 OpenAI 兼容推理接口。",
    },
    {
        "id": "hunyuan",
        "name": "腾讯混元 Hy-MT2",
        "kind": "openai",
        "model": "hunyuan-mt2",
        "description": "腾讯混元翻译模型；可指向混元 OpenAI 兼容网关或 NewAPI。",
    },
    {
        "id": "openai",
        "name": "OpenAI 兼容翻译服务",
        "kind": "openai",
        "model": "gpt-4o-mini",
        "description": "任意支持 /v1/chat/completions 的翻译模型。",
    },
    {
        "id": "demo",
        "name": "演示翻译",
        "kind": "demo",
        "model": "demo",
        "description": "用于 UI 验证的占位翻译器，不调用外部模型。",
    },
)

LANGUAGE_NAMES = {item["code"]: item["name"] for item in LANGUAGES}
PROVIDER_IDS = {item["id"] for item in PROVIDERS}


class TranslationError(RuntimeError):
    pass


class TranslationService:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    # ------------------------------------------------------------------ status
    def _argos_available(self) -> bool:
        command = self.config.argos_command
        if not command:
            return False
        executable = shlex.split(command)[0] if command else ""
        return bool(shutil.which(executable))

    def _provider_available(self, provider: str) -> bool:
        if provider == "demo":
            return self.config.demo_translation
        if provider == "libre":
            return bool(self.config.libre_url)
        if provider == "argos":
            return self._argos_available()
        if provider == "index":
            return bool(self.config.index_url)
        if provider == "hunyuan":
            return bool(self.config.hunyuan_url)
        if provider == "openai":
            return bool(self.config.llm_base_url)
        return False

    def _provider_model(self, provider: str) -> str:
        if provider == "index":
            return self.config.index_model or "Index-Translate"
        if provider == "hunyuan":
            return self.config.hunyuan_model or "hunyuan-mt2"
        if provider == "openai":
            return self.config.llm_model or "gpt-4o-mini"
        return next(
            (str(item["model"]) for item in PROVIDERS if item["id"] == provider),
            provider,
        )

    def resolve_provider(self, requested: str | None = None) -> str:
        requested = (requested or self.config.settings().get("translation_provider") or "auto").strip()
        if requested in PROVIDER_IDS and requested != "auto":
            if not self._provider_available(requested):
                raise TranslationError(f"{self.provider_name(requested)} 尚未配置或不可用。")
            return requested
        if requested not in PROVIDER_IDS and requested != "auto":
            raise TranslationError(f"未知翻译服务：{requested}")
        for candidate in ("index", "hunyuan", "libre", "argos", "openai", "demo"):
            if self._provider_available(candidate):
                return candidate
        raise TranslationError(
            "没有可用的翻译服务；请在设置中配置 LibreTranslate、Index-Translate、"
            "混元或 Argos，或启用演示翻译。"
        )

    @staticmethod
    def provider_name(provider: str) -> str:
        return next(
            (str(item["name"]) for item in PROVIDERS if item["id"] == provider),
            provider,
        )

    def status(self) -> dict[str, Any]:
        providers = [
            {
                **item,
                "available": self._provider_available(str(item["id"])),
                "model": self._provider_model(str(item["id"])),
            }
            for item in PROVIDERS
        ]
        try:
            resolved = self.resolve_provider()
        except TranslationError:
            resolved = None
        return {
            "default_provider": str(
                self.config.settings().get("translation_provider") or "auto"
            ),
            "resolved_provider": resolved,
            "providers": providers,
            "languages": list(LANGUAGES),
            "demo": self.config.demo_translation,
        }

    # ----------------------------------------------------------------- translate
    def translate(
        self,
        *,
        text: str,
        source: str,
        target: str,
        provider: str | None = None,
        model: str | None = None,
    ) -> dict[str, Any]:
        text = text.strip()
        if not text:
            raise TranslationError("待翻译文本不能为空。")
        if len(text) > 20000:
            raise TranslationError("单次翻译最多 20000 字符。")
        source = (source or "auto").strip()
        target = (target or "zh").strip()
        if source not in LANGUAGE_NAMES:
            raise TranslationError(f"不支持的源语言：{source}")
        if target not in LANGUAGE_NAMES or target == "auto":
            raise TranslationError(f"不支持的目标语言：{target}")
        if source != "auto" and source == target:
            raise TranslationError("源语言和目标语言不能相同。")
        selected = self.resolve_provider(provider)
        chosen_model = (model or "").strip() or self._provider_model(selected)
        started = time.monotonic()
        detected = source if source != "auto" else None
        if selected == "demo":
            translated = f"[演示翻译 {source}→{target}] {text}"
        elif selected == "libre":
            translated, detected = self._libre(text, source, target)
        elif selected == "argos":
            translated = self._argos(text, source, target)
        else:
            translated = self._openai_compatible(
                text, source, target, selected, chosen_model
            )
        translated = translated.strip()
        if not translated:
            raise TranslationError("翻译服务返回了空结果。")
        return {
            "text": text,
            "translated": translated,
            "source": source,
            "target": target,
            "provider": selected,
            "provider_name": self.provider_name(selected),
            "model": chosen_model,
            "detected_language": detected,
            "latency_ms": int((time.monotonic() - started) * 1000),
        }

    def _libre(self, text: str, source: str, target: str) -> tuple[str, str | None]:
        payload: dict[str, Any] = {
            "q": text,
            "source": source or "auto",
            "target": target,
            "format": "text",
        }
        if self.config.libre_api_key:
            payload["api_key"] = self.config.libre_api_key
        try:
            response = httpx.post(
                f"{self.config.libre_url.rstrip('/')}/translate",
                json=payload,
                timeout=120,
            )
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise TranslationError(f"LibreTranslate 调用失败：{exc}") from exc
        translated = body.get("translatedText") or body.get("translated_text")
        if not translated:
            raise TranslationError("LibreTranslate 没有返回 translatedText。")
        detected = body.get("detectedLanguage")
        if isinstance(detected, dict):
            detected = detected.get("language")
        return str(translated), str(detected) if detected else None

    def _argos(self, text: str, source: str, target: str) -> str:
        if source == "auto":
            raise TranslationError("Argos Translate 需要明确指定源语言。")
        command = shlex.split(self.config.argos_command)
        if not command:
            raise TranslationError("AIBOX_ARGOS_COMMAND 为空。")
        try:
            completed = subprocess.run(
                [
                    *command,
                    "--from-lang",
                    source,
                    "--to-lang",
                    target,
                    text,
                ],
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise TranslationError(f"Argos Translate 启动失败：{exc}") from exc
        if completed.returncode != 0:
            error = (completed.stderr or completed.stdout).strip()
            raise TranslationError(f"Argos Translate 失败：{error[-1000:]}")
        output = (completed.stdout or "").strip()
        if not output:
            raise TranslationError("Argos Translate 没有输出译文。")
        return output

    def _openai_compatible(
        self,
        text: str,
        source: str,
        target: str,
        provider: str,
        model: str,
    ) -> str:
        if provider == "index":
            base = self.config.index_url
            api_key = self.config.index_api_key
        elif provider == "hunyuan":
            base = self.config.hunyuan_url
            api_key = self.config.hunyuan_api_key
        else:
            base = self.config.llm_base_url
            api_key = self.config.llm_api_key
        if not base:
            raise TranslationError(f"{self.provider_name(provider)} 尚未配置 Base URL。")
        normalized = base.rstrip("/")
        endpoint = (
            f"{normalized}/chat/completions"
            if normalized.endswith("/v1")
            else f"{normalized}/v1/chat/completions"
        )
        source_name = LANGUAGE_NAMES.get(source, source)
        target_name = LANGUAGE_NAMES.get(target, target)
        system = (
            "You are a precise professional translator. "
            f"Translate from {source_name} to {target_name}. "
            "Return only the translation, with no explanations, labels or markdown."
        )
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        payload = {
            "model": model,
            "temperature": 0.2,
            "max_tokens": 4096,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": text},
            ],
        }
        try:
            response = httpx.post(endpoint, headers=headers, json=payload, timeout=120)
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise TranslationError(f"{self.provider_name(provider)} 调用失败：{exc}") from exc
        choices = body.get("choices")
        if not isinstance(choices, list) or not choices:
            raise TranslationError(f"{self.provider_name(provider)} 返回格式不兼容。")
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, list):
            content = "".join(
                str(part.get("text") or "")
                for part in content
                if isinstance(part, dict)
            )
        if not isinstance(content, str) or not content.strip():
            raise TranslationError(f"{self.provider_name(provider)} 没有返回译文。")
        return content
