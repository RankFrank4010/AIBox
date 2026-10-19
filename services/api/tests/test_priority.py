"""Compute-priority and time-window policy tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from aibox_api.config import AppConfig
from aibox_api.runtime import RuntimeCapacityError, RuntimeManager


def make_runtime(tmp_path: Path, **settings) -> RuntimeManager:
    config = AppConfig(data_dir=tmp_path / "data", mock_asr=True)
    if settings:
        config.update_settings(settings)
    return RuntimeManager(config)


def test_services_first_blocks_new_llm(tmp_path):
    runtime = make_runtime(tmp_path)
    runtime.note_request("asr")
    assert runtime.compute_policy() == "services"
    assert runtime._priority("asr") > runtime._priority("llm")
    with pytest.raises(RuntimeCapacityError):
        runtime.admit("llm")


def test_image_demand_counts_as_service_pressure(tmp_path):
    runtime = make_runtime(tmp_path)
    assert runtime.compute_policy() == "balanced"
    runtime.note_request("image")
    assert runtime.service_pressure() is True
    assert runtime.compute_policy() == "services"


def test_scheduled_window_prioritizes_llm(tmp_path):
    runtime = make_runtime(
        tmp_path,
        compute_priority_mode="scheduled",
        compute_priority_windows=[
            {"start": "00:00", "end": "23:59", "days": [0, 1, 2, 3, 4, 5, 6]}
        ],
    )
    runtime.note_request("asr")
    assert runtime.in_llm_priority_window() is True
    assert runtime.compute_policy() == "llm"
    assert runtime._priority("llm") > runtime._priority("asr")
    runtime.admit("llm")


def test_auto_uses_window_then_service_pressure(tmp_path):
    runtime = make_runtime(
        tmp_path,
        compute_priority_mode="auto",
        compute_priority_windows=[
            {"start": "00:00", "end": "23:59", "days": [0, 1, 2, 3, 4, 5, 6]}
        ],
    )
    assert runtime.compute_policy() == "llm"
    runtime.config.update_settings({"compute_priority_windows": []})
    runtime.note_request("tts")
    assert runtime.compute_policy() == "services"
    runtime.admit("tts")
