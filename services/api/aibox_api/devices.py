"""Compute-device inventory and task-level scheduling.

AIBox does not assume a homogeneous machine: data-parallel jobs can be placed
on different GPUs, while llama.cpp can split one model across GPUs with tensor
(row) or pipeline (layer) split modes.
"""

from __future__ import annotations

import threading
from dataclasses import asdict, dataclass
from typing import Any

from .config import AppConfig
from .hardware import collect_hardware

STRATEGIES = ("auto", "single", "data", "tensor", "pipeline", "hybrid")
ENGINES = ("asr", "tts", "image", "llm")


@dataclass(frozen=True)
class ComputeDevice:
    id: str
    name: str
    kind: str
    backend: str
    memory_gb: float | None
    index: int | None
    available: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DeviceScheduler:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self._lock = threading.RLock()
        self._active: dict[str, int] = {}
        self._rr = 0
        self._devices = self._discover()

    # ------------------------------------------------------------------ devices
    def _discover(self) -> list[ComputeDevice]:
        devices: list[ComputeDevice] = []
        hardware = collect_hardware()
        gpus = hardware.get("gpus") or []
        accelerators = hardware.get("engines", {}).get("accelerators", {})
        cuda_ready = bool((accelerators.get("cuda") or {}).get("runtime_ready"))
        for index, gpu in enumerate(gpus):
            backend = str(gpu.get("backend") or "").upper()
            if backend == "CUDA":
                devices.append(
                    ComputeDevice(
                        id=f"cuda:{index}",
                        name=str(gpu.get("name") or f"CUDA {index}"),
                        kind="gpu",
                        backend="CUDA",
                        memory_gb=gpu.get("vram_gb"),
                        index=index,
                        available=cuda_ready,
                    )
                )
            elif str(gpu.get("vendor")) == "Apple":
                devices.append(
                    ComputeDevice(
                        id=f"metal:{index}",
                        name=str(gpu.get("name") or "Apple GPU"),
                        kind="gpu",
                        backend="Metal",
                        memory_gb=gpu.get("vram_gb"),
                        index=index,
                        available=True,
                    )
                )
        devices.append(
            ComputeDevice(
                id="cpu",
                name=hardware.get("cpu", {}).get("name") or "CPU",
                kind="cpu",
                backend="CPU",
                memory_gb=hardware.get("memory", {}).get("total_gb"),
                index=None,
            )
        )
        return devices

    def refresh(self) -> None:
        with self._lock:
            self._devices = self._discover()

    def all_devices(self) -> list[ComputeDevice]:
        return list(self._devices)

    def _preferred(self, engine: str) -> str:
        settings = self.config.settings()
        return str(settings.get(f"{engine}_device") or "auto")

    def _configured(self) -> list[str]:
        settings = self.config.settings()
        raw = settings.get("parallel_devices") or []
        valid = {device.id for device in self._devices}
        selected = [str(item) for item in raw if str(item) in valid]
        if selected:
            return selected
        accelerators = [
            device.id for device in self._devices if device.kind != "cpu" and device.available
        ]
        return accelerators or ["cpu"]

    def selected_devices(self) -> list[str]:
        return self._configured()

    def strategy(self) -> str:
        strategy = str(self.config.settings().get("parallel_strategy") or "auto")
        return strategy if strategy in STRATEGIES else "auto"

    def devices_for(self, engine: str) -> list[str]:
        selected = self._configured()
        strategy = self.strategy()
        if engine == "llm" and strategy in {"tensor", "pipeline", "hybrid"}:
            return selected
        preferred = self._preferred(engine)
        if preferred != "auto":
            valid = {device.id for device in self._devices if device.available}
            if preferred in valid:
                return [preferred]
            return selected[:1]
        if strategy == "data":
            return selected
        return selected[:1]

    def choose(self, engine: str) -> str:
        options = self.devices_for(engine)
        if not options:
            return "cpu"
        preferred = self._preferred(engine)
        if preferred != "auto" and preferred in options:
            return preferred
        with self._lock:
            if self.strategy() == "data":
                option = min(
                    options,
                    key=lambda item: (self._active.get(item, 0), options.index(item)),
                )
            else:
                option = options[self._rr % len(options)]
                self._rr += 1
            self._active[option] = self._active.get(option, 0) + 1
            return option

    def release(self, device: str) -> None:
        with self._lock:
            current = self._active.get(device, 0)
            if current <= 1:
                self._active.pop(device, None)
            else:
                self._active[device] = current - 1

    def acquire(self, engine: str) -> str:
        return self.choose(engine)

    def status(self) -> dict[str, Any]:
        selected = self._configured()
        return {
            "strategy": self.strategy(),
            "strategies": list(STRATEGIES),
            "devices": [device.to_dict() for device in self._devices],
            "selected": selected,
            "assignments": {
                engine: self.devices_for(engine) for engine in ENGINES
            },
            "preferred": {
                engine: self._preferred(engine) for engine in ENGINES
            },
            "active": dict(self._active),
            "workers": int(self.config.settings().get("parallel_workers") or 2),
        }

    def llm_runtime_config(self) -> dict[str, Any]:
        selected = self.devices_for("llm")
        indices = []
        for item in selected:
            if item.startswith("cuda:"):
                try:
                    indices.append(int(item.split(":", 1)[1]))
                except ValueError:
                    continue
        strategy = self.strategy()
        split_mode = "layer" if strategy == "pipeline" else "row" if strategy in {"tensor", "hybrid"} else "none"
        return {
            "strategy": strategy,
            "devices": selected,
            "cuda_indices": indices,
            "split_mode": split_mode,
            "tensor_split": [1.0 for _ in indices] if len(indices) > 1 else [],
            "parallel": max(1, int(self.config.settings().get("parallel_workers") or 1)),
        }
