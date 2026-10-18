"""Background vocal / background separation jobs."""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .asr import probe_duration
from .config import AppConfig
from .separation import SeparationEngine, SeparationUnavailable
from .separation_store import SeparationStore

logger = logging.getLogger("aibox.separation.jobs")


class SeparationJobs:
    def __init__(
        self,
        config: AppConfig,
        store: SeparationStore,
        engine: SeparationEngine,
        max_workers: int = 1,
    ) -> None:
        self.config = config
        self.store = store
        self.engine = engine
        self.executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="aibox-separation"
        )
        self._events: dict[str, threading.Event] = {}
        self._lock = threading.Lock()

    def submit(
        self,
        job_id: str,
        *,
        audio_path: Path,
        model_id: str,
        mode: str,
    ) -> None:
        event = threading.Event()
        with self._lock:
            self._events[job_id] = event
        self.executor.submit(self._run, job_id, audio_path, model_id, mode, event)

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            event = self._events.get(job_id)
        if event is None:
            return False
        event.set()
        self.store.update(job_id, status="cancelling", stage="正在取消")
        return True

    def model_in_use(self, model_id: str) -> bool:
        return any(
            record.get("model_id") == model_id
            and record.get("status") in {"queued", "running", "cancelling"}
            for record in self.store.list(limit=100)
        )

    def shutdown(self) -> None:
        with self._lock:
            for event in self._events.values():
                event.set()
        self.executor.shutdown(wait=False, cancel_futures=True)

    def _run(
        self,
        job_id: str,
        audio_path: Path,
        model_id: str,
        mode: str,
        event: threading.Event,
    ) -> None:
        try:
            if event.is_set():
                self.store.update(job_id, status="cancelled", stage="已取消")
                return
            self.store.update(
                job_id,
                status="running",
                stage="正在分离",
                progress=3.0,
                error=None,
            )
            last_write = 0.0

            def report(value: float, stage: str) -> None:
                nonlocal last_write
                now = time.monotonic()
                if now - last_write < 0.3 and value < 98:
                    return
                self.store.update(
                    job_id,
                    status="running",
                    stage=stage,
                    progress=round(max(0.0, min(100.0, value)), 1),
                )
                last_write = now

            result = self.engine.separate(
                audio_path=audio_path,
                model_id=model_id,
                mode=mode,
                job_id=job_id,
                progress=report,
            )
            if event.is_set():
                self.store.update(job_id, status="cancelled", stage="已取消")
                return
            duration = probe_duration(audio_path)
            self.store.set_outputs(
                job_id,
                result["outputs"],
                duration=duration,
            )
            logger.info(
                "separation %s completed via %s (%s stems)",
                job_id,
                result.get("provider"),
                len(result.get("outputs") or []),
            )
        except SeparationUnavailable as exc:
            logger.warning("separation %s unavailable: %s", job_id, exc)
            self.store.update(
                job_id,
                status="failed",
                stage="分离失败",
                error=str(exc),
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("separation %s failed", job_id)
            self.store.update(
                job_id,
                status="failed",
                stage="分离失败",
                error=f"分离失败：{exc}",
            )
        finally:
            with self._lock:
                self._events.pop(job_id, None)
