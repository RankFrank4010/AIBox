"""Multi-device inventory, selection and parallel strategy tests."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from aibox_api.config import AppConfig
from aibox_api.devices import DeviceScheduler
from aibox_api.main import create_app


def make_config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        data_dir=tmp_path / "data",
        mock_asr=True,
        demo_tts=True,
        demo_image=True,
        demo_separation=True,
        demo_video=True,
        demo_llm=True,
        grpc_port=0,
        mrcp_port=0,
    )


def test_device_inventory_and_strategy(tmp_path):
    config = make_config(tmp_path)
    scheduler = DeviceScheduler(config)
    status = scheduler.status()
    assert status["devices"]
    assert status["selected"]
    assert all(item in {d["id"] for d in status["devices"]} for item in status["selected"])

    selected = status["selected"]
    config.update_settings(
        {
            "parallel_strategy": "tensor",
            "parallel_devices": selected,
            "parallel_workers": 3,
        }
    )
    scheduler.refresh()
    llm = scheduler.llm_runtime_config()
    assert llm["strategy"] == "tensor"
    assert llm["split_mode"] == "row"
    assert scheduler.devices_for("llm") == selected
    assert scheduler.status()["workers"] == 3

    config.update_settings({"parallel_strategy": "pipeline"})
    scheduler.refresh()
    assert scheduler.llm_runtime_config()["split_mode"] == "layer"

    config.update_settings({"parallel_strategy": "single"})
    scheduler.refresh()
    assert len(scheduler.devices_for("asr")) == 1


def test_devices_api_and_settings(tmp_path):
    config = make_config(tmp_path)
    with TestClient(create_app(config)) as client:
        devices = client.get("/api/devices").json()
        assert devices["strategies"]
        assert devices["devices"]
        assert client.get("/api/system").json()["devices"]["strategy"]
        patched = client.patch(
            "/api/settings",
            json={"parallel_strategy": "data", "parallel_workers": 2},
        )
        assert patched.status_code == 200
        assert patched.json()["parallel_strategy"] == "data"
        assert client.get("/api/devices").json()["strategy"] == "data"
