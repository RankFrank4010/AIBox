"""Background transcription job orchestration."""

from __future__ import annotations

import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from .asr import AsrUnavailable, TranscriptionCancelled, WhisperEngine
from .config import AppConfig
from .models import safe_model_dir
from .store import TranscriptionStore

logger = logging.getLogger("aibox.jobs")


class TranscriptionJobs:
    def __init__(
        self,
        config: AppConfig,
        store: TranscriptionStore,
        engine: WhisperEngine,
        max_workers: int = 2,
    ) -> None:
        self.config = config
        self.store = store
        self.engine = engine
        self.executor = ThreadPoolExecutor(
            max_workers=max(1, min(4, max_workers)), thread_name_prefix="aibox-asr"
        )
        self._events: dict[str, threading.Event] = {}
        self._models: dict[str, str] = {}
        self._lock = threading.RLock()

    def submit(self, transcription_id: str, model_id: str, options: dict[str, Any]) -> None:
        event = threading.Event()
        with self._lock:
            self._events[transcription_id] = event
            self._models[transcription_id] = model_id
        self.executor.submit(self._run, transcription_id, model_id, options, event)

    def cancel(self, transcription_id: str) -> bool:
        with self._lock:
            event = self._events.get(transcription_id)
        if event is not None:
            event.set()
            self.store.update(
                transcription_id,
                status="cancelling",
                stage="正在取消",
                error=None,
            )
            return True
        record = self.store.get(transcription_id)
        if record and record["status"] in {"queued", "running", "cancelling"}:
            self.store.update(
                transcription_id,
                status="cancelled",
                stage="已取消",
                progress=record.get("progress") or 0,
            )
            return True
        return False

    def model_in_use(self, model_id: str) -> bool:
        with self._lock:
            return model_id in self._models.values()

    def shutdown(self) -> None:
        with self._lock:
            for event in self._events.values():
                event.set()
        self.executor.shutdown(wait=False, cancel_futures=True)

    def _run(
        self,
        transcription_id: str,
        model_id: str,
        options: dict[str, Any],
        event: threading.Event,
    ) -> None:
        record = self.store.get(transcription_id, include_audio_path=True)
        if record is None:
            return
        audio_path = Path(record["audio_path"])
        model_path = safe_model_dir(self.config, model_id)
        last_write = 0.0

        def report(value: float, stage: str) -> None:
            nonlocal last_write
            now = time.monotonic()
            if now - last_write < 0.35 and value < 99.5:
                return
            self.store.update(
                transcription_id,
                status="running",
                stage=stage,
                progress=round(max(0.0, min(100.0, value)), 1),
            )
            last_write = now

        try:
            if event.is_set():
                raise TranscriptionCancelled("任务已取消")
            self.store.update(
                transcription_id,
                status="running",
                stage="准备模型",
                progress=1.0,
                error=None,
            )
            result = self.engine.transcribe(
                audio_path=audio_path,
                model_path=model_path,
                options=options,
                progress=report,
                cancel_check=event.is_set,
            )
            if event.is_set():
                raise TranscriptionCancelled("任务已取消")
            segments = result.get("segments") or []
            self.store.update(
                transcription_id,
                status="completed",
                stage="转写完成",
                progress=100.0,
                text=result.get("text") or "",
                segments_json=json.dumps(segments, ensure_ascii=False),
                duration=result.get("duration"),
                detected_language=result.get("detected_language"),
                language_probability=result.get("language_probability"),
                engine=result.get("engine"),
                device=result.get("device"),
                compute_type=result.get("compute_type"),
                warning=result.get("warning"),
                error=None,
            )
            logger.info(
                "transcription %s completed: %s segments on %s/%s",
                transcription_id,
                len(segments),
                result.get("device"),
                result.get("compute_type"),
            )
        except TranscriptionCancelled:
            self.store.update(
                transcription_id,
                status="cancelled",
                stage="已取消",
                error=None,
            )
        except AsrUnavailable as exc:
            logger.warning("transcription %s unavailable: %s", transcription_id, exc)
            self.store.update(
                transcription_id,
                status="failed",
                stage="处理失败",
                error=str(exc),
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("transcription %s failed", transcription_id)
            self.store.update(
                transcription_id,
                status="failed",
                stage="处理失败",
                error=f"转写失败：{exc}",
            )
        finally:
            with self._lock:
                self._events.pop(transcription_id, None)
                self._models.pop(transcription_id, None)
            if not self.config.settings().get("keep_audio", True):
                try:
                    audio_path.unlink(missing_ok=True)
                except OSError:
                    pass
