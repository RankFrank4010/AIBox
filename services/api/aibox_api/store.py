"""SQLite persistence for transcription history and job progress."""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS transcriptions (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    stage TEXT NOT NULL DEFAULT '等待处理',
    progress REAL NOT NULL DEFAULT 0,
    filename TEXT NOT NULL,
    audio_path TEXT NOT NULL,
    audio_size INTEGER NOT NULL DEFAULT 0,
    duration REAL,
    model_id TEXT NOT NULL,
    task TEXT NOT NULL DEFAULT 'transcribe',
    language TEXT NOT NULL DEFAULT 'auto',
    detected_language TEXT,
    language_probability REAL,
    text TEXT NOT NULL DEFAULT '',
    segments_json TEXT NOT NULL DEFAULT '[]',
    options_json TEXT NOT NULL DEFAULT '{}',
    engine TEXT,
    device TEXT,
    compute_type TEXT,
    warning TEXT,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_transcriptions_created
    ON transcriptions(created_at DESC);
"""

WRITABLE_FIELDS = {
    "status",
    "stage",
    "progress",
    "duration",
    "detected_language",
    "language_probability",
    "text",
    "segments_json",
    "error",
    "audio_path",
    "engine",
    "device",
    "compute_type",
    "warning",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class TranscriptionStore:
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
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(transcriptions)").fetchall()
            }
            for column in ("engine", "device", "compute_type", "warning"):
                if column not in columns:
                    connection.execute(
                        f"ALTER TABLE transcriptions ADD COLUMN {column} TEXT"  # noqa: S608
                    )

    def create(
        self,
        *,
        id: str,
        filename: str,
        audio_path: str,
        audio_size: int,
        model_id: str,
        task: str,
        language: str,
        options: dict[str, Any],
    ) -> dict[str, Any]:
        now = utc_now()
        with self._write_lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO transcriptions
                    (id, created_at, updated_at, status, stage, progress, filename,
                     audio_path, audio_size, model_id, task, language, options_json)
                VALUES (?, ?, ?, 'queued', '排队中', 0, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    id,
                    now,
                    now,
                    filename,
                    audio_path,
                    audio_size,
                    model_id,
                    task,
                    language,
                    json.dumps(options, ensure_ascii=False),
                ),
            )
        return self.get(id)  # type: ignore[return-value]

    def update(self, transcription_id: str, **fields: Any) -> dict[str, Any] | None:
        clean = {key: value for key, value in fields.items() if key in WRITABLE_FIELDS}
        if not clean:
            return self.get(transcription_id)
        clean["updated_at"] = utc_now()
        assignments = ", ".join(f"{key} = ?" for key in clean)
        values = list(clean.values()) + [transcription_id]
        with self._write_lock, self._connect() as connection:
            connection.execute(
                f"UPDATE transcriptions SET {assignments} WHERE id = ?",  # noqa: S608
                values,
            )
        return self.get(transcription_id)

    def get(self, transcription_id: str, include_audio_path: bool = False) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM transcriptions WHERE id = ?", (transcription_id,)
            ).fetchone()
        return self._row_to_dict(row, include_audio_path) if row else None

    def list(self, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM transcriptions ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [self._row_to_dict(row, include_audio_path=False) for row in rows]

    def delete(self, transcription_id: str) -> dict[str, Any] | None:
        record = self.get(transcription_id, include_audio_path=True)
        if record is None:
            return None
        with self._write_lock, self._connect() as connection:
            connection.execute("DELETE FROM transcriptions WHERE id = ?", (transcription_id,))
        return record

    def mark_interrupted(self) -> int:
        """Jobs cannot survive a process restart. Reflect that in history."""
        with self._write_lock, self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE transcriptions
                SET status = 'failed', stage = '已中断',
                    error = '服务重启，转写任务已中断', updated_at = ?
                WHERE status IN ('queued', 'running', 'cancelling')
                """,
                (utc_now(),),
            )
            return cursor.rowcount

    def _row_to_dict(self, row: sqlite3.Row, include_audio_path: bool) -> dict[str, Any]:
        data = dict(row)
        try:
            segments = json.loads(data.pop("segments_json") or "[]")
        except json.JSONDecodeError:
            segments = []
        try:
            options = json.loads(data.pop("options_json") or "{}")
        except json.JSONDecodeError:
            options = {}
        audio_path = data.pop("audio_path", None)
        public = {
            **data,
            "segments": segments if isinstance(segments, list) else [],
            "options": options if isinstance(options, dict) else {},
            "audio_url": f"/api/transcriptions/{data['id']}/audio",
            "export_urls": {
                fmt: f"/api/transcriptions/{data['id']}/export?format={fmt}"
                for fmt in ("txt", "srt", "vtt", "json")
            },
            "has_audio": bool(audio_path and Path(audio_path).is_file()),
        }
        if include_audio_path:
            public["audio_path"] = audio_path
        return public


def format_timestamp(seconds: float, separator: str = ",") -> str:
    total_ms = max(0, int(round(seconds * 1000)))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{separator}{millis:03d}"


def render_export(record: dict[str, Any], fmt: str) -> tuple[str, str, str]:
    """Return (content, media_type, filename) for a transcript export."""
    base = Path(record["filename"]).stem or "transcript"
    segments: Iterable[dict[str, Any]] = record.get("segments") or []
    if fmt == "txt":
        content = (record.get("text") or "").strip() + "\n"
        return content, "text/plain; charset=utf-8", f"{base}.txt"
    if fmt == "json":
        payload = {
            "id": record["id"],
            "filename": record["filename"],
            "model": record["model_id"],
            "language": record.get("detected_language") or record.get("language"),
            "task": record.get("task"),
            "duration": record.get("duration"),
            "text": record.get("text"),
            "segments": record.get("segments") or [],
            "created_at": record.get("created_at"),
        }
        return (
            json.dumps(payload, ensure_ascii=False, indent=2),
            "application/json; charset=utf-8",
            f"{base}.json",
        )
    if fmt == "vtt":
        lines = ["WEBVTT", ""]
        for index, segment in enumerate(segments, start=1):
            lines.append(str(index))
            lines.append(
                f"{format_timestamp(segment['start'], '.')} --> "
                f"{format_timestamp(segment['end'], '.')}"
            )
            lines.append(str(segment.get("text", "")).strip())
            lines.append("")
        return "\n".join(lines), "text/vtt; charset=utf-8", f"{base}.vtt"
    # Default SRT
    lines = []
    for index, segment in enumerate(segments, start=1):
        lines.append(str(index))
        lines.append(
            f"{format_timestamp(segment['start'])} --> {format_timestamp(segment['end'])}"
        )
        lines.append(str(segment.get("text", "")).strip())
        lines.append("")
    return "\n".join(lines), "application/x-subrip; charset=utf-8", f"{base}.srt"
