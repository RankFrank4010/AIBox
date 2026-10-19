"""Shared ASR service layer for external transports.

The HTTP UI, OpenAI API, WebSocket, gRPC and MRCP adapters all use this gateway
so model selection, validation, job creation and result persistence behave the
same way on every transport.
"""

from __future__ import annotations

import shutil
import time
import uuid
from pathlib import Path
from typing import Any

from .asr import engine_available
from .catalog import asr_models, find_model_by_alias, get_model
from .config import AppConfig
from .jobs import TranscriptionJobs
from .models import list_installed
from .store import TranscriptionStore

AUDIO_EXTENSIONS = {
    ".wav",
    ".mp3",
    ".m4a",
    ".flac",
    ".ogg",
    ".oga",
    ".opus",
    ".webm",
    ".mp4",
    ".aac",
    ".wma",
    ".aiff",
    ".aif",
    ".caf",
}

MODEL_ALIASES = {
    "whisper-1": None,
    "gpt-4o-transcribe": None,
    "gpt-4o-mini-transcribe": None,
    "whisper-tiny": "tiny",
    "whisper-base": "base",
    "whisper-small": "small",
    "whisper-medium": "medium",
    "whisper-large-v3": "large-v3",
    "whisper-large-v3-turbo": "large-v3-turbo",
    "large-v3-turbo": "large-v3-turbo",
    "distil-whisper-large-v3": "distil-large-v3",
    "faster-whisper-tiny": "tiny",
    "faster-whisper-base": "base",
    "faster-whisper-small": "small",
    "faster-whisper-medium": "medium",
    "faster-whisper-large-v3": "large-v3",
}


class ExternalServiceError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int = 400,
        code: str = "invalid_request_error",
        error_type: str = "invalid_request_error",
        param: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code
        self.error_type = error_type
        self.param = param

    def as_openai(self) -> dict[str, Any]:
        return {
            "error": {
                "message": self.message,
                "type": self.error_type,
                "param": self.param,
                "code": self.code,
            }
        }


def normalize_filename(filename: str | None, default: str = "audio.wav") -> str:
    name = Path(filename or default).name.strip()
    return name or default


def normalize_options(
    config: AppConfig,
    values: dict[str, Any] | None = None,
) -> dict[str, Any]:
    settings = config.settings()
    source = values or {}
    language = str(source.get("language") or settings.get("language") or "auto")
    if language == "auto":
        language = "auto"
    task = str(source.get("task") or settings.get("task") or "transcribe")
    if task not in {"transcribe", "translate"}:
        task = "transcribe"
    try:
        beam_size = int(source.get("beam_size", settings.get("beam_size", 5)))
    except (TypeError, ValueError):
        beam_size = 5
    device = str(source.get("device") or settings.get("device") or "auto")
    if device not in {"auto", "cpu", "cuda", "npu", "metal"}:
        device = "auto"
    compute_type = str(source.get("compute_type") or settings.get("compute_type") or "auto")
    if compute_type not in {
        "auto",
        "int8",
        "int8_float16",
        "int8_float32",
        "float16",
        "float32",
        "bfloat16",
    }:
        compute_type = "auto"
    return {
        "language": language,
        "task": task,
        "beam_size": max(1, min(10, beam_size)),
        "vad_filter": bool(source.get("vad_filter", settings.get("vad_filter", True))),
        "word_timestamps": bool(
            source.get("word_timestamps", settings.get("word_timestamps", False))
        ),
        "device": device,
        "compute_type": compute_type,
    }


