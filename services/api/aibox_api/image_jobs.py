"""Background image generation job orchestration."""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from .config import AppConfig
from .image import ImageEngine, ImageUnavailable
from .image_store import ImageStore

logger = logging.getLogger("aibox.images")


class ImageJobs:
    def __init__(
        self,
        config: AppConfig,
        store: ImageStore,
        engine: ImageEngine,
        max_workers: int = 1,
    ) -> None:
        self.config = config
        self.store = store
        self.engine = engine
        self.executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="aibox-image"
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
        self.store.update(
            job_id,
            status="cancelling",
            stage="正在取消",
        )
        return True

    def model_in_use(self, model_id: str) -> bool:
        return any(
            record.get("model_id") == model_id
            and record.get("status") in {"queued", "running", "cancelling"}
            for record in self.store.list(limit=200)
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
                if now - last_write < 0.3 and value < 99:
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
                negative_prompt=str(options.get("negative_prompt") or ""),
                model_id=options.get("model_id"),
                provider=str(options.get("provider") or "auto"),
                width=int(options.get("width") or 1024),
                height=int(options.get("height") or 1024),
                steps=int(options.get("steps") or 28),
                guidance=float(options.get("guidance") or 3.5),
                seed=options.get("seed"),
                batch=int(options.get("batch") or 1),
                job_id=job_id,
                workflow=options.get("workflow"),
                checkpoint=options.get("checkpoint"),
                progress=report,
            )
            if event.is_set():
                self.store.update(job_id, status="cancelled", stage="已取消")
                return
            paths = [str(path) for path in result.get("paths") or []]
            self.store.set_images(job_id, paths, result.get("warning"))
            self.store.update(
                job_id,
                provider=str(result.get("provider") or "auto"),
                seed=result.get("seed"),
            )
            logger.info(
                "image %s completed via %s (%s images)",
                job_id,
                result.get("provider"),
                len(paths),
            )
        except ImageUnavailable as exc:
            logger.warning("image %s unavailable: %s", job_id, exc)
            self.store.update(
                job_id,
                status="failed",
                stage="生成失败",
                error=str(exc),
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("image %s failed", job_id)
            self.store.update(
                job_id,
                status="failed",
                stage="生成失败",
                error=f"图像生成失败：{exc}",
            )
        finally:
            with self._lock:
                self._events.pop(job_id, None)
