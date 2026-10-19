"""SQLite persistence for OCR results."""

from __future__ import annotations

import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS ocr_records (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    language TEXT NOT NULL,
    text TEXT NOT NULL,
    image_path TEXT NOT NULL,
    filename TEXT NOT NULL,
    latency_ms INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_ocr_created ON ocr_records(created_at DESC);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _public(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "provider": row["provider"],
        "model": row["model"],
        "language": row["language"],
        "text": row["text"],
        "image_url": f"/api/ocr/images/{row['id']}",
        "filename": row["filename"],
        "latency_ms": row["latency_ms"],
    }


class OcrStore:
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
        with self._lock, self._connect() as connection:
            connection.executescript(SCHEMA)

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        record_id = f"ocr_{uuid.uuid4().hex[:14]}"
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO ocr_records (
                    id, created_at, provider, model, language, text,
                    image_path, filename, latency_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record_id,
                    utc_now(),
                    payload["provider"],
                    payload["model"],
                    payload["language"],
                    payload["text"],
                    payload["image_path"],
                    payload["filename"],
                    int(payload.get("latency_ms") or 0),
                ),
            )
        return self.get(record_id) or {}

    def get(self, record_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM ocr_records WHERE id = ?", (record_id,)
            ).fetchone()
        return _public(row) if row else None

    def get_raw(self, record_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM ocr_records WHERE id = ?", (record_id,)
            ).fetchone()
        return dict(row) if row else None

    def list(self, limit: int = 50) -> list[dict[str, Any]]:
        limit = max(1, min(200, int(limit)))
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM ocr_records ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [_public(row) for row in rows]

    def delete(self, record_id: str) -> bool:
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM ocr_records WHERE id = ?", (record_id,)
            )
        return cursor.rowcount > 0
