"""Cluster registry, dispatch and worker runtime tests."""

from __future__ import annotations

from pathlib import Path

import httpx

from aibox_api.cluster import ClusterManager
from aibox_api.config import AppConfig
from aibox_api.worker import ExecuteRequest, WorkerRuntime


def make_manager(tmp_path: Path, handler) -> ClusterManager:
    config = AppConfig(
        data_dir=tmp_path / "data",
        mock_asr=True,
        demo_translation=True,
        demo_ocr=True,
        cluster_enabled=True,
        cluster_max_retries=1,
    )
    return ClusterManager(config, transport=httpx.MockTransport(handler))


def test_cluster_register_and_dispatch(tmp_path):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(
            200,
            json={"result": {"translated": "你好", "provider": "demo"}},
        )

    manager = make_manager(tmp_path, handler)
    manager.register(
        {
            "id": "worker-a",
            "url": "http://worker-a:9101",
            "capabilities": ["translation", "ocr"],
            "max_concurrency": 2,
        }
    )
    assert manager.status()["nodes_online"] == 1
    task = manager.dispatch(
        "translation",
        {"text": "Hello", "source": "en", "target": "zh", "provider": "demo"},
    )
    assert task["status"] == "completed"
    assert task["result"]["translated"] == "你好"
    assert seen == ["http://worker-a:9101/internal/execute"]


def test_cluster_failover_to_second_node(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "worker-a":
            return httpx.Response(500, text="down")
        return httpx.Response(200, json={"result": {"text": "ok"}})

    manager = make_manager(tmp_path, handler)
    for node in ("worker-a", "worker-b"):
        manager.register(
            {
                "id": node,
                "url": f"http://{node}:9101",
                "capabilities": ["translation"],
                "max_concurrency": 1,
            }
        )
    task = manager.dispatch("translation", {"text": "Hello"})
    assert task["status"] == "completed"
    assert task["attempts"] == 2
    assert task["result"]["text"] == "ok"


def test_worker_runtime_executes_translation(tmp_path):
    config = AppConfig(
        data_dir=tmp_path / "data",
        mock_asr=True,
        demo_translation=True,
        demo_ocr=True,
    )
    runtime = WorkerRuntime(
        config,
        node_id="worker-a",
        url="http://worker-a:9101",
        coordinator="http://coordinator",
        capabilities=["translation"],
        max_concurrency=1,
        token=None,
    )
    result = runtime.execute(
        ExecuteRequest(
            task_id="t1",
            kind="translation",
            payload={"text": "Hello", "source": "en", "target": "zh", "provider": "demo"},
        )
    )
    assert result["translated"].startswith("[演示翻译")

def test_worker_config_can_disable_scheduling(tmp_path):
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"result": {"echo": "ok"}})

    manager = make_manager(tmp_path, handler)
    manager.register(
        {
            "id": "worker-off",
            "url": "http://worker-off:9101",
            "capabilities": ["translation"],
            "max_concurrency": 2,
            "work_config": {"enabled": False, "role": "ocr"},
        }
    )
    node = manager.node("worker-off")
    assert node["work_config"]["enabled"] is False
    try:
        manager.dispatch("translation", {"text": "Hello"})
    except Exception as exc:
        assert "没有可用" in str(exc)
    else:
        raise AssertionError("disabled worker must not be scheduled")

    manager.update_config("worker-off", {"enabled": True})
    task = manager.dispatch("translation", {"text": "Hello"})
    assert task["status"] == "completed"
