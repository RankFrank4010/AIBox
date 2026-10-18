"""SQLite persistence for image generation history."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS image_generations (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    stage TEXT NOT NULL DEFAULT '排队中',
    progress REAL NOT NULL DEFAULT 0,
    prompt TEXT NOT NULL,
    negative_prompt TEXT NOT NULL DEFAULT '',
    model_id TEXT NOT NULL,
    provider TEXT NOT NULL DEFAULT 'auto',
    width INTEGER NOT NULL DEFAULT 1024,
    height INTEGER NOT NULL DEFAULT 1024,
    steps INTEGER NOT NULL DEFAULT 28,
    guidance REAL NOT NULL DEFAULT 3.5,
    seed INTEGER,
    batch INTEGER NOT NULL DEFAULT 1,
    image_paths_json TEXT NOT NULL DEFAULT '[]',
    warning TEXT,
    error TEXT,
    options_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_image_generations_created
    ON image_generations(created_at DESC);
"""

WRITABLE_FIELDS = {
    "status",
    "stage",
    "progress",
    "image_paths_json",
    "warning",
    "error",
    "provider",
    "seed",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ImageStore:
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
        negative_prompt: str,
        model_id: str,
        provider: str,
        width: int,
        height: int,
        steps: int,
        guidance: float,
        seed: int | None,
        batch: int,
        options: dict[str, Any],
    ) -> dict[str, Any]:
        now = utc_now()
        with self._write_lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO image_generations
                    (id, created_at, updated_at, status, stage, progress, prompt,
                     negative_prompt, model_id, provider, width, height, steps,
                     guidance, seed, batch, options_json)
                VALUES (?, ?, ?, 'queued', '排队中', 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    id,
                    now,
                    now,
                    prompt,
                    negative_prompt,
                    model_id,
                    provider,
                    width,
                    height,
                    steps,
                    guidance,
                    seed,
                    batch,
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
                f"UPDATE image_generations SET {assignments} WHERE id = ?",  # noqa: S608
                values,
            )
        return self.get(job_id)

    def set_images(self, job_id: str, paths: list[str], warning: str | None = None) -> dict[str, Any] | None:
        return self.update(
            job_id,
            status="completed",
            stage="生成完成",
            progress=100.0,
            image_paths_json=json.dumps(paths, ensure_ascii=False),
            warning=warning,
            error=None,
        )

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM image_generations WHERE id = ?", (job_id,)
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def list(self, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM image_generations ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def delete(self, job_id: str) -> dict[str, Any] | None:
        record = self.get(job_id)
        if record is None:
            return None
        with self._write_lock, self._connect() as connection:
            connection.execute("DELETE FROM image_generations WHERE id = ?", (job_id,))
        return record

    def mark_interrupted(self) -> int:
        with self._write_lock, self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE image_generations
                SET status = 'failed', stage = '已中断',
                    error = '服务重启，图像生成任务已中断', updated_at = ?
                WHERE status IN ('queued', 'running', 'cancelling')
                """,
                (utc_now(),),
            )
            return cursor.rowcount

    def _row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        try:
            data["image_paths"] = json.loads(data.pop("image_paths_json") or "[]")
        except json.JSONDecodeError:
            data["image_paths"] = []
        try:
            data["options"] = json.loads(data.pop("options_json") or "{}")
        except json.JSONDecodeError:
            data["options"] = {}
        return data
