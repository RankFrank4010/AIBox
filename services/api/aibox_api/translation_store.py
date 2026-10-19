"""SQLite persistence for translation history."""

from __future__ import annotations

import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS translations (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    source_lang TEXT NOT NULL,
    target_lang TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    source_text TEXT NOT NULL,
    translated_text TEXT NOT NULL,
    detected_lang TEXT,
    latency_ms INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_translations_created
    ON translations(created_at DESC);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _public(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "source": row["source_lang"],
        "target": row["target_lang"],
        "provider": row["provider"],
        "model": row["model"],
        "text": row["source_text"],
        "translated": row["translated_text"],
        "detected_language": row["detected_lang"],
        "latency_ms": row["latency_ms"],
    }


class TranslationStore:
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
        record_id = f"tr_{uuid.uuid4().hex[:14]}"
        created_at = utc_now()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO translations (
                    id, created_at, source_lang, target_lang, provider, model,
                    source_text, translated_text, detected_lang, latency_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record_id,
                    created_at,
                    payload["source"],
                    payload["target"],
                    payload["provider"],
                    payload["model"],
                    payload["text"],
                    payload["translated"],
                    payload.get("detected_language"),
                    int(payload.get("latency_ms") or 0),
                ),
            )
        return self.get(record_id) or {}

    def get(self, record_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM translations WHERE id = ?", (record_id,)
            ).fetchone()
        return _public(row) if row else None

    def list(self, limit: int = 50) -> list[dict[str, Any]]:
        limit = max(1, min(200, int(limit)))
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM translations ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [_public(row) for row in rows]

    def delete(self, record_id: str) -> bool:
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM translations WHERE id = ?", (record_id,)
            )
        return cursor.rowcount > 0
