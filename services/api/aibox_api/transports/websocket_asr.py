"""WebSocket ASR transport for chunked / live audio."""

from __future__ import annotations

import asyncio
import json
import threading
import time
import uuid
import wave
from pathlib import Path
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..auth import token_matches, websocket_token
from ..config import AppConfig
from ..external import (
    AUDIO_EXTENSIONS,
    ExternalAsrGateway,
    ExternalServiceError,
    normalize_filename,
    normalize_options,
)

WS_FORMATS = {"pcm16", "wav", "mp3", "m4a", "webm", "ogg", "flac", "opus", "aac"}


def _write_wav(path: Path, pcm: bytes, sample_rate: int) -> None:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm)


def create_websocket_router(
    config: AppConfig,
    gateway: ExternalAsrGateway,
) -> APIRouter:
    router = APIRouter(tags=["websocket"])
    engine = gateway.jobs.engine

    @router.websocket("/ws/asr")
    async def websocket_asr(websocket: WebSocket) -> None:
        supplied = websocket_token(
            dict(websocket.headers),
            dict(websocket.query_params),
        )
        if not token_matches(config, supplied):
            await websocket.close(code=1008, reason="Unauthorized")
            return
        await websocket.accept()
        send_lock = asyncio.Lock()
        session_id = uuid.uuid4().hex[:12]
        temp_path: Path | None = None
        submitted_id: str | None = None
        pcm = bytearray()
        sample_rate = 16000
        audio_format = "pcm16"
        encoded_handle = None
        written = 0
        max_bytes = config.max_upload_mb * 1024 * 1024
        partial_enabled = False
        partial_stopped = False
        partial_task: asyncio.Task[None] | None = None
        partial_cancel = threading.Event()
        last_partial_bytes = 0
        partial_limit_bytes = 60 * 2 * 16000

        async def send(payload: dict[str, Any]) -> None:
            async with send_lock:
                await websocket.send_json(payload)

        async def send_error(
            message: str,
            code: str = "invalid_request",
            status: int = 400,
        ) -> None:
            try:
                await send({"type": "error", "code": code, "status": status, "message": message})
            except Exception:
                pass

        try:
            first = await websocket.receive()
            if first.get("type") == "websocket.disconnect":
                return
            if "text" not in first:
                await send_error("First WebSocket message must be a JSON start message.")
                return
            start = json.loads(first["text"])
            if start.get("type") != "start":
                await send_error("Expected {'type':'start'} as the first message.")
                return

            try:
                model_entry = gateway.resolve_model(start.get("model"))
            except ExternalServiceError as exc:
                await send_error(exc.message, exc.code, exc.status_code)
                return

            audio_format = str(start.get("format") or "pcm16").lower()
            if audio_format not in WS_FORMATS:
                await send_error(
                    f"Unsupported format {audio_format}. Use pcm16 or an encoded format.",
                    "unsupported_format",
                )
                return
            try:
                sample_rate = max(8000, min(48000, int(start.get("sample_rate") or 16000)))
            except (TypeError, ValueError):
                sample_rate = 16000
            partial_enabled = bool(start.get("partial", False)) and audio_format == "pcm16"
            partial_limit_bytes = sample_rate * 2 * 60
            reference = str(start.get("language") or "auto")
            options = normalize_options(
                config,
                {
                    "language": reference,
                    "task": start.get("task"),
                    "beam_size": start.get("beam_size"),
                    "vad_filter": start.get("vad_filter"),
                    "word_timestamps": start.get("word_timestamps"),
                    "device": start.get("device"),
                    "compute_type": start.get("compute_type"),
                },
            )
            model_id = str(model_entry["id"])
            model_path = Path(str(model_entry.get("path") or config.models_dir / model_id))
            filename = normalize_filename(
                start.get("filename"),
                f"websocket-{session_id}{'.wav' if audio_format == 'pcm16' else '.' + audio_format}",
            )
            if audio_format == "pcm16":
                temp_path = config.uploads_dir / f".incoming_{session_id}.wav"
            else:
                suffix = Path(filename).suffix.lower()
                if suffix not in AUDIO_EXTENSIONS:
                    suffix = f".{audio_format}"
                temp_path = config.uploads_dir / f".incoming_{session_id}{suffix}"
                encoded_handle = temp_path.open("wb")

            await send(
                {
                    "type": "ready",
                    "session_id": session_id,
                    "model": model_id,
                    "format": audio_format,
                    "sample_rate": sample_rate if audio_format == "pcm16" else None,
                    "partial_supported": partial_enabled,
                }
            )

            async def run_partial(snapshot: bytes) -> None:
                partial_path = config.uploads_dir / f".partial_{session_id}_{int(time.time() * 1000)}.wav"
                try:
                    _write_wav(partial_path, snapshot, sample_rate)
                    result = await asyncio.to_thread(
                        engine.transcribe,
                        audio_path=partial_path,
                        model_path=model_path,
                        options={
                            **options,
                            "beam_size": 1,
                            "vad_filter": True,
                            "word_timestamps": False,
                        },
                        progress=lambda *_: None,
                        cancel_check=partial_cancel.is_set,
                    )
                    text = str(result.get("text") or "").strip()
                    if text and not partial_stopped:
                        await send(
                            {
                                "type": "partial",
                                "text": text,
                                "duration": result.get("duration"),
                            }
                        )
                except Exception:
                    pass
                finally:
                    partial_path.unlink(missing_ok=True)

            last_activity = time.monotonic()
            last_received_event = 0.0
            while True:
                message = await websocket.receive()
                if message.get("type") == "websocket.disconnect":
                    return
                if "bytes" in message and message["bytes"] is not None:
                    chunk = message["bytes"]
                    written += len(chunk)
                    if written > max_bytes:
                        await send_error(
                            f"Audio exceeds the {config.max_upload_mb} MB limit.",
                            "audio_too_large",
                            413,
                        )
                        return
                    if encoded_handle is not None:
                        encoded_handle.write(chunk)
                    else:
                        pcm.extend(chunk)
                        if partial_enabled and len(pcm) <= partial_limit_bytes:
                            enough_new = len(pcm) - last_partial_bytes >= sample_rate * 2 * 2
                            if enough_new and (partial_task is None or partial_task.done()):
                                last_partial_bytes = len(pcm)
                                partial_task = asyncio.create_task(run_partial(bytes(pcm)))
                    last_activity = time.monotonic()
                    if last_activity - last_received_event > 0.5:
                        last_received_event = last_activity
                        await send({"type": "received", "bytes": written})
                    continue
                if "text" not in message or message["text"] is None:
                    continue
                try:
                    control = json.loads(message["text"])
                except json.JSONDecodeError:
                    await send_error("Control messages must be JSON.", "invalid_json")
                    continue
                kind = control.get("type")
                if kind == "ping":
                    await send({"type": "pong", "ts": time.time()})
                    continue
                if kind == "cancel":
                    if submitted_id:
                        gateway.jobs.cancel(submitted_id)
                    await send({"type": "cancelled"})
                    return
                if kind not in {"stop", "commit"}:
                    await send_error(f"Unknown control type {kind}.", "unknown_control")
                    continue

                # Finalize the upload and run the same persistent job pipeline.
                partial_stopped = True
                partial_cancel.set()
                if partial_task is not None and not partial_task.done():
                    try:
                        await asyncio.wait_for(asyncio.shield(partial_task), timeout=10)
                    except (TimeoutError, asyncio.CancelledError):
                        pass
                if encoded_handle is not None:
                    encoded_handle.close()
                    encoded_handle = None
                else:
                    if len(pcm) < sample_rate:
                        await send_error("Audio is too short.", "audio_too_short", 400)
                        return
                    if len(pcm) % 2:
                        pcm = pcm[:-1]
                    _write_wav(temp_path, bytes(pcm), sample_rate)
                if temp_path is None or not temp_path.is_file():
                    await send_error("No audio was received.", "empty_audio", 400)
                    return
                try:
                    record = gateway.submit(
                        temp_path,
                        filename=filename,
                        model=model_id,
                        options=options,
                        transport="websocket",
                    )
                    submitted_id = record["id"]
                    temp_path = None
                except ExternalServiceError as exc:
                    await send_error(exc.message, exc.code, exc.status_code)
                    return

                await send(
                    {
                        "type": "processing",
                        "id": submitted_id,
                        "model": model_id,
                        "filename": filename,
                    }
                )
                last_progress = -1.0
                last_stage = ""
                deadline = time.monotonic() + 1800
                while time.monotonic() < deadline:
                    current = gateway.store.get(submitted_id)
                    if current is None:
                        await send_error("Job disappeared.", "job_not_found", 404)
                        return
                    if current["status"] == "completed":
                        await send(
                            {
                                "type": "final",
                                "id": submitted_id,
                                "text": current.get("text") or "",
                                "segments": current.get("segments") or [],
                                "duration": current.get("duration"),
                                "language": current.get("detected_language")
                                or current.get("language"),
                                "language_probability": current.get("language_probability"),
                                "model": current.get("model_id"),
                                "device": current.get("device"),
                                "compute_type": current.get("compute_type"),
                                "engine": current.get("engine"),
                                "warning": current.get("warning"),
                                "audio_url": current.get("audio_url"),
                                "export_urls": current.get("export_urls"),
                            }
                        )
                        return
                    if current["status"] in {"failed", "cancelled"}:
                        await send_error(
                            current.get("error") or "Transcription cancelled.",
                            "transcription_failed",
                            500 if current["status"] == "failed" else 409,
                        )
                        return
                    progress = float(current.get("progress") or 0)
                    stage = str(current.get("stage") or "")
                    if progress - last_progress >= 2 or stage != last_stage:
                        last_progress = progress
                        last_stage = stage
                        await send(
                            {
                                "type": "progress",
                                "progress": progress,
                                "stage": stage,
                                "status": current["status"],
                            }
                        )
                    await asyncio.sleep(0.25)
                await send_error("Transcription timed out.", "transcription_timeout", 504)
                return
        except WebSocketDisconnect:
            if submitted_id:
                gateway.jobs.cancel(submitted_id)
        except Exception as exc:
            try:
                await send_error(str(exc), "internal_error", 500)
            except Exception:
                pass
        finally:
            partial_cancel.set()
            if submitted_id:
                gateway.jobs.cancel(submitted_id)
            if encoded_handle is not None:
                try:
                    encoded_handle.close()
                except Exception:
                    pass
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    return router
