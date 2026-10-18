"""SQLite persistence for vocal / background separation jobs."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS separations (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    stage TEXT NOT NULL DEFAULT '排队中',
    progress REAL NOT NULL DEFAULT 0,
    filename TEXT NOT NULL,
    audio_path TEXT NOT NULL,
    audio_size INTEGER NOT NULL DEFAULT 0,
    model_id TEXT NOT NULL,
    mode TEXT NOT NULL DEFAULT 'instrumental',
    duration REAL,
    outputs_json TEXT NOT NULL DEFAULT '[]',
    error TEXT,
    options_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_separations_created
    ON separations(created_at DESC);
"""

WRITABLE_FIELDS = {
    "status",
    "stage",
    "progress",
    "duration",
    "outputs_json",
    "error",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class SeparationStore:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self._write_lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.database_path), timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        return connection

    def _initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._write_lock, self._connect() as connection:
            connection.executescript(SCHEMA)

    def create(
        self,
        *,
        id: str,
        filename: str,
        audio_path: str,
        audio_size: int,
        model_id: str,
        mode: str,
        options: dict[str, Any],
    ) -> dict[str, Any]:
        now = utc_now()
        with self._write_lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO separations
                    (id, created_at, updated_at, status, stage, progress, filename,
                     audio_path, audio_size, model_id, mode, options_json)
                VALUES (?, ?, ?, 'queued', '排队中', 0, ?, ?, ?, ?, ?, ?)
                """,
                (
                    id,
                    now,
                    now,
                    filename,
                    audio_path,
                    audio_size,
                    model_id,
                    mode,
                    json.dumps(options, ensure_ascii=False),
                ),
            )
        return self.get(id)  # type: ignore[return-value]

    def update(self, job_id: str, **fields: Any) -> dict[str, Any] | None:
        clean = {key: value for key, value in fields.items() if key in WRITABLE_FIELDS}
        if not clean:
            return self.get(job_id)
        clean["updated_at"] = utc_now()
        assignments = ", ".join(f"{key} = ?" for key in clean)
        values = list(clean.values()) + [job_id]
        with self._write_lock, self._connect() as connection:
            connection.execute(
                f"UPDATE separations SET {assignments} WHERE id = ?",  # noqa: S608
                values,
            )
        return self.get(job_id)

    def set_outputs(
        self,
        job_id: str,
        outputs: list[dict[str, Any]],
        duration: float | None = None,
    ) -> dict[str, Any] | None:
        return self.update(
            job_id,
            status="completed",
            stage="分离完成",
            progress=100.0,
            outputs_json=json.dumps(outputs, ensure_ascii=False),
            duration=duration,
            error=None,
        )

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM separations WHERE id = ?", (job_id,)
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def list(self, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM separations ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def delete(self, job_id: str) -> dict[str, Any] | None:
        record = self.get(job_id)
        if record is None:
            return None
        with self._write_lock, self._connect() as connection:
            connection.execute("DELETE FROM separations WHERE id = ?", (job_id,))
        return record

    def mark_interrupted(self) -> int:
        with self._write_lock, self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE separations
                SET status = 'failed', stage = '已中断',
                    error = '服务重启，分离任务已中断', updated_at = ?
                WHERE status IN ('queued', 'running', 'cancelling')
                """,
                (utc_now(),),
            )
            return cursor.rowcount

    def _row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        try:
            data["outputs"] = json.loads(data.pop("outputs_json") or "[]")
        except json.JSONDecodeError:
            data["outputs"] = []
        try:
            data["options"] = json.loads(data.pop("options_json") or "{}")
        except json.JSONDecodeError:
            data["options"] = {}
        return data
