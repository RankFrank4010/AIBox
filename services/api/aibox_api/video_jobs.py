"""Background video generation jobs."""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from .config import AppConfig
from .video import VideoEngine, VideoUnavailable
from .video_store import VideoStore

logger = logging.getLogger("aibox.videos")


class VideoJobs:
    def __init__(
        self,
        config: AppConfig,
        store: VideoStore,
        engine: VideoEngine,
        max_workers: int = 1,
    ) -> None:
        self.config = config
        self.store = store
        self.engine = engine
        self.executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="aibox-video"
        )
        self._events: dict[str, threading.Event] = {}
        self._lock = threading.Lock()

    def submit(self, job_id: str, options: dict[str, Any]) -> None:
        event = threading.Event()
        with self._lock:
            self._events[job_id] = event
        self.executor.submit(self._run, job_id, options, event)

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

    def _run(self, job_id: str, options: dict[str, Any], event: threading.Event) -> None:
        try:
            if event.is_set():
                self.store.update(job_id, status="cancelled", stage="已取消")
                return
            self.store.update(
                job_id,
                status="running",
                stage="正在生成",
                progress=3.0,
                error=None,
            )
            last_write = 0.0

            def report(value: float, stage: str) -> None:
                nonlocal last_write
                now = time.monotonic()
                if now - last_write < 0.4 and value < 99:
                    return
                self.store.update(
                    job_id,
                    status="running",
                    stage=stage,
                    progress=round(max(0.0, min(100.0, value)), 1),
                )
                last_write = now

            result = self.engine.generate(
                prompt=str(options.get("prompt") or ""),
                model_id=options.get("model_id"),
                duration=int(options.get("duration") or 6),
                resolution=str(options.get("resolution") or "1080P"),
                aspect=str(options.get("aspect") or "16:9"),
                seed=options.get("seed"),
                workflow=options.get("workflow"),
                job_id=job_id,
                progress=report,
            )
            if event.is_set():
                self.store.update(job_id, status="cancelled", stage="已取消")
                return
            self.store.set_video(
                job_id,
                video_path=str(result["path"]),
                poster_path=str(result["poster"]) if result.get("poster") else None,
                duration=int(result.get("duration") or 0),
                width=int(result.get("width") or 0),
                height=int(result.get("height") or 0),
                provider=str(result.get("provider") or "auto"),
                warning=result.get("warning"),
            )
            logger.info(
                "video %s completed via %s (%sx%s)",
                job_id,
                result.get("provider"),
                result.get("width"),
                result.get("height"),
            )
        except VideoUnavailable as exc:
            logger.warning("video %s unavailable: %s", job_id, exc)
            self.store.update(
                job_id,
                status="failed",
                stage="生成失败",
                error=str(exc),
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("video %s failed", job_id)
            self.store.update(
                job_id,
                status="failed",
                stage="生成失败",
                error=f"视频生成失败：{exc}",
            )
        finally:
            with self._lock:
                self._events.pop(job_id, None)
