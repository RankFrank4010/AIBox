"""Watermark removal history and asynchronous video jobs."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import AppConfig
from .watermark import WatermarkService

SCHEMA = """
CREATE TABLE IF NOT EXISTS watermark_jobs (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    provider TEXT NOT NULL DEFAULT 'auto',
    filename TEXT NOT NULL,
    input_path TEXT NOT NULL,
    output_path TEXT NOT NULL,
    mask_path TEXT,
    regions_json TEXT NOT NULL DEFAULT '[]',
    progress REAL NOT NULL DEFAULT 0,
    error TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
"""


def _now() -> float:
    return time.time()


def _iso(value: float) -> str:
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat(timespec="seconds")


class WatermarkStore:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.database_path = config.database_path
        self._lock = threading.RLock()
        with self._lock, self._connect() as connection:
            connection.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.database_path), timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _public(self, row: sqlite3.Row) -> dict[str, Any]:
        record = {
            "id": row["id"],
            "kind": row["kind"],
            "status": row["status"],
            "provider": row["provider"],
            "filename": row["filename"],
            "progress": row["progress"],
            "error": row["error"],
            "regions": json.loads(row["regions_json"] or "[]"),
            "created_at": _iso(row["created_at"]),
            "updated_at": _iso(row["updated_at"]),
        }
        if row["status"] == "completed":
            record["output_url"] = f"/api/watermarks/{row['id']}/file"
        return record

    def create(
        self,
        *,
        kind: str,
        provider: str,
        filename: str,
        input_path: Path,
        output_path: Path,
        mask_path: Path | None,
        regions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        job_id = "wm_" + uuid.uuid4().hex[:14]
        now = _now()
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT INTO watermark_jobs "
                "(id, kind, status, provider, filename, input_path, output_path, "
                "mask_path, regions_json, created_at, updated_at) "
                "VALUES (?, ?, 'queued', ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    job_id,
                    kind,
                    provider,
                    filename,
                    str(input_path),
                    str(output_path),
                    str(mask_path) if mask_path else None,
                    json.dumps(regions, ensure_ascii=False),
                    now,
                    now,
                ),
            )
        return self.get(job_id) or {}

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM watermark_jobs WHERE id = ?", (job_id,)
            ).fetchone()
        return self._public(row) if row else None

    def raw(self, job_id: str) -> sqlite3.Row | None:
        with self._lock, self._connect() as connection:
            return connection.execute(
                "SELECT * FROM watermark_jobs WHERE id = ?", (job_id,)
            ).fetchone()

    def list(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM watermark_jobs ORDER BY created_at DESC LIMIT ?",
                (max(1, min(200, limit)),),
            ).fetchall()
        return [self._public(row) for row in rows]

    def update(
        self,
        job_id: str,
        *,
        status: str | None = None,
        progress: float | None = None,
        error: str | None = None,
    ) -> None:
        fields = ["updated_at = ?"]
        values: list[Any] = [_now()]
        if status is not None:
            fields.append("status = ?")
            values.append(status)
        if progress is not None:
            fields.append("progress = ?")
            values.append(progress)
        if error is not None:
            fields.append("error = ?")
            values.append(error)
        values.append(job_id)
        with self._lock, self._connect() as connection:
            connection.execute(
                f"UPDATE watermark_jobs SET {', '.join(fields)} WHERE id = ?", values
            )

    def delete(self, job_id: str) -> bool:
        row = self.raw(job_id)
        if not row:
            return False
        for key in ("input_path", "output_path", "mask_path"):
            path = row[key]
            if path:
                Path(path).unlink(missing_ok=True)
        with self._lock, self._connect() as connection:
            connection.execute("DELETE FROM watermark_jobs WHERE id = ?", (job_id,))
        return True


class WatermarkJobs:
    def __init__(self, config: AppConfig, service: WatermarkService, store: WatermarkStore) -> None:
        self.config = config
        self.service = service
        self.store = store
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="aibox-watermark")

    def submit_video(
        self,
        *,
        provider: str,
        filename: str,
        input_path: Path,
        output_path: Path,
        mask_path: Path | None,
        regions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        record = self.store.create(
            kind="video",
            provider=provider,
            filename=filename,
            input_path=input_path,
            output_path=output_path,
            mask_path=mask_path,
            regions=regions,
        )
        self._pool.submit(self._run, record["id"])
        return record

    def _run(self, job_id: str) -> None:
        row = self.store.raw(job_id)
        if not row:
            return
        self.store.update(job_id, status="running", progress=0.01)

        def progress(value: float, _: str) -> None:
            self.store.update(job_id, progress=max(0.01, min(0.99, value)))

        try:
            result = self.service.remove_video(
                input_path=Path(row["input_path"]),
                output_path=Path(row["output_path"]),
                mask_path=Path(row["mask_path"]) if row["mask_path"] else None,
                regions=json.loads(row["regions_json"] or "[]"),
                provider=row["provider"],
                progress=progress,
            )
            self.store.update(job_id, status="completed", progress=1, error=None)
            logger.info("watermark video %s completed: %s", job_id, result)
        except Exception as exc:  # noqa: BLE001
            logger.exception("watermark video failed")
            self.store.update(job_id, status="failed", error=str(exc))

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)


import logging  # noqa: E402

logger = logging.getLogger("aibox.watermark.jobs")