class ExternalAsrGateway:
    def __init__(
        self,
        config: AppConfig,
        store: TranscriptionStore,
        jobs: TranscriptionJobs,
    ) -> None:
        self.config = config
        self.store = store
        self.jobs = jobs

    # --------------------------------------------------------------- discovery
    def installed_models(self) -> list[dict[str, Any]]:
        return list_installed(self.config, "asr")

    def resolve_model(self, requested: str | None) -> dict[str, Any]:
        installed = {entry["id"]: entry for entry in self.installed_models()}
        if not installed:
            raise ExternalServiceError(
                "没有已安装的 Whisper 模型，请先在 AIBox 模型库下载模型。",
                status_code=409,
                code="no_model_installed",
                param="model",
            )

        raw = (requested or "").strip()
        if not raw or raw.lower() in {"auto", "default"}:
            return self._default_installed(installed)

        key = raw.lower()
        if key in installed:
            return installed[key]
        mapped = MODEL_ALIASES.get(key, key)
        if mapped is None:
            return self._default_installed(installed)
        if mapped.startswith("whisper-"):
            mapped = mapped[len("whisper-") :]
        if mapped.startswith("faster-whisper-"):
            mapped = mapped[len("faster-whisper-") :]

        if mapped in installed:
            return installed[mapped]
        spec = find_model_by_alias(mapped, "asr") or find_model_by_alias(mapped)
        if spec is not None:
            if spec.kind != "asr":
                raise ExternalServiceError(
                    f"{raw} 是 TTS 模型，不能用于语音识别。",
                    status_code=400,
                    code="model_kind_mismatch",
                    param="model",
                )
            if spec.id in installed:
                return installed[spec.id]
            raise ExternalServiceError(
                f"模型 {raw} 尚未安装，请先在 AIBox 模型库下载。",
                status_code=404,
                code="model_not_installed",
                param="model",
            )
        raise ExternalServiceError(
            f"未知模型 {raw}。可用模型：{', '.join(installed)}",
            status_code=404,
            code="model_not_found",
            param="model",
        )

    def _default_installed(self, installed: dict[str, dict[str, Any]]) -> dict[str, Any]:
        preferred = self.config.settings().get("default_model")
        if preferred and preferred in installed:
            return installed[preferred]
        for spec in asr_models():
            if spec.id in installed:
                return installed[spec.id]
        return next(iter(installed.values()))

    def model_list_for_openai(self) -> list[dict[str, Any]]:
        models = []
        ids = [
            "whisper-1",
            "tts-1",
            "tts-1-hd",
            "gpt-4o-mini-tts",
        ]
        ids += [entry["id"] for entry in list_installed(self.config)]
        seen: set[str] = set()
        for model_id in ids:
            if model_id in seen:
                continue
            seen.add(model_id)
            spec = get_model(model_id)
            models.append(
                {
                    "id": model_id,
                    "object": "model",
                    "created": 0,
                    "owned_by": "aibox",
                    "permission": [],
                    "root": model_id,
                    "parent": None,
                    "name": spec.name
                    if spec
                    else (
                        "AIBox IndexTTS alias"
                        if model_id in {"tts-1", "tts-1-hd", "gpt-4o-mini-tts"}
                        else "AIBox default Whisper model"
                    ),
                }
            )
        return models

    # ------------------------------------------------------------------ submit
    def submit(
        self,
        audio_source: Path,
        *,
        filename: str | None,
        model: str | None,
        options: dict[str, Any] | None = None,
        transport: str = "external",
    ) -> dict[str, Any]:
        if not (engine_available() or self.config.mock_asr):
            raise ExternalServiceError(
                "ASR 引擎未安装：请安装 faster-whisper 后重启 AIBox。",
                status_code=503,
                code="engine_unavailable",
            )
        if not audio_source.is_file() or audio_source.stat().st_size <= 0:
            raise ExternalServiceError(
                "音频文件为空或不存在。",
                status_code=400,
                code="empty_audio",
                param="file",
            )

        model_entry = self.resolve_model(model)
        model_id = str(model_entry["id"])
        suffix = audio_source.suffix.lower()
        if suffix not in AUDIO_EXTENSIONS:
            suffix = ".wav"

        job_id = f"ext_{uuid.uuid4().hex[:14]}"
        destination = self.config.uploads_dir / f"{job_id}{suffix}"
        try:
            if (
                audio_source.parent.resolve() == self.config.uploads_dir.resolve()
                and audio_source.name.startswith(".incoming_")
            ):
                audio_source.replace(destination)
            else:
                shutil.copyfile(audio_source, destination)
                audio_source.unlink(missing_ok=True)
        except OSError as exc:
            destination.unlink(missing_ok=True)
            raise ExternalServiceError(
                f"无法保存音频：{exc}", status_code=500, code="audio_storage_failed"
            ) from exc

        resolved = normalize_options(self.config, options)
        resolved["transport"] = transport
        record = self.store.create(
            id=job_id,
            filename=normalize_filename(filename, f"{transport}{suffix}"),
            audio_path=str(destination),
            audio_size=destination.stat().st_size,
            model_id=model_id,
            task=resolved["task"],
            language=resolved["language"],
            options=resolved,
        )
        self.jobs.submit(job_id, model_id, resolved)
        return record

    def wait(
        self,
        transcription_id: str,
        *,
        timeout: float = 1800.0,
        poll_interval: float = 0.15,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while True:
            record = self.store.get(transcription_id)
            if record is None:
                raise ExternalServiceError(
                    "转写任务不存在。", status_code=404, code="job_not_found"
                )
            if record["status"] == "completed":
                return record
            if record["status"] == "failed":
                raise ExternalServiceError(
                    record.get("error") or "转写失败。",
                    status_code=500,
                    code="transcription_failed",
                )
            if record["status"] in {"cancelled", "cancelling"}:
                raise ExternalServiceError(
                    "转写任务已取消。", status_code=409, code="cancelled"
                )
            if time.monotonic() >= deadline:
                self.jobs.cancel(transcription_id)
                raise ExternalServiceError(
                    "转写超时。", status_code=504, code="transcription_timeout"
                )
            time.sleep(poll_interval)

    def submit_and_wait(
        self,
        audio_source: Path,
        *,
        filename: str | None,
        model: str | None,
        options: dict[str, Any] | None = None,
        transport: str = "external",
        timeout: float = 1800.0,
    ) -> dict[str, Any]:
        record = self.submit(
            audio_source,
            filename=filename,
            model=model,
            options=options,
            transport=transport,
        )
        return self.wait(record["id"], timeout=timeout)
