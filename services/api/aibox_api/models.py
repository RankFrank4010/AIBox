"""Installed-model registry and filesystem helpers for ASR and TTS."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .catalog import all_models, get_model
from .config import AppConfig


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def model_base_dir(config: AppConfig, model_id: str) -> Path:
    spec = get_model(model_id)
    if spec is None:
        raise ValueError(f"Unknown model id: {model_id}")
    if spec.external:
        return config.adapters_dir / "external"
    if spec.kind == "asr":
        return config.models_dir
    if spec.kind == "image":
        return config.image_models_dir
    if spec.kind == "llm":
        return config.llm_models_dir
    return config.tts_models_dir


def safe_model_dir(config: AppConfig, model_id: str) -> Path:
    return model_base_dir(config, model_id) / model_id


def directory_size(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for child in path.rglob("*"):
        try:
            if child.is_file():
                total += child.stat().st_size
        except OSError:
            continue
    return total


def is_model_installed(config: AppConfig, model_id: str) -> bool:
    spec = get_model(model_id)
    if spec is None:
        return False
    if spec.external:
        return True
    model_dir = model_base_dir(config, model_id) / model_id
    if not model_dir.is_dir():
        return False
    for name in spec.required_files:
        file = model_dir / name
        try:
            if not file.is_file() or file.stat().st_size <= 0:
                return False
        except OSError:
            return False
    if spec.kind == "asr":
        try:
            return (model_dir / "model.bin").stat().st_size > 1_000_000
        except OSError:
            return False
    return True


def _read_manifest(model_dir: Path) -> dict[str, Any]:
    path = model_dir / "manifest.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def installed_model(config: AppConfig, model_id: str) -> dict[str, Any] | None:
    spec = get_model(model_id)
    if spec is None or not is_model_installed(config, model_id):
        return None
    if spec.external:
        return {
            **spec.to_dict(),
            "installed": True,
            "installed_at": None,
            "installed_bytes": 0,
            "path": None,
            "files": [],
            "verified": True,
        }
    model_dir = model_base_dir(config, model_id) / model_id
    manifest = _read_manifest(model_dir)
    return {
        **spec.to_dict(),
        "installed": True,
        "installed_at": manifest.get("installed_at"),
        "installed_bytes": directory_size(model_dir),
        "path": str(model_dir),
        "files": manifest.get("files", []),
        "verified": bool(manifest.get("verified", True)),
    }


def list_installed(config: AppConfig, kind: str | None = None) -> list[dict[str, Any]]:
    installed: list[dict[str, Any]] = []
    for spec in all_models():
        if kind and spec.kind != kind:
            continue
        entry = installed_model(config, spec.id)
        if entry:
            installed.append(entry)
    return installed


def delete_model(config: AppConfig, model_id: str) -> bool:
    model_dir = safe_model_dir(config, model_id)
    if not model_dir.exists():
        return False
    shutil.rmtree(model_dir)
    return True


def storage_info(config: AppConfig) -> dict[str, Any]:
    try:
        usage = shutil.disk_usage(config.data_dir)
        disk = {
            "total_bytes": usage.total,
            "free_bytes": usage.free,
            "used_bytes": usage.used,
        }
    except OSError:
        disk = {"total_bytes": None, "free_bytes": None, "used_bytes": None}

    installed = list_installed(config)
    return {
        "data_dir": str(config.data_dir),
        "models_dir": str(config.models_dir),
        "tts_models_dir": str(config.tts_models_dir),
        "image_models_dir": str(config.image_models_dir),
        "llm_models_dir": str(config.llm_models_dir),
        "uploads_dir": str(config.uploads_dir),
        "models_bytes": sum(entry["installed_bytes"] for entry in installed),
        "installed_count": len(installed),
        **disk,
    }
