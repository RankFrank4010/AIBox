"""Runtime residency and capacity policy tests."""

from __future__ import annotations

import pytest

from aibox_api.config import AppConfig
from aibox_api.runtime import RuntimeCapacityError, RuntimeManager


def test_runtime_evicts_idle_model_and_respects_busy(tmp_path, monkeypatch):
    fake_hardware = {
        "has_cuda": True,
        "memory_gb": 32.0,
        "gpus": [{"vram_gb": 12.0}],
    }
    monkeypatch.setattr(
        "aibox_api.runtime.collect_hardware", lambda: fake_hardware
    )
    config = AppConfig(data_dir=tmp_path / "data", demo_tts=True)
    config.update_settings(
        {
            "elastic_mode": "balanced",
            "elastic_gpu_reserve_gb": 1.0,
            "elastic_max_loaded_models": 1,
        }
    )
    runtime = RuntimeManager(config)
    unloaded: list[str] = []
    runtime.register("asr", lambda: unloaded.append("asr"))
    runtime.register("tts", lambda: unloaded.append("tts"))

    token = runtime.ensure_capacity("asr", "small")
    runtime.commit(token)
    assert runtime.is_loaded("asr", "small")
    assert runtime.status()["budget"]["kind"] == "vram"

    runtime.begin("asr")
    with pytest.raises(RuntimeCapacityError):
        runtime.ensure_capacity("tts", "indextts-2.5")
    runtime.end("asr")

    token = runtime.ensure_capacity("tts", "indextts-2.5")
    runtime.commit(token)
    assert runtime.is_loaded("tts", "indextts-2.5")
    assert not runtime.is_loaded("asr")
    assert unloaded == ["asr"]


def test_runtime_rejects_models_over_budget(tmp_path, monkeypatch):
    fake_hardware = {
        "has_cuda": True,
        "memory_gb": 16.0,
        "gpus": [{"vram_gb": 4.0}],
    }
    monkeypatch.setattr(
        "aibox_api.runtime.collect_hardware", lambda: fake_hardware
    )
    config = AppConfig(data_dir=tmp_path / "data", demo_tts=True)
    config.update_settings({"elastic_gpu_reserve_gb": 1.0})
    runtime = RuntimeManager(config)
    with pytest.raises(RuntimeCapacityError):
        runtime.ensure_capacity("tts", "indextts-2.5")
