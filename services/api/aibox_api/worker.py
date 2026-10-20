"""AIBox compute worker.

Run one worker per machine (or container) and point it at the coordinator:

    python -m aibox_api.worker \
      --id worker-1 --url http://worker-1:9101 \
      --coordinator http://aibox:8765 \
      --capabilities translation,ocr --max-concurrency 2

The worker advertises capabilities, sends heartbeats and exposes an internal
execute endpoint. It does not route cluster tasks recursively.
"""

from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
import uvicorn
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from .config import AppConfig
from .ocr import OcrError, OcrService
from .translation import TranslationError, TranslationService

logger = logging.getLogger("aibox.worker")


class ExecuteRequest(BaseModel):
    task_id: str
    kind: str
    payload: dict[str, Any]


class WorkerRuntime:
    def __init__(
        self,
        config: AppConfig,
        *,
        node_id: str,
        url: str,
        coordinator: str,
        capabilities: list[str],
        max_concurrency: int,
        token: str | None,
        labels: dict[str, str] | None = None,
    ) -> None:
        self.config = config
        self.node_id = node_id
        self.url = url.rstrip("/")
        self.coordinator = coordinator.rstrip("/")
        self.capabilities = capabilities
        self.max_concurrency = max_concurrency
        self.token = token
        self.labels = labels or {}
        self.translation = TranslationService(config)
        self.ocr = OcrService(config)
        self._slots = threading.BoundedSemaphore(max_concurrency)
        self._stopped = threading.Event()
        self._thread: threading.Thread | None = None

    def _headers(self) -> dict[str, str]:
        headers = {"X-AIBox-Protocol": "1.0"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def register(self) -> None:
        payload = {
            "id": self.node_id,
            "url": self.url,
            "capabilities": self.capabilities,
            "labels": self.labels,
            "work_config": {
                "enabled": True,
                "capabilities": self.capabilities,
                "max_concurrency": self.max_concurrency,
                "labels": self.labels,
            },
            "max_concurrency": self.max_concurrency,
            "version": "1.0",
        }
        try:
            with httpx.Client(timeout=15) as client:
                response = client.post(
                    f"{self.coordinator}/api/cluster/nodes",
                    headers=self._headers(),
                    json=payload,
                )
                response.raise_for_status()
            logger.info("registered worker %s at %s", self.node_id, self.url)
        except (httpx.HTTPError, OSError) as exc:
            logger.warning("worker registration failed: %s", exc)

    def _heartbeat_loop(self) -> None:
        while not self._stopped.wait(5):
            try:
                with httpx.Client(timeout=10) as client:
                    response = client.post(
                        f"{self.coordinator}/api/cluster/nodes/{self.node_id}/heartbeat",
                        headers=self._headers(),
                    )
                    if response.status_code == 404:
                        self.register()
            except (httpx.HTTPError, OSError) as exc:
                logger.debug("heartbeat failed: %s", exc)

    def start(self) -> None:
        self.register()
        self._thread = threading.Thread(
            target=self._heartbeat_loop,
            name="aibox-worker-heartbeat",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stopped.set()

    def execute(self, request: ExecuteRequest) -> dict[str, Any]:
        if not self._slots.acquire(blocking=False):
            raise HTTPException(status_code=429, detail="worker 并发已满。")
        try:
            if request.kind == "translation":
                data = request.payload
                delay_ms = max(0, min(30_000, int(data.get("delay_ms") or 0)))
                if delay_ms:
                    time.sleep(delay_ms / 1000)
                return self.translation.translate(
                    text=str(data.get("text") or ""),
                    source=str(data.get("source") or "auto"),
                    target=str(data.get("target") or "zh"),
                    provider=str(data.get("provider") or "auto"),
                    model=data.get("model"),
                )
            if request.kind == "ocr":
                data = request.payload
                encoded = str(data.get("image_b64") or "")
                if not encoded:
                    raise HTTPException(status_code=400, detail="缺少 image_b64。")
                suffix = Path(str(data.get("filename") or "image.png")).suffix or ".png"
                target_dir = self.config.ocr_dir / "worker"
                target_dir.mkdir(parents=True, exist_ok=True)
                image_path = target_dir / f"{uuid.uuid4().hex}{suffix}"
                try:
                    image_path.write_bytes(base64.b64decode(encoded))
                    return self.ocr.recognize(
                        image_path=image_path,
                        provider=str(data.get("provider") or "auto"),
                        model=data.get("model"),
                        language=str(data.get("language") or "auto"),
                    )
                finally:
                    image_path.unlink(missing_ok=True)
            if request.kind == "echo":
                return {"echo": request.payload}
            raise HTTPException(status_code=400, detail=f"未知任务类型：{request.kind}")
        except (TranslationError, OcrError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        finally:
            self._slots.release()


def create_worker_app(
    config: AppConfig,
    *,
    node_id: str,
    url: str,
    coordinator: str,
    capabilities: list[str],
    max_concurrency: int = 1,
    token: str | None = None,
    labels: dict[str, str] | None = None,
) -> FastAPI:
    runtime = WorkerRuntime(
        config,
        node_id=node_id,
        url=url,
        coordinator=coordinator,
        capabilities=capabilities,
        max_concurrency=max_concurrency,
        token=token,
        labels=labels,
    )
    app = FastAPI(title=f"AIBox Worker {node_id}", version="1.0")
    app.state.worker = runtime

    @app.on_event("startup")
    def startup() -> None:
        runtime.start()

    @app.on_event("shutdown")
    def shutdown() -> None:
        runtime.stop()

    @app.get("/internal/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "node_id": node_id,
            "capabilities": capabilities,
            "max_concurrency": max_concurrency,
        }

    @app.post("/internal/execute")
    def execute(
        payload: ExecuteRequest,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        if token and authorization != f"Bearer {token}":
            raise HTTPException(status_code=401, detail="worker Token 无效。")
        result = runtime.execute(payload)
        return {"task_id": payload.task_id, "result": result}

    return app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="aibox-worker")
    parser.add_argument("--id", required=True, help="worker node id")
    parser.add_argument("--url", required=True, help="worker URL reachable by coordinator")
    parser.add_argument("--coordinator", required=True, help="coordinator base URL")
    parser.add_argument("--capabilities", default="translation,ocr")
    parser.add_argument("--max-concurrency", type=int, default=1)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=9101)
    parser.add_argument("--token", default=os.getenv("AIBOX_CLUSTER_TOKEN"))
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--labels", default="{}", help="JSON object")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level="INFO",
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = AppConfig(data_dir=Path(args.data_dir)) if args.data_dir else AppConfig()
    capabilities = [item.strip() for item in args.capabilities.split(",") if item.strip()]
    labels = json.loads(args.labels or "{}")
    app = create_worker_app(
        config,
        node_id=args.id,
        url=args.url,
        coordinator=args.coordinator,
        capabilities=capabilities,
        max_concurrency=max(1, args.max_concurrency),
        token=args.token,
        labels=labels,
    )
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
