"""SQLite persistence for fine-tuning datasets and training jobs."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS training_datasets (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    path TEXT NOT NULL,
    format TEXT NOT NULL,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    rows INTEGER NOT NULL DEFAULT 0,
    preview_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS training_jobs (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    stage TEXT NOT NULL DEFAULT '排队中',
    progress REAL NOT NULL DEFAULT 0,
    name TEXT NOT NULL,
    base_model TEXT NOT NULL,
    method TEXT NOT NULL,
    dataset_id TEXT NOT NULL,
    output_dir TEXT NOT NULL,
    device TEXT NOT NULL DEFAULT 'auto',
    parallel_strategy TEXT NOT NULL DEFAULT 'single',
    config_json TEXT NOT NULL DEFAULT '{}',
    metrics_json TEXT NOT NULL DEFAULT '{}',
    log_path TEXT,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_training_jobs_created
    ON training_jobs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_training_datasets_created
    ON training_datasets(created_at DESC);
"""

JOB_WRITABLE = {
    "status",
    "stage",
    "progress",
    "metrics_json",
    "log_path",
    "error",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class TrainingStore:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.database_path), timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        return connection

    def _initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self._connect() as connection:
            connection.executescript(SCHEMA)

    # --------------------------------------------------------------- datasets
    def create_dataset(
        self,
        *,
        id: str,
        name: str,
        path: str,
        format: str,
        size_bytes: int,
        rows: int,
        preview: list[dict[str, Any]],
    ) -> dict[str, Any]:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO training_datasets
                    (id, name, path, format, size_bytes, rows, preview_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    id,
                    name,
                    path,
                    format,
                    size_bytes,
                    rows,
                    json.dumps(preview, ensure_ascii=False),
                    utc_now(),
                ),
            )
        return self.get_dataset(id)  # type: ignore[return-value]

    def get_dataset(self, dataset_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM training_datasets WHERE id = ?", (dataset_id,)
            ).fetchone()
        return self._dataset(row) if row else None

    def list_datasets(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM training_datasets ORDER BY created_at DESC"
            ).fetchall()
        return [self._dataset(row) for row in rows]

    def delete_dataset(self, dataset_id: str) -> dict[str, Any] | None:
        record = self.get_dataset(dataset_id)
        if record is None:
            return None
        with self._lock, self._connect() as connection:
            connection.execute(
                "DELETE FROM training_datasets WHERE id = ?", (dataset_id,)
            )
        return record

    # ------------------------------------------------------------------- jobs
    def create_job(
        self,
        *,
        id: str,
        name: str,
        base_model: str,
        method: str,
        dataset_id: str,
        output_dir: str,
        device: str,
        parallel_strategy: str,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        now = utc_now()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO training_jobs
                    (id, created_at, updated_at, status, stage, progress, name,
                     base_model, method, dataset_id, output_dir, device,
                     parallel_strategy, config_json)
                VALUES (?, ?, ?, 'queued', '排队中', 0, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    id,
                    now,
                    now,
                    name,
                    base_model,
                    method,
                    dataset_id,
                    output_dir,
                    device,
                    parallel_strategy,
                    json.dumps(config, ensure_ascii=False),
                ),
            )
        return self.get_job(id)  # type: ignore[return-value]

    def update_job(self, job_id: str, **fields: Any) -> dict[str, Any] | None:
        clean = {key: value for key, value in fields.items() if key in JOB_WRITABLE}
        if not clean:
            return self.get_job(job_id)
        clean["updated_at"] = utc_now()
        assignments = ", ".join(f"{key} = ?" for key in clean)
        values = list(clean.values()) + [job_id]
        with self._lock, self._connect() as connection:
            connection.execute(
                f"UPDATE training_jobs SET {assignments} WHERE id = ?",  # noqa: S608
                values,
            )
        return self.get_job(job_id)

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM training_jobs WHERE id = ?", (job_id,)
            ).fetchone()
        return self._job(row) if row else None

    def list_jobs(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM training_jobs ORDER BY created_at DESC LIMIT ?",
                (max(1, min(200, limit)),),
            ).fetchall()
        return [self._job(row) for row in rows]

    def delete_job(self, job_id: str) -> dict[str, Any] | None:
        record = self.get_job(job_id)
        if record is None:
            return None
        with self._lock, self._connect() as connection:
            connection.execute("DELETE FROM training_jobs WHERE id = ?", (job_id,))
        return record

    def mark_interrupted(self) -> int:
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE training_jobs
                SET status = 'failed', stage = '已中断',
                    error = '服务重启，训练任务已中断', updated_at = ?
                WHERE status IN ('queued', 'running', 'cancelling')
                """,
                (utc_now(),),
            )
            return cursor.rowcount

    # ----------------------------------------------------------------- helpers
    def _dataset(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        try:
            data["preview"] = json.loads(data.pop("preview_json") or "[]")
        except json.JSONDecodeError:
            data["preview"] = []
        return data

    def _job(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        try:
            data["config"] = json.loads(data.pop("config_json") or "{}")
        except json.JSONDecodeError:
            data["config"] = {}
        try:
            data["metrics"] = json.loads(data.pop("metrics_json") or "{}")
        except json.JSONDecodeError:
            data["metrics"] = {}
        return data
