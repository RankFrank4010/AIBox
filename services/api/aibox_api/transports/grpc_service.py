"""gRPC transport for external ASR clients."""

from __future__ import annotations

import asyncio
import time
import uuid
import wave
from pathlib import Path
from typing import Any

import grpc
from grpc_reflection.v1alpha import reflection

from ..auth import token_matches
from ..config import AppConfig
from ..external import (
    AUDIO_EXTENSIONS,
    ExternalAsrGateway,
    ExternalServiceError,
    normalize_filename,
    normalize_options,
)
from ..proto import (
    aibox_asr_pb2,
    aibox_asr_pb2_grpc,
    aibox_tts_pb2,
    aibox_tts_pb2_grpc,
)
from ..tts import TtsEngine, TtsUnavailable

SERVICE_NAME = "aibox.asr.v1.AsrService"
TTS_SERVICE_NAME = "aibox.tts.v1.TtsService"
GRPC_FORMATS = {"pcm16", "wav", "mp3", "m4a", "webm", "ogg", "flac", "opus", "aac"}


def _options_from_proto(options: aibox_asr_pb2.TranscribeOptions, config: AppConfig) -> dict[str, Any]:
    return normalize_options(
        config,
        {
            "language": options.language or "auto",
            "task": options.task or "transcribe",
            "beam_size": options.beam_size or None,
            "vad_filter": options.vad_filter or None,
            "word_timestamps": options.word_timestamps or None,
            "device": options.device or "auto",
            "compute_type": options.compute_type or "auto",
        },
    )


def _response_from_record(
    record: dict[str, Any],
    model: str | None = None,
) -> aibox_asr_pb2.TranscribeResponse:
    segments = []
    for item in record.get("segments") or []:
        words = []
        for word in item.get("words") or []:
            words.append(
                aibox_asr_pb2.Word(
                    word=str(word.get("word") or ""),
                    start=float(word.get("start") or 0),
                    end=float(word.get("end") or 0),
                    probability=float(word.get("probability") or 0),
                )
            )
        segments.append(
            aibox_asr_pb2.Segment(
                id=int(item.get("id") or 0),
                start=float(item.get("start") or 0),
                end=float(item.get("end") or 0),
                text=str(item.get("text") or ""),
                words=words,
            )
        )
    return aibox_asr_pb2.TranscribeResponse(
        text=record.get("text") or "",
        segments=segments,
        duration=float(record.get("duration") or 0),
        language=str(record.get("detected_language") or record.get("language") or ""),
        language_probability=float(record.get("language_probability") or 0),
        model=str(model or record.get("model_id") or ""),
        device=str(record.get("device") or ""),
        compute_type=str(record.get("compute_type") or ""),
        warning=str(record.get("warning") or ""),
        engine=str(record.get("engine") or ""),
        transcription_id=str(record.get("id") or ""),
    )


