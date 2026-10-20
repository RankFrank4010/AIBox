"""AIBOX Unified Protocol Python SDK.

The SDK wraps AIBox's native ``/api`` surface and OpenAI-compatible ``/v1``
surface, normalizes errors and job polling, and never assumes localhost.
"""

from __future__ import annotations

import json
import mimetypes
import os
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx

PROTOCOL_VERSION = "1.0"
TERMINAL_STATES = {"completed", "failed", "cancelled"}
JOB_PATHS = {
    "transcription": "/api/transcriptions/{id}",
    "image": "/api/images/generations/{id}",
    "video": "/api/videos/{id}",
    "separation": "/api/separations/{id}",
    "training": "/api/training/jobs/{id}",
}
CANCEL_PATHS = {
    "transcription": "/api/transcriptions/{id}/cancel",
    "image": "/api/images/generations/{id}/cancel",
    "video": "/api/videos/{id}/cancel",
    "separation": "/api/separations/{id}/cancel",
    "training": "/api/training/jobs/{id}/cancel",
}


class AIBOXError(RuntimeError):
    """Base SDK error."""


class AIBOXAPIError(AIBOXError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        code: str | None = None,
        details: Any = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.details = details
        self.request_id = request_id


class AIBOXTimeout(AIBOXError):
    """A job did not reach a terminal state before the deadline."""


def _mime(path: Path) -> str:
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def _error_payload(response: httpx.Response) -> tuple[str, str | None, Any]:
    try:
        body = response.json()
    except ValueError:
        return response.text.strip() or response.reason_phrase, None, response.text
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            return (
                str(error.get("message") or error.get("type") or response.reason_phrase),
                str(error.get("code")) if error.get("code") else None,
                body,
            )
        detail = body.get("detail")
        if isinstance(detail, str):
            return detail, None, body
        if isinstance(detail, list):
            return json.dumps(detail, ensure_ascii=False), None, body
    return response.reason_phrase, None, body


class AIBOXClient:
    """Synchronous client for the AIBOX Unified Protocol 1.0."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8765",
        *,
        api_key: str | None = None,
        timeout: float = 60.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or os.getenv("AIBOX_API_TOKEN")
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=timeout,
            transport=transport,
        )

    # ------------------------------------------------------------------ plumbing
    def _headers(self, idempotency_key: str | None = None) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "X-AIBox-Protocol": PROTOCOL_VERSION,
            "X-AIBox-Client": "aibox-python/1.0",
            "X-Request-ID": uuid.uuid4().hex,
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        return headers

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any = None,
        data: Any = None,
        files: Any = None,
        params: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
        raw: bool = False,
    ) -> Any:
        response = self._client.request(
            method,
            path,
            json=json_body,
            data=data,
            files=files,
            params=params,
            headers=self._headers(idempotency_key),
        )
        if response.status_code >= 400:
            message, code, details = _error_payload(response)
            raise AIBOXAPIError(
                message,
                status_code=response.status_code,
                code=code,
                details=details,
                request_id=response.headers.get("X-Request-ID"),
            )
        if raw:
            return response.content
        if response.content:
            try:
                return response.json()
            except ValueError:
                return response.text
        return None

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> AIBOXClient:  # noqa: PYI034
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    # ------------------------------------------------------------------ discovery
    def protocol(self) -> dict[str, Any]:
        return self.request("GET", "/api/protocol")

    def health(self) -> dict[str, Any]:
        return self.request("GET", "/api/health")

    def models(self) -> list[dict[str, Any]]:
        payload = self.request("GET", "/v1/models")
        return list(payload.get("data") or []) if isinstance(payload, dict) else []

    # ------------------------------------------------------------------ chat
    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        stream: bool = False,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> Any:
        payload: dict[str, Any] = {"messages": messages, "stream": stream}
        if model:
            payload["model"] = model
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if not stream:
            return self.request("POST", "/v1/chat/completions", json_body=payload)
        return self._stream_chat(payload)

    def _stream_chat(self, payload: dict[str, Any]) -> Iterator[dict[str, Any]]:
        with self._client.stream(
            "POST",
            "/v1/chat/completions",
            json=payload,
            headers=self._headers(),
        ) as response:
            if response.status_code >= 400:
                response.read()
                message, code, details = _error_payload(response)
                raise AIBOXAPIError(
                    message,
                    status_code=response.status_code,
                    code=code,
                    details=details,
                    request_id=response.headers.get("X-Request-ID"),
                )
            for line in response.iter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if not data or data == "[DONE]":
                    if data == "[DONE]":
                        break
                    continue
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                if isinstance(chunk, dict) and "error" in chunk:
                    error = chunk.get("error") or {}
                    raise AIBOXAPIError(
                        str(error.get("message") or "stream error"),
                        status_code=response.status_code,
                        code=error.get("code"),
                        details=chunk,
                    )
                yield chunk

    # ------------------------------------------------------------------ audio
    def transcribe(
        self,
        audio: str | Path | bytes,
        *,
        filename: str = "audio.wav",
        model: str = "whisper-1",
        language: str | None = None,
        prompt: str | None = None,
        response_format: str = "json",
    ) -> Any:
        if isinstance(audio, (str, Path)):
            path = Path(audio)
            content = path.read_bytes()
            filename = path.name
            mime = _mime(path)
        else:
            content = audio
            mime = "application/octet-stream"
        data = {"model": model, "response_format": response_format}
        if language:
            data["language"] = language
        if prompt:
            data["prompt"] = prompt
        return self.request(
            "POST",
            "/v1/audio/transcriptions",
            data=data,
            files={"file": (filename, content, mime)},
        )

    def speech(
        self,
        text: str,
        *,
        voice: str = "default",
        model: str = "tts-1",
        response_format: str = "wav",
        save_to: str | Path | None = None,
    ) -> bytes:
        response = self._client.post(
            "/v1/audio/speech",
            json={
                "input": text,
                "voice": voice,
                "model": model,
                "response_format": response_format,
            },
            headers=self._headers(),
        )
        if response.status_code >= 400:
            message, code, details = _error_payload(response)
            raise AIBOXAPIError(
                message,
                status_code=response.status_code,
                code=code,
                details=details,
                request_id=response.headers.get("X-Request-ID"),
            )
        content = response.content
        if save_to:
            Path(save_to).write_bytes(content)
        return content

    # ------------------------------------------------------------------ text / image
    def translate(
        self,
        text: str,
        *,
        source: str = "auto",
        target: str = "zh",
        provider: str = "auto",
        model: str | None = None,
    ) -> dict[str, Any]:
        payload = {
            "text": text,
            "source": source,
            "target": target,
            "provider": provider,
        }
        if model:
            payload["model"] = model
        return self.request("POST", "/api/translations", json_body=payload)[
            "translation"
        ]

    def ocr(
        self,
        image: str | Path | bytes,
        *,
        filename: str = "image.png",
        provider: str = "auto",
        model: str | None = None,
        language: str = "auto",
    ) -> dict[str, Any]:
        if isinstance(image, (str, Path)):
            path = Path(image)
            content = path.read_bytes()
            filename = path.name
            mime = _mime(path)
        else:
            content = image
            mime = "application/octet-stream"
        data: dict[str, Any] = {"provider": provider, "language": language}
        if model:
            data["model"] = model
        return self.request(
            "POST",
            "/api/ocr",
            data=data,
            files={"file": (filename, content, mime)},
        )["record"]

    # ------------------------------------------------------------------ jobs
    def create_image(self, **payload: Any) -> dict[str, Any]:
        return self.request("POST", "/api/images/generations", json_body=payload)

    def create_video(self, **payload: Any) -> dict[str, Any]:
        return self.request("POST", "/api/videos", json_body=payload)

    def create_separation(
        self,
        audio: str | Path,
        *,
        mode: str = "instrumental",
        model: str | None = None,
    ) -> dict[str, Any]:
        path = Path(audio)
        data: dict[str, Any] = {"mode": mode}
        if model:
            data["model"] = model
        return self.request(
            "POST",
            "/api/separations",
            data=data,
            files={"file": (path.name, path.read_bytes(), _mime(path))},
        )

    def create_training(self, **payload: Any) -> dict[str, Any]:
        return self.request("POST", "/api/training/jobs", json_body=payload)

    def job(self, kind: str, job_id: str) -> dict[str, Any]:
        template = JOB_PATHS.get(kind)
        if not template:
            raise ValueError(f"unknown job kind: {kind}")
        return self.request("GET", template.format(id=job_id))

    def cancel_job(self, kind: str, job_id: str) -> dict[str, Any]:
        template = CANCEL_PATHS.get(kind)
        if not template:
            raise ValueError(f"unknown job kind: {kind}")
        return self.request("POST", template.format(id=job_id))

    def wait_job(
        self,
        kind: str,
        job_id: str,
        *,
        timeout: float = 600,
        interval: float = 1.0,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while True:
            job = self.job(kind, job_id)
            if str(job.get("status")) in TERMINAL_STATES:
                return job
            if time.monotonic() >= deadline:
                raise AIBOXTimeout(
                    f"{kind} job {job_id} did not finish within {timeout}s"
                )
            time.sleep(interval)
