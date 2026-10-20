"""Multi-node compute fabric for AIBox.

The coordinator keeps a small lease-based registry in SQLite. Workers register
their capabilities and advertise an internal execute endpoint; the scheduler
picks the least-loaded healthy node and retries another node on failure.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx

from .config import AppConfig

SCHEMA = """
CREATE TABLE IF NOT EXISTS cluster_nodes (
    id TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    capabilities_json TEXT NOT NULL DEFAULT '[]',
    labels_json TEXT NOT NULL DEFAULT '{}',
    max_concurrency INTEGER NOT NULL DEFAULT 1,
    state TEXT NOT NULL DEFAULT 'online',
    version TEXT NOT NULL DEFAULT '1.0',
    registered_at REAL NOT NULL,
    last_heartbeat REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS cluster_tasks (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT,
    status TEXT NOT NULL DEFAULT 'queued',
    node_id TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cluster_tasks_status
    ON cluster_tasks(status, created_at DESC);
"""


class ClusterError(RuntimeError):
    pass


def _now() -> float:
    return time.time()


def _iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat(timespec="seconds")


def _node_public(row: sqlite3.Row, active: int = 0) -> dict[str, Any]:
    return {
        "id": row["id"],
        "url": row["url"],
        "capabilities": json.loads(row["capabilities_json"] or "[]"),
        "labels": json.loads(row["labels_json"] or "{}"),
        "max_concurrency": row["max_concurrency"],
        "state": row["state"],
        "version": row["version"],
        "active_tasks": active,
        "registered_at": _iso(row["registered_at"]),
        "last_heartbeat": _iso(row["last_heartbeat"]),
    }


class ClusterManager:
    def __init__(
        self,
        config: AppConfig,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.config = config
        self.database_path = config.database_path
        self._lock = threading.RLock()
        self._transport = transport
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

    # ------------------------------------------------------------------ registry
    def register(self, payload: dict[str, Any]) -> dict[str, Any]:
        node_id = str(payload.get("id") or "").strip()
        if not node_id or len(node_id) > 128:
            raise ClusterError("node id 非法。")
        url = str(payload.get("url") or "").strip().rstrip("/")
        if not url.startswith(("http://", "https://")):
            raise ClusterError("node url 必须是 http(s)。")
        capabilities = payload.get("capabilities") or []
        if not isinstance(capabilities, list):
            raise ClusterError("capabilities 必须是数组。")
        capabilities = [str(item) for item in capabilities][:32]
        labels = payload.get("labels") or {}
        if not isinstance(labels, dict):
            labels = {}
        max_concurrency = max(1, min(64, int(payload.get("max_concurrency") or 1)))
        now = _now()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO cluster_nodes (
                    id, url, capabilities_json, labels_json, max_concurrency,
                    state, version, registered_at, last_heartbeat
                ) VALUES (?, ?, ?, ?, ?, 'online', ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    url = excluded.url,
                    capabilities_json = excluded.capabilities_json,
                    labels_json = excluded.labels_json,
                    max_concurrency = excluded.max_concurrency,
                    state = 'online',
                    version = excluded.version,
                    last_heartbeat = excluded.last_heartbeat
                """,
                (
                    node_id,
                    url,
                    json.dumps(capabilities, ensure_ascii=False),
                    json.dumps(labels, ensure_ascii=False),
                    max_concurrency,
                    str(payload.get("version") or "1.0"),
                    now,
                    now,
                ),
            )
        return self.node(node_id) or {}

    def heartbeat(self, node_id: str) -> dict[str, Any]:
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                "UPDATE cluster_nodes SET last_heartbeat = ?, state = 'online' "
                "WHERE id = ? AND state != 'draining'",
                (_now(), node_id),
            )
        if cursor.rowcount == 0:
            raise ClusterError("节点不存在或已 draining。")
        return self.node(node_id) or {}

    def drain(self, node_id: str) -> dict[str, Any]:
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                "UPDATE cluster_nodes SET state = 'draining' WHERE id = ?",
                (node_id,),
            )
        if cursor.rowcount == 0:
            raise ClusterError("节点不存在。")
        return self.node(node_id) or {}

    def prune(self) -> None:
        threshold = _now() - max(5, self.config.cluster_node_ttl_seconds)
        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE cluster_nodes SET state = 'offline' "
                "WHERE state = 'online' AND last_heartbeat < ?",
                (threshold,),
            )

    def _active_counts(self, connection: sqlite3.Connection) -> dict[str, int]:
        rows = connection.execute(
            "SELECT node_id, COUNT(*) AS count FROM cluster_tasks "
            "WHERE status IN ('assigned', 'running') AND node_id IS NOT NULL "
            "GROUP BY node_id"
        ).fetchall()
        return {row["node_id"]: int(row["count"]) for row in rows}

    def nodes(self, include_offline: bool = True) -> list[dict[str, Any]]:
        self.prune()
        with self._lock, self._connect() as connection:
            clause = "" if include_offline else "WHERE state != 'offline'"
            rows = connection.execute(
                f"SELECT * FROM cluster_nodes {clause} ORDER BY id"
            ).fetchall()
            active = self._active_counts(connection)
        return [_node_public(row, active.get(row["id"], 0)) for row in rows]

    def node(self, node_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM cluster_nodes WHERE id = ?", (node_id,)
            ).fetchone()
            active = self._active_counts(connection)
        return _node_public(row, active.get(node_id, 0)) if row else None

    def status(self) -> dict[str, Any]:
        self.prune()
        nodes = self.nodes()
        online = [node for node in nodes if node["state"] in {"online", "draining"}]
        with self._lock, self._connect() as connection:
            task_rows = connection.execute(
                "SELECT status, COUNT(*) AS count FROM cluster_tasks GROUP BY status"
            ).fetchall()
        return {
            "enabled": self.config.cluster_enabled,
            "token_required": bool(self.config.cluster_token),
            "node_ttl_seconds": self.config.cluster_node_ttl_seconds,
            "max_retries": self.config.cluster_max_retries,
            "nodes_online": len([node for node in online if node["state"] == "online"]),
            "nodes_total": len(nodes),
            "nodes": nodes,
            "task_counts": {row["status"]: row["count"] for row in task_rows},
        }

    # ------------------------------------------------------------------ tasks
    def _create_task(self, kind: str, payload: dict[str, Any]) -> str:
        task_id = f"ct_{uuid.uuid4().hex[:14]}"
        now = _now()
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT INTO cluster_tasks "
                "(id, kind, payload_json, status, created_at, updated_at) "
                "VALUES (?, ?, ?, 'queued', ?, ?)",
                (task_id, kind, json.dumps(payload, ensure_ascii=False), now, now),
            )
        return task_id

    def task(self, task_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM cluster_tasks WHERE id = ?", (task_id,)
            ).fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "kind": row["kind"],
            "status": row["status"],
            "node_id": row["node_id"],
            "attempts": row["attempts"],
            "error": row["error"],
            "result": json.loads(row["result_json"]) if row["result_json"] else None,
            "created_at": _iso(row["created_at"]),
            "updated_at": _iso(row["updated_at"]),
        }

    def tasks(self, limit: int = 50) -> list[dict[str, Any]]:
        limit = max(1, min(200, int(limit)))
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT id FROM cluster_tasks ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [task for row in rows if (task := self.task(row["id"]))]

    def _candidates(self, kind: str) -> list[dict[str, Any]]:
        self.prune()
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM cluster_nodes WHERE state = 'online'"
            ).fetchall()
            active = self._active_counts(connection)
        candidates = [
            _node_public(row, active.get(row["id"], 0))
            for row in rows
            if kind in json.loads(row["capabilities_json"] or "[]")
            and active.get(row["id"], 0) < row["max_concurrency"]
        ]
        candidates.sort(key=lambda item: (item["active_tasks"], item["last_heartbeat"]))
        return candidates

    def dispatch(
        self,
        kind: str,
        payload: dict[str, Any],
        *,
        timeout: float = 180,
    ) -> dict[str, Any]:
        if not self.config.cluster_enabled:
            raise ClusterError("集群调度未启用。")
        task_id = self._create_task(kind, payload)
        candidates = self._candidates(kind)
        if not candidates:
            self._finish_task(task_id, "failed", error="没有可用的集群节点。")
            raise ClusterError("没有可用的集群节点。")
        attempts = max(1, self.config.cluster_max_retries + 1)
        last_error = ""
        for index, node in enumerate(candidates[:attempts]):
            self._update_task(task_id, "running", node["id"], index + 1)
            headers = {"X-AIBox-Protocol": "1.0"}
            if self.config.cluster_token:
                headers["Authorization"] = f"Bearer {self.config.cluster_token}"
            try:
                with httpx.Client(timeout=timeout, transport=self._transport) as client:
                    response = client.post(
                        f"{node['url']}/internal/execute",
                        headers=headers,
                        json={"task_id": task_id, "kind": kind, "payload": payload},
                    )
                    response.raise_for_status()
                    body = response.json()
                result = body.get("result") if isinstance(body, dict) else body
                self._finish_task(task_id, "completed", result=result)
                return self.task(task_id) or {}
            except (httpx.HTTPError, ValueError, OSError) as exc:
                last_error = str(exc)
                self._update_task(task_id, "failed", node["id"], index + 1, last_error)
        self._finish_task(task_id, "failed", error=last_error or "all nodes failed")
        raise ClusterError(last_error or "所有集群节点均失败。")

    def _update_task(
        self,
        task_id: str,
        status: str,
        node_id: str | None = None,
        attempts: int | None = None,
        error: str | None = None,
    ) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE cluster_tasks SET status = ?, node_id = COALESCE(?, node_id), "
                "attempts = COALESCE(?, attempts), error = ?, updated_at = ? WHERE id = ?",
                (status, node_id, attempts, error, _now(), task_id),
            )

    def _finish_task(
        self,
        task_id: str,
        status: str,
        *,
        result: Any = None,
        error: str | None = None,
    ) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE cluster_tasks SET status = ?, result_json = ?, error = ?, "
                "updated_at = ? WHERE id = ?",
                (
                    status,
                    json.dumps(result, ensure_ascii=False) if result is not None else None,
                    error,
                    _now(),
                    task_id,
                ),
            )
