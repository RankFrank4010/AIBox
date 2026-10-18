"""Execution helpers for declarative community adapters."""

from __future__ import annotations

import json
import mimetypes
import os
import shlex
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from .models import utc_now


class AdapterExecutionError(RuntimeError):
    pass


class _SafeValues(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def _expand(value: Any, values: dict[str, Any]) -> str:
    return str(value).format_map(_SafeValues(values))


def _auth_headers(adapter: dict[str, Any]) -> dict[str, str]:
    env_name = adapter.get("api_key_env")
    if not env_name:
        return {}
    key = os.getenv(str(env_name))
    if not key:
        raise AdapterExecutionError(f"缺少环境变量 {env_name}")
    return {"Authorization": f"Bearer {key}"}


def _endpoint(adapter: dict[str, Any], default_path: str) -> str:
    if adapter.get("path"):
        path = str(adapter["path"])
        if path.startswith("http://") or path.startswith("https://"):
            return path
        return str(adapter["base_url"]).rstrip("/") + "/" + path.lstrip("/")
    base = str(adapter["base_url"]).rstrip("/")
    if base.endswith(default_path):
        return base
    return base + default_path


def openai_asr(
    adapter: dict[str, Any],
    *,
    audio_path: Path,
    options: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    endpoint = _endpoint(adapter, "/audio/transcriptions")
    headers = _auth_headers(adapter)
    data = {
        "model": str(adapter.get("model") or "whisper-1"),
        "response_format": "verbose_json",
    }
    language = str(options.get("language") or "auto")
    if language and language != "auto":
        data["language"] = language
    task = str(options.get("task") or "transcribe")
    data["task"] = "translate" if task == "translate" else "transcribe"
    mime = mimetypes.guess_type(audio_path.name)[0] or "application/octet-stream"
    try:
        with audio_path.open("rb") as handle:
            files = {"file": (audio_path.name, handle, mime)}
            with httpx.Client(timeout=timeout) as client:
                response = client.post(endpoint, data=data, files=files, headers=headers)
    except httpx.HTTPError as exc:
        raise AdapterExecutionError(f"OpenAI ASR 适配器请求失败：{exc}") from exc
    if response.status_code >= 400:
        raise AdapterExecutionError(
            f"OpenAI ASR 适配器返回 {response.status_code}：{response.text[:500]}"
        )
    try:
        payload = response.json()
    except ValueError:
        payload = {"text": response.text}
    return normalise_asr_payload(
        payload,
        audio_path=audio_path,
        engine="community:openai-http",
        device="external",
        compute_type="http",
    )


def openai_tts(
    adapter: dict[str, Any],
    *,
    text: str,
    voice: str | None,
    speed: float,
    output_path: Path,
    timeout: float,
) -> Path:
    endpoint = _endpoint(adapter, "/audio/speech")
    headers = _auth_headers(adapter)
    selected_voice = voice
    openai_aliases = {"alloy", "echo", "fable", "onyx", "nova", "shimmer"}
    if (not selected_voice or selected_voice.lower() in openai_aliases) and adapter.get("voice"):
        selected_voice = str(adapter["voice"])
    payload = {
        "model": str(adapter.get("model") or "tts-1"),
        "input": text,
        "voice": selected_voice or "alloy",
        "response_format": "wav",
        "speed": speed,
    }
    payload.update(adapter.get("extra_body") or {})
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.post(endpoint, json=payload, headers=headers)
    except httpx.HTTPError as exc:
        raise AdapterExecutionError(f"OpenAI TTS 适配器请求失败：{exc}") from exc
    if response.status_code >= 400:
        raise AdapterExecutionError(
            f"OpenAI TTS 适配器返回 {response.status_code}：{response.text[:500]}"
        )
    if not response.content:
        raise AdapterExecutionError("OpenAI TTS 适配器返回空音频")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(response.content)
    return output_path


def command_asr(
    adapter: dict[str, Any],
    *,
    audio_path: Path,
    model_dir: Path,
    options: dict[str, Any],
    timeout: float,
    cancel_check: Callable[[], bool],
) -> dict[str, Any]:
    output = model_dir / f".aibox-adapter-{utc_now().replace(':', '-')}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    values = {
        "audio": str(audio_path),
        "model_dir": str(adapter.get("model_dir") or model_dir),
        "output": str(output),
        "language": str(options.get("language") or "auto"),
        "task": str(options.get("task") or "transcribe"),
        "filename": audio_path.name,
    }
    stdout, stderr, _ = _run_command(adapter, values, timeout, cancel_check)
    if output.is_file():
        raw = output.read_text(encoding="utf-8", errors="replace")
        output.unlink(missing_ok=True)
    else:
        raw = stdout
    mode = str(adapter.get("output") or "json").lower()
    if mode == "text":
        payload: dict[str, Any] = {"text": raw.strip()}
    else:
        try:
            parsed = json.loads(raw)
            payload = parsed if isinstance(parsed, dict) else {"text": str(parsed)}
        except json.JSONDecodeError:
            payload = {"text": raw.strip()}
    if not payload.get("text") and stderr:
        payload["text"] = stderr.strip()
    return normalise_asr_payload(
        payload,
        audio_path=audio_path,
        engine="community:command",
        device="external",
        compute_type="command",
    )


def command_tts(
    adapter: dict[str, Any],
    *,
    text: str,
    model_dir: Path,
    voice: str | None,
    reference: str | None,
    language: str,
    speed: float,
    output_path: Path,
    timeout: float,
    cancel_check: Callable[[], bool],
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    values = {
        "text": text,
        "model_dir": str(adapter.get("model_dir") or model_dir),
        "output": str(output_path),
        "voice": voice or "",
        "reference": reference or "",
        "language": language,
        "speed": f"{speed:g}",
    }
    _run_command(adapter, values, timeout, cancel_check)
    if not output_path.is_file() or output_path.stat().st_size <= 0:
        raise AdapterExecutionError("命令适配器没有生成有效音频文件")
    return output_path


def _run_command(
    adapter: dict[str, Any],
    values: dict[str, Any],
    timeout: float,
    cancel_check: Callable[[], bool],
) -> tuple[str, str, int]:
    raw_command = adapter.get("command")
    if isinstance(raw_command, str):
        command = shlex.split(raw_command, posix=sys.platform != "win32")
    elif isinstance(raw_command, list):
        command = [str(part) for part in raw_command]
    else:
        raise AdapterExecutionError("command 必须是字符串或数组")
    if not command:
        raise AdapterExecutionError("command 不能为空")
    command = [_expand(part, values) for part in command]
    stdin_text = _expand(adapter["stdin"], values) if adapter.get("stdin") else None
    env = os.environ.copy()
    for key, value in (adapter.get("env") or {}).items():
        env[str(key)] = _expand(value, values)
    cwd = adapter.get("cwd")
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(cwd) if cwd else None,
            env=env,
        )
    except OSError as exc:
        raise AdapterExecutionError(f"无法启动命令适配器：{exc}") from exc
    stdout_parts: list[str] = []
    stderr_parts: list[str] = []
    lock = threading.Lock()

    def read(stream, target: list[str]) -> None:
        if stream is None:
            return
        for line in stream:
            with lock:
                if sum(len(part) for part in target) < 4_000_000:
                    target.append(line)

    out_thread = threading.Thread(target=read, args=(process.stdout, stdout_parts), daemon=True)
    err_thread = threading.Thread(target=read, args=(process.stderr, stderr_parts), daemon=True)
    out_thread.start()
    err_thread.start()
    if stdin_text is not None and process.stdin is not None:
        try:
            process.stdin.write(stdin_text)
            process.stdin.close()
        except OSError:
            pass
    started = time.monotonic()
    try:
        while process.poll() is None:
            if cancel_check():
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                raise AdapterExecutionError("命令适配器已取消")
            if time.monotonic() - started > timeout:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                raise AdapterExecutionError(f"命令适配器超时（{timeout:.0f}s）")
            time.sleep(0.2)
    finally:
        out_thread.join(timeout=2)
        err_thread.join(timeout=2)
    stdout = "".join(stdout_parts)
    stderr = "".join(stderr_parts)
    if process.returncode != 0:
        raise AdapterExecutionError(
            f"命令适配器退出码 {process.returncode}：{stderr[-800:] or stdout[-800:]}"
        )
    return stdout, stderr, int(process.returncode or 0)


def normalise_asr_payload(
    payload: dict[str, Any],
    *,
    audio_path: Path,
    engine: str,
    device: str,
    compute_type: str,
) -> dict[str, Any]:
    text = str(payload.get("text") or payload.get("result") or "").strip()
    raw_segments = payload.get("segments") or []
    segments: list[dict[str, Any]] = []
    if isinstance(raw_segments, list):
        for index, item in enumerate(raw_segments, start=1):
            if not isinstance(item, dict):
                continue
            seg_text = str(item.get("text") or "").strip()
            if not seg_text:
                continue
            try:
                start = float(item.get("start") or 0)
                end = float(item.get("end") or start)
            except (TypeError, ValueError):
                start, end = 0.0, 0.0
            segments.append(
                {
                    "id": index,
                    "start": round(start, 3),
                    "end": round(end, 3),
                    "text": seg_text,
                }
            )
    duration = _duration(payload.get("duration"), audio_path)
    if not segments and text:
        segments = [
            {
                "id": 1,
                "start": 0.0,
                "end": round(duration, 3),
                "text": text,
            }
        ]
    if not text and segments:
        text = " ".join(item["text"] for item in segments)
    if not duration and segments:
        duration = max(float(item["end"]) for item in segments)
    return {
        "text": text,
        "segments": segments,
        "duration": round(float(duration or 0.0), 3),
        "detected_language": str(payload.get("language") or payload.get("detected_language") or "unknown"),
        "language_probability": payload.get("language_probability"),
        "device": device,
        "compute_type": compute_type,
        "engine": engine,
        "warning": payload.get("warning"),
    }


def _duration(value: Any, audio_path: Path) -> float:
    try:
        if value is not None:
            return float(value)
    except (TypeError, ValueError):
        pass
    try:
        from .asr import probe_duration

        return float(probe_duration(audio_path) or 0.0)
    except Exception:
        return 0.0
