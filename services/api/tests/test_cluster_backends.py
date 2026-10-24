"""Optional PostgreSQL/Redis cluster backend integration test.

Set AIBOX_TEST_POSTGRES_DSN (and optionally AIBOX_TEST_REDIS_URL) to run.
"""

from __future__ import annotations

import os
import uuid

import httpx
import pytest

from aibox_api.cluster import create_cluster_manager
from aibox_api.config import AppConfig


@pytest.mark.skipif(
    not os.getenv("AIBOX_TEST_POSTGRES_DSN"),
    reason="AIBOX_TEST_POSTGRES_DSN not configured",
)
def test_postgres_cluster_backend(tmp_path):
    config = AppConfig(
        data_dir=tmp_path / "data",
        cluster_enabled=True,
        cluster_backend="postgres",
        postgres_dsn=os.environ["AIBOX_TEST_POSTGRES_DSN"],
        redis_url=os.getenv("AIBOX_TEST_REDIS_URL"),
    )
    manager = create_cluster_manager(config)
    node_id = f"pg-{uuid.uuid4().hex[:8]}"
    manager.register(
        {
            "id": node_id,
            "url": f"http://{node_id}:9101",
            "capabilities": ["translation"],
            "max_concurrency": 1,
        }
    )
    manager.heartbeat(node_id)
    assert manager.status()["nodes_online"] >= 1

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"result": {"text": "ok"}})

    manager._transport = httpx.MockTransport(handler)
    task = manager.dispatch("translation", {"text": "Hello"})
    assert task["status"] == "completed"
