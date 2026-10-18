"""SQLite persistence for video generation jobs."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS video_generations (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    stage TEXT NOT NULL DEFAULT '排队中',
    progress REAL NOT NULL DEFAULT 0,
    prompt TEXT NOT NULL,
    model_id TEXT NOT NULL,
    provider TEXT NOT NULL DEFAULT 'auto',
    duration INTEGER NOT NULL DEFAULT 6,
    resolution TEXT NOT NULL DEFAULT '1080P',
    aspect TEXT NOT NULL DEFAULT '16:9',
    width INTEGER NOT NULL DEFAULT 1920,
    height INTEGER NOT NULL DEFAULT 1080,
    seed INTEGER,
    video_path TEXT,
    poster_path TEXT,
    warning TEXT,
    error TEXT,
    options_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_video_generations_created
    ON video_generations(created_at DESC);
"""

WRITABLE_FIELDS = {
    "status",
    "stage",
    "progress",
    "duration",
    "width",
    "height",
    "provider",
    "video_path",
    "poster_path",
    "warning",
    "error",
    "seed",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class VideoStore:
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
        prompt: str,
        model_id: str,
        provider: str,
        duration: int,
        resolution: str,
        aspect: str,
        width: int,
        height: int,
        seed: int | None,
        options: dict[str, Any],
    ) -> dict[str, Any]:
        now = utc_now()
        with self._write_lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO video_generations
                    (id, created_at, updated_at, status, stage, progress, prompt,
                     model_id, provider, duration, resolution, aspect, width, height,
                     seed, options_json)
                VALUES (?, ?, ?, 'queued', '排队中', 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    id,
                    now,
                    now,
                    prompt,
                    model_id,
                    provider,
                    duration,
                    resolution,
                    aspect,
                    width,
                    height,
                    seed,
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
                f"UPDATE video_generations SET {assignments} WHERE id = ?",  # noqa: S608
                values,
            )
        return self.get(job_id)

    def set_video(
        self,
        job_id: str,
        *,
        video_path: str,
        poster_path: str | None,
        duration: int,
        width: int,
        height: int,
        provider: str,
        warning: str | None = None,
    ) -> dict[str, Any] | None:
        return self.update(
            job_id,
            status="completed",
            stage="生成完成",
            progress=100.0,
            video_path=video_path,
            poster_path=poster_path,
            duration=duration,
            width=width,
            height=height,
            provider=provider,
            warning=warning,
            error=None,
        )

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM video_generations WHERE id = ?", (job_id,)
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def list(self, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM video_generations ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def delete(self, job_id: str) -> dict[str, Any] | None:
        record = self.get(job_id)
        if record is None:
            return None
        with self._write_lock, self._connect() as connection:
            connection.execute("DELETE FROM video_generations WHERE id = ?", (job_id,))
        return record

    def mark_interrupted(self) -> int:
        with self._write_lock, self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE video_generations
                SET status = 'failed', stage = '已中断',
                    error = '服务重启，视频生成任务已中断', updated_at = ?
                WHERE status IN ('queued', 'running', 'cancelling')
                """,
                (utc_now(),),
            )
            return cursor.rowcount

    def _row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        try:
            data["options"] = json.loads(data.pop("options_json") or "{}")
        except json.JSONDecodeError:
            data["options"] = {}
        return data
