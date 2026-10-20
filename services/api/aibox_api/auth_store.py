"""Lightweight built-in accounts, sessions and roles for AIBox WebUI/API."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
import threading
import time
from datetime import datetime, timezone
from typing import Any

from .config import AppConfig

ROLES = {"admin", "operator", "viewer"}
ROLE_ORDER = {"viewer": 1, "operator": 2, "admin": 3}

SCHEMA = """
CREATE TABLE IF NOT EXISTS auth_users (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT,
    role TEXT NOT NULL DEFAULT 'viewer',
    active INTEGER NOT NULL DEFAULT 1,
    external_subject TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS auth_sessions (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_auth_sessions_user ON auth_sessions(user_id);
"""


def _now() -> float:
    return time.time()


def _iso(value: float) -> str:
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat(timespec="seconds")


def hash_password(password: str) -> str:
    if len(password) < 8:
        raise ValueError("密码至少 8 位。")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32
    )
    return f"scrypt$16384$8$1${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str | None) -> bool:
    if not encoded:
        return False
    try:
        algorithm, n, r, p, salt_hex, digest_hex = encoded.split("$", 5)
        if algorithm != "scrypt":
            return False
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


class AuthStore:
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
        connection.execute("PRAGMA synchronous=NORMAL")
        return connection

    def _user(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "username": row["username"],
            "role": row["role"],
            "active": bool(row["active"]),
            "created_at": _iso(row["created_at"]),
            "updated_at": _iso(row["updated_at"]),
        }

    def count_users(self) -> int:
        with self._lock, self._connect() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM auth_users").fetchone()[0])

    def list_users(self) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM auth_users ORDER BY created_at"
            ).fetchall()
        return [self._user(row) for row in rows]

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM auth_users WHERE id = ?", (user_id,)
            ).fetchone()
        return self._user(row) if row else None

    def get_by_username(self, username: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM auth_users WHERE username = ?", (username,)
            ).fetchone()
        return self._user(row) if row else None

    def create_user(
        self,
        username: str,
        password: str | None,
        *,
        role: str = "viewer",
        external_subject: str | None = None,
    ) -> dict[str, Any]:
        username = username.strip()
        if not username:
            raise ValueError("用户名不能为空。")
        if role not in ROLES:
            raise ValueError("角色必须是 admin / operator / viewer。")
        encoded = hash_password(password) if password else None
        now = _now()
        user_id = "u_" + secrets.token_hex(8)
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT INTO auth_users "
                "(id, username, password_hash, role, active, external_subject, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, 1, ?, ?, ?)",
                (user_id, username, encoded, role, external_subject, now, now),
            )
        return self.get_user(user_id) or {}

    def update_user(
        self,
        user_id: str,
        *,
        role: str | None = None,
        active: bool | None = None,
        password: str | None = None,
    ) -> dict[str, Any]:
        if role is not None and role not in ROLES:
            raise ValueError("角色必须是 admin / operator / viewer。")
        updates: list[str] = ["updated_at = ?"]
        values: list[Any] = [_now()]
        if role is not None:
            updates.append("role = ?")
            values.append(role)
        if active is not None:
            updates.append("active = ?")
            values.append(1 if active else 0)
        if password:
            updates.append("password_hash = ?")
            values.append(hash_password(password))
        values.append(user_id)
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                f"UPDATE auth_users SET {', '.join(updates)} WHERE id = ?", values
            )
        if cursor.rowcount == 0:
            raise KeyError("用户不存在。")
        return self.get_user(user_id) or {}

    def delete_user(self, user_id: str) -> None:
        with self._lock, self._connect() as connection:
            cursor = connection.execute("DELETE FROM auth_users WHERE id = ?", (user_id,))
            connection.execute("DELETE FROM auth_sessions WHERE user_id = ?", (user_id,))
        if cursor.rowcount == 0:
            raise KeyError("用户不存在。")

    def authenticate(self, username: str, password: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM auth_users WHERE username = ?", (username.strip(),)
            ).fetchone()
        if not row or not row["active"]:
            return None
        if not verify_password(password, row["password_hash"]):
            return None
        return self._user(row)

    def create_session(self, user_id: str) -> str:
        raw = secrets.token_urlsafe(32)
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        now = _now()
        expires = now + max(3600, self.config.auth_session_hours * 3600)
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT INTO auth_sessions (token_hash, user_id, created_at, expires_at) "
                "VALUES (?, ?, ?, ?)",
                (digest, user_id, now, expires),
            )
        return raw

    def resolve_session(self, token: str | None) -> dict[str, Any] | None:
        if not token:
            return None
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        now = _now()
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT user_id, expires_at FROM auth_sessions WHERE token_hash = ?",
                (digest,),
            ).fetchone()
            if not row:
                return None
            if row["expires_at"] < now:
                connection.execute(
                    "DELETE FROM auth_sessions WHERE token_hash = ?", (digest,)
                )
                return None
        return self.get_user(row["user_id"])

    def revoke_session(self, token: str | None) -> None:
        if not token:
            return
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        with self._lock, self._connect() as connection:
            connection.execute(
                "DELETE FROM auth_sessions WHERE token_hash = ?", (digest,)
            )