class AsrServiceServicer(aibox_asr_pb2_grpc.AsrServiceServicer):
    def __init__(self, config: AppConfig, gateway: ExternalAsrGateway) -> None:
        self.config = config
        self.gateway = gateway

    def _authorized(self, context: grpc.aio.ServicerContext) -> bool:
        if not self.config.api_token:
            return True
        metadata = {key.lower(): value for key, value in context.invocation_metadata()}
        return token_matches(self.config, metadata.get("authorization"))

    async def Transcribe(  # noqa: N802 - gRPC method name
        self,
        request: aibox_asr_pb2.TranscribeRequest,
        context: grpc.aio.ServicerContext,
    ) -> aibox_asr_pb2.TranscribeResponse:
        if not self._authorized(context):
            await context.abort(grpc.StatusCode.UNAUTHENTICATED, "Invalid API token")
        if not request.audio:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "audio is empty")
        if len(request.audio) > self.config.max_upload_mb * 1024 * 1024:
            await context.abort(grpc.StatusCode.RESOURCE_EXHAUSTED, "audio is too large")

        filename = normalize_filename(
            request.filename,
            f"grpc-{uuid.uuid4().hex[:10]}.wav",
        )
        suffix = Path(filename).suffix.lower()
        if suffix not in AUDIO_EXTENSIONS:
            suffix = ".wav"
        temp = self.config.uploads_dir / f".incoming_grpc_{uuid.uuid4().hex}{suffix}"
        temp.write_bytes(request.audio)
        try:
            record = await asyncio.to_thread(
                self.gateway.submit_and_wait,
                temp,
                filename=filename,
                model=request.options.model or None,
                options=_options_from_proto(request.options, self.config),
                transport="grpc",
            )
            return _response_from_record(record)
        except ExternalServiceError as exc:
            await context.abort(
                grpc.StatusCode.NOT_FOUND
                if exc.status_code == 404
                else grpc.StatusCode.INTERNAL
                if exc.status_code >= 500
                else grpc.StatusCode.INVALID_ARGUMENT,
                exc.message,
            )
        finally:
            temp.unlink(missing_ok=True)

    async def TranscribeStream(  # noqa: N802 - gRPC method name
        self,
        request_iterator: Any,
        context: grpc.aio.ServicerContext,
    ):
        if not self._authorized(context):
            await context.abort(grpc.StatusCode.UNAUTHENTICATED, "Invalid API token")

        session_id = uuid.uuid4().hex[:12]
        start: aibox_asr_pb2.StartSession | None = None
        pcm = bytearray()
        sample_rate = 16000
        audio_format = "pcm16"
        temp: Path | None = None
        submitted_id: str | None = None
        written = 0
        max_bytes = self.config.max_upload_mb * 1024 * 1024

        try:
            async for chunk in request_iterator:
                payload = chunk.WhichOneof("payload")
                if payload == "start":
                    if start is not None:
                        yield aibox_asr_pb2.StreamEvent(
                            error=aibox_asr_pb2.Error(
                                message="start must be sent exactly once",
                                code=400,
                                type="invalid_request",
                            )
                        )
                        return
                    start = chunk.start
                    audio_format = (start.format or "pcm16").lower()
                    if audio_format not in GRPC_FORMATS:
                        yield aibox_asr_pb2.StreamEvent(
                            error=aibox_asr_pb2.Error(
                                message=f"unsupported format {audio_format}",
                                code=400,
                                type="invalid_request",
                            )
                        )
                        return
                    try:
                        sample_rate = max(8000, min(48000, int(start.sample_rate or 16000)))
                    except (TypeError, ValueError):
                        sample_rate = 16000
                    try:
                        model_entry = self.gateway.resolve_model(start.options.model or None)
                    except ExternalServiceError as exc:
                        yield aibox_asr_pb2.StreamEvent(
                            error=aibox_asr_pb2.Error(
                                message=exc.message,
                                code=exc.status_code,
                                type=exc.code,
                            )
                        )
                        return
                    filename = normalize_filename(
                        start.filename,
                        f"grpc-{session_id}{'.wav' if audio_format == 'pcm16' else '.' + audio_format}",
                    )
                    suffix = Path(filename).suffix.lower()
                    if audio_format == "pcm16":
                        suffix = ".wav"
                    elif suffix not in AUDIO_EXTENSIONS:
                        suffix = f".{audio_format}"
                    temp = self.config.uploads_dir / f".incoming_grpc_{session_id}{suffix}"
                    yield aibox_asr_pb2.StreamEvent(
                        started=aibox_asr_pb2.Started(
                            session_id=session_id,
                            model=str(model_entry["id"]),
                            format=audio_format,
                            sample_rate=sample_rate if audio_format == "pcm16" else 0,
                        )
                    )
                elif payload == "data":
                    if start is None:
                        yield aibox_asr_pb2.StreamEvent(
                            error=aibox_asr_pb2.Error(
                                message="send StartSession before audio data",
                                code=400,
                                type="invalid_request",
                            )
                        )
                        return
                    written += len(chunk.data)
                    if written > max_bytes:
                        yield aibox_asr_pb2.StreamEvent(
                            error=aibox_asr_pb2.Error(
                                message="audio is too large",
                                code=413,
                                type="audio_too_large",
                            )
                        )
                        return
                    if audio_format == "pcm16":
                        pcm.extend(chunk.data)
                    else:
                        if temp is None:
                            return
                        with temp.open("ab") as handle:
                            handle.write(chunk.data)
                elif payload == "end" and chunk.end:
                    break
                else:
                    continue
            if start is None or temp is None:
                yield aibox_asr_pb2.StreamEvent(
                    error=aibox_asr_pb2.Error(
                        message="missing StartSession",
                        code=400,
                        type="invalid_request",
                    )
                )
                return
            if audio_format == "pcm16":
                if len(pcm) < sample_rate:
                    yield aibox_asr_pb2.StreamEvent(
                        error=aibox_asr_pb2.Error(
                            message="audio is too short",
                            code=400,
                            type="audio_too_short",
                        )
                    )
                    return
                if len(pcm) % 2:
                    pcm = pcm[:-1]
                with wave.open(str(temp), "wb") as handle:
                    handle.setnchannels(1)
                    handle.setsampwidth(2)
                    handle.setframerate(sample_rate)
                    handle.writeframes(bytes(pcm))
            options = _options_from_proto(start.options, self.config)
            try:
                record = self.gateway.submit(
                    temp,
                    filename=filename,
                    model=start.options.model or None,
                    options=options,
                    transport="grpc",
                )
                submitted_id = record["id"]
                temp = None
            except ExternalServiceError as exc:
                yield aibox_asr_pb2.StreamEvent(
                    error=aibox_asr_pb2.Error(
                        message=exc.message,
                        code=exc.status_code,
                        type=exc.code,
                    )
                )
                return

            last_progress = -1.0
            last_stage = ""
            deadline = time.monotonic() + 1800
            while time.monotonic() < deadline:
                current = self.gateway.store.get(record["id"])
                if current is None:
                    return
                if current["status"] == "completed":
                    yield aibox_asr_pb2.StreamEvent(
                        result=_response_from_record(current, record["model_id"])
                    )
                    return
                if current["status"] in {"failed", "cancelled"}:
                    yield aibox_asr_pb2.StreamEvent(
                        error=aibox_asr_pb2.Error(
                            message=current.get("error") or "transcription cancelled",
                            code=500 if current["status"] == "failed" else 409,
                            type="transcription_failed",
                        )
                    )
                    return
                progress = float(current.get("progress") or 0)
                stage = str(current.get("stage") or "")
                if progress - last_progress >= 2 or stage != last_stage:
                    last_progress = progress
                    last_stage = stage
                    yield aibox_asr_pb2.StreamEvent(
                        progress=aibox_asr_pb2.Progress(
                            progress=progress,
                            stage=stage,
                            status=current["status"],
                        )
                    )
                await asyncio.sleep(0.25)
            yield aibox_asr_pb2.StreamEvent(
                error=aibox_asr_pb2.Error(
                    message="transcription timed out",
                    code=504,
                    type="transcription_timeout",
                )
            )
        finally:
            if submitted_id:
                self.gateway.jobs.cancel(submitted_id)
            if temp is not None:
                temp.unlink(missing_ok=True)


class TtsServiceServicer(aibox_tts_pb2_grpc.TtsServiceServicer):
    def __init__(self, config: AppConfig, engine: TtsEngine) -> None:
        self.config = config
        self.engine = engine

    def _authorized(self, context: grpc.aio.ServicerContext) -> bool:
        if not self.config.api_token:
            return True
        metadata = {key.lower(): value for key, value in context.invocation_metadata()}
        return token_matches(self.config, metadata.get("authorization"))

    async def _synthesize(
        self,
        request: aibox_tts_pb2.SynthesizeRequest,
        context: grpc.aio.ServicerContext,
    ) -> tuple[aibox_tts_pb2.SynthesizeResponse, bytes]:
        if not self._authorized(context):
            await context.abort(grpc.StatusCode.UNAUTHENTICATED, "Invalid API token")
        if not request.text.strip():
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "text is empty")
        try:
            result = await asyncio.to_thread(
                self.engine.synthesize,
                text=request.text,
                model_id=request.model or None,
                voice=request.voice or None,
                language=request.language or "auto",
                speed=request.speed or 1.0,
                response_format=request.format or "wav",
            )
        except TtsUnavailable as exc:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
        path = Path(result["path"])
        try:
            content = path.read_bytes()
        finally:
            path.unlink(missing_ok=True)
        response = aibox_tts_pb2.SynthesizeResponse(
            audio=content,
            format=str(result["format"]),
            model=request.model or "tts-1",
            voice=request.voice or "default",
            warning=str(result.get("warning") or ""),
            sample_rate=0,
        )
        return response, content

    async def Synthesize(  # noqa: N802 - gRPC method name
        self,
        request: aibox_tts_pb2.SynthesizeRequest,
        context: grpc.aio.ServicerContext,
    ) -> aibox_tts_pb2.SynthesizeResponse:
        response, _ = await self._synthesize(request, context)
        return response

    async def SynthesizeStream(  # noqa: N802 - gRPC method name
        self,
        request: aibox_tts_pb2.SynthesizeRequest,
        context: grpc.aio.ServicerContext,
    ):
        response, content = await self._synthesize(request, context)
        chunk_size = 64 * 1024
        for index in range(0, len(content), chunk_size):
            yield aibox_tts_pb2.AudioChunk(
                data=content[index : index + chunk_size],
                format=response.format,
                final=index + chunk_size >= len(content),
            )
        if not content:
            yield aibox_tts_pb2.AudioChunk(format=response.format, final=True)


async def start_grpc_server(
    config: AppConfig,
    gateway: ExternalAsrGateway,
    tts_engine: TtsEngine,
):
    if not config.grpc_enabled or config.grpc_port <= 0:
        return {
            "status": "disabled",
            "enabled": False,
            "host": config.grpc_host,
            "port": config.grpc_port,
            "service": SERVICE_NAME,
            "tts_service": TTS_SERVICE_NAME,
            "auth_required": bool(config.api_token),
        }, None
    try:
        server = grpc.aio.server(
            options=[
                ("grpc.max_receive_message_length", config.max_upload_mb * 1024 * 1024 + 1024),
                ("grpc.max_send_message_length", 64 * 1024 * 1024),
            ]
        )
        aibox_asr_pb2_grpc.add_AsrServiceServicer_to_server(
            AsrServiceServicer(config, gateway), server
        )
        aibox_tts_pb2_grpc.add_TtsServiceServicer_to_server(
            TtsServiceServicer(config, tts_engine), server
        )
        reflection.enable_server_reflection(
            (SERVICE_NAME, TTS_SERVICE_NAME, reflection.SERVICE_NAME),
            server,
        )
        address = f"{config.grpc_host}:{config.grpc_port}"
        actual_port = server.add_insecure_port(address)
        if actual_port == 0:
            raise RuntimeError(f"could not bind {address}")
        await server.start()
        return {
            "status": "running",
            "enabled": True,
            "host": config.grpc_host,
            "port": actual_port,
            "service": SERVICE_NAME,
            "tts_service": TTS_SERVICE_NAME,
            "proto": "services/api/aibox_api/proto/aibox_asr.proto",
            "tts_proto": "services/api/aibox_api/proto/aibox_tts.proto",
            "auth_required": bool(config.api_token),
        }, server
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "error",
            "enabled": True,
            "host": config.grpc_host,
            "port": config.grpc_port,
            "service": SERVICE_NAME,
            "tts_service": TTS_SERVICE_NAME,
            "error": str(exc),
            "auth_required": bool(config.api_token),
        }, None


async def stop_grpc_server(server: Any) -> None:
    if server is None:
        return
    try:
        await server.stop(grace=2)
    except Exception:
        pass
