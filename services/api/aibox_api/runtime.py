"""Elastic multi-model residency policy for ASR and TTS.

The current architecture has one model slot per engine type. ASR and TTS can be
resident at the same time when the device budget allows it; under pressure the
manager evicts the least valuable idle slot according to the selected policy.

Policies:

* auto       - keep both when they fit, follow recent demand, idle-unload
* balanced   - keep one ASR and one TTS resident when they fit
* asr_focus  - protect ASR, load TTS on demand, unload idle TTS
* tts_focus  - protect TTS, load ASR on demand, unload idle ASR
* time_slice - periodically focus on the dominant request type
* custom     - user-pinned kinds + explicit limits
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from collections import Counter, deque
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any

from .catalog import get_model
from .config import AppConfig
from .hardware import collect_hardware

logger = logging.getLogger("aibox.runtime")

MODES = ("auto", "balanced", "asr_focus", "tts_focus", "time_slice", "custom")


class RuntimeCapacityError(RuntimeError):
    def __init__(self, message: str, status: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.status = status or {}


@dataclass
class LoadedModel:
    kind: str
    model_id: str
    estimated_gb: float
    loaded_at: float
    last_used: float
    uses: int = 0


@dataclass
class PendingLoad:
    token: str
    kind: str
    model_id: str
    estimated_gb: float
    created_at: float


class RuntimeManager:
    def __init__(self, config: AppConfig, poll_seconds: float = 5.0) -> None:
        self.config = config
        self.poll_seconds = poll_seconds
        self._lock = threading.RLock()
        self._loaded: dict[str, LoadedModel] = {}
        self._pending: dict[str, PendingLoad] = {}
        self._unloaders: dict[str, Callable[[], None]] = {}
        self._busy: Counter[str] = Counter()
        self._demand: dict[str, deque[float]] = {
            "asr": deque(maxlen=2000),
            "tts": deque(maxlen=2000),
            "llm": deque(maxlen=2000),
        }
        self._focus: str = ""
        self._last_switch = time.monotonic()
        self._last_rebalance = time.monotonic()
        self._task: asyncio.Task[None] | None = None
        self._stopped = False
        self._evictions: deque[dict[str, Any]] = deque(maxlen=20)
        self._hardware = collect_hardware()
        self.refresh_budget()

    # --------------------------------------------------------------- lifecycle
    def register(self, kind: str, unload: Callable[[], None]) -> None:
        with self._lock:
            self._unloaders[kind] = unload

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop(), name="aibox-runtime-policy")

    async def stop(self) -> None:
        self._stopped = True
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    def refresh_budget(self) -> None:
        try:
            self._hardware = collect_hardware()
        except Exception:
            logger.debug("hardware refresh failed", exc_info=True)

    # ------------------------------------------------------------------ budget
    def _budget(self) -> dict[str, Any]:
        settings = self.config.settings()
        gpu_reserve = float(settings.get("elastic_gpu_reserve_gb", 1.5))
        ram_reserve = float(settings.get("elastic_ram_reserve_gb", 2.0))
        gpu = self._hardware.get("gpus") or []
        vram = max((float(gpu.get("vram_gb") or 0) for gpu in gpu), default=0.0)
        ram = float(self._hardware.get("memory_gb") or 0.0)
        if self._hardware.get("has_cuda") and vram > 0:
            total = max(0.0, vram - gpu_reserve)
            kind = "vram"
            reserve = gpu_reserve
        else:
            total = max(0.0, ram - ram_reserve)
            kind = "ram"
            reserve = ram_reserve
        return {
            "kind": kind,
            "total_gb": round(total, 1),
            "reserve_gb": round(reserve, 1),
            "vram_gb": round(vram, 1),
            "ram_gb": round(ram, 1),
        }

    def _used_gb(self) -> float:
        used = sum(item.estimated_gb for item in self._loaded.values())
        used += sum(item.estimated_gb for item in self._pending.values())
        return round(used, 1)

    def _available_gb(self) -> float:
        return round(max(0.0, self._budget()["total_gb"] - self._used_gb()), 1)

    # ------------------------------------------------------------------ demand
    def note_request(self, kind: str) -> None:
        if kind not in self._demand:
            return
        with self._lock:
            self._demand[kind].append(time.monotonic())
            if (
                self._effective_mode() == "time_slice"
                and not self._focus
                and not self._loaded
            ):
                self._focus = kind
                self._last_switch = time.monotonic()

    def _demand_counts(self, now: float | None = None) -> dict[str, int]:
        now = now or time.monotonic()
        settings = self.config.settings()
        window = max(30, int(settings.get("elastic_switch_interval_seconds") or 300))
        counts: dict[str, int] = {}
        for kind, values in self._demand.items():
            while values and now - values[0] > window:
                values.popleft()
            counts[kind] = len(values)
        return counts

    def _effective_mode(self) -> str:
        mode = str(self.config.settings().get("elastic_mode") or "auto")
        return mode if mode in MODES else "auto"

    def _pinned_kinds(self) -> set[str]:
        raw = self.config.settings().get("elastic_pinned_kinds") or []
        return {str(kind) for kind in raw if kind in {"asr", "tts"}}

    def _priority(self, kind: str, mode: str | None = None) -> int:
        mode = mode or self._effective_mode()
        pinned = self._pinned_kinds()
        if kind in pinned:
            return 20
        if mode == "asr_focus":
            return 8 if kind == "asr" else 1
        if mode == "tts_focus":
            return 8 if kind == "tts" else 1
        if mode == "time_slice":
            return 8 if kind == self._focus else 1
        if mode == "auto":
            if self._focus == kind:
                return 5
            if self._focus:
                return 2
            return 4
        return 4

    # ------------------------------------------------------------------- loads
    def ensure_capacity(self, kind: str, model_id: str) -> str | None:
        spec = get_model(model_id)
        if spec is None:
            raise RuntimeCapacityError(f"未知模型 {model_id}")
        estimate = max(0.1, float(spec.memory_gb))
        with self._lock:
            current = self._loaded.get(kind)
            if current and current.model_id == model_id:
                current.last_used = time.monotonic()
                return None

            settings = self.config.settings()
            max_loaded = max(1, min(4, int(settings.get("elastic_max_loaded_models") or 4)))
            if kind not in self._loaded and len(self._loaded) + len(self._pending) >= max_loaded:
                if not self._evict_one(protected=kind):
                    raise RuntimeCapacityError(
                        f"常驻模型上限为 {max_loaded} 个，当前模型都在使用或被固定驻留。",
                        self.status(),
                    )
            if current and current.model_id != model_id:
                # The engine will replace its own slot; ask it to free first.
                self._unload_locked(kind)

            budget = self._budget()
            while self._used_gb() + estimate > budget["total_gb"]:
                if not self._evict_for(estimate, requested_kind=kind, mode=self._effective_mode()):
                    raise RuntimeCapacityError(
                        f"显存/内存不足：加载 {spec.name} 需要约 {estimate:.1f} GB，"
                        f"当前可用 {self._available_gb():.1f} GB。"
                        "可在「设置 → 弹性调度」中调整预留或切换模式。",
                        self.status(),
                    )
            token = f"load_{uuid.uuid4().hex[:10]}"
            self._pending[token] = PendingLoad(
                token=token,
                kind=kind,
                model_id=model_id,
                estimated_gb=estimate,
                created_at=time.monotonic(),
            )
            return token

    def commit(self, token: str | None) -> None:
        if token is None:
            return
        with self._lock:
            pending = self._pending.pop(token, None)
            if pending is None:
                return
            now = time.monotonic()
            self._loaded[pending.kind] = LoadedModel(
                kind=pending.kind,
                model_id=pending.model_id,
                estimated_gb=pending.estimated_gb,
                loaded_at=now,
                last_used=now,
            )

    def cancel(self, token: str | None) -> None:
        if token is None:
            return
        with self._lock:
            self._pending.pop(token, None)

    def note_loaded(
        self,
        kind: str,
        model_id: str,
        estimated_gb: float | None = None,
    ) -> None:
        spec = get_model(model_id)
        estimate = float(estimated_gb if estimated_gb is not None else (spec.memory_gb if spec else 0.1))
        with self._lock:
            now = time.monotonic()
            self._loaded[kind] = LoadedModel(
                kind=kind,
                model_id=model_id,
                estimated_gb=max(0.1, estimate),
                loaded_at=now,
                last_used=now,
            )

    def note_unloaded(self, kind: str) -> None:
        with self._lock:
            self._loaded.pop(kind, None)

    def mark_used(self, kind: str) -> None:
        with self._lock:
            if kind in self._loaded:
                self._loaded[kind].last_used = time.monotonic()
                self._loaded[kind].uses += 1

    def begin(self, kind: str) -> None:
        with self._lock:
            self._busy[kind] += 1
            if kind in self._loaded:
                self._loaded[kind].last_used = time.monotonic()

    def end(self, kind: str) -> None:
        with self._lock:
            self._busy[kind] = max(0, self._busy[kind] - 1)
            if kind in self._loaded:
                self._loaded[kind].last_used = time.monotonic()

    def is_loaded(self, kind: str, model_id: str | None = None) -> bool:
        with self._lock:
            loaded = self._loaded.get(kind)
            return loaded is not None and (model_id is None or loaded.model_id == model_id)

    def unload_kind(self, kind: str) -> bool:
        with self._lock:
            return self._unload_locked(kind)

    def _unload_locked(self, kind: str) -> bool:
        loaded = self._loaded.get(kind)
        if loaded is None:
            return False
        if self._busy.get(kind, 0) > 0:
            raise RuntimeCapacityError(f"{kind.upper()} 正在推理，不能立即卸载。")
        unloader = self._unloaders.get(kind)
        try:
            if unloader:
                unloader()
        except Exception:
            logger.exception("unload %s failed", kind)
        self._loaded.pop(kind, None)
        self._evictions.appendleft(
            {
                "kind": kind,
                "model_id": loaded.model_id,
                "at": loaded.last_used,
            }
        )
        return True

    def _evict_one(self, protected: str | None = None) -> bool:
        pinned = self._pinned_kinds()
        candidates = [
            item
            for item in self._loaded.values()
            if item.kind != protected
            and self._busy.get(item.kind, 0) == 0
            and item.kind not in pinned
        ]
        if not candidates:
            return False
        candidates.sort(key=lambda item: item.last_used)
        return self._unload_locked(candidates[0].kind)

    def _evict_for(self, needed_gb: float, requested_kind: str, mode: str) -> bool:
        requested_priority = self._priority(requested_kind, mode)
        candidates = [
            item
            for item in self._loaded.values()
            if item.kind != requested_kind
            and self._busy.get(item.kind, 0) == 0
            and self._priority(item.kind, mode) <= requested_priority
        ]
        if not candidates:
            return False
        pinned = self._pinned_kinds()
        candidates = [
            item
            for item in candidates
            if item.kind not in pinned or self._priority(item.kind, mode) < requested_priority
        ]
        if not candidates:
            return False
        candidates.sort(
            key=lambda item: (
                self._priority(item.kind, mode),
                item.last_used,
            )
        )
        if candidates[0].kind in pinned and self._priority(candidates[0].kind, mode) >= requested_priority:
            return False
        self._unload_locked(candidates[0].kind)
        return True

    # ---------------------------------------------------------------- policies
    async def _loop(self) -> None:
        while not self._stopped:
            try:
                await asyncio.sleep(self.poll_seconds)
                self.rebalance()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("runtime policy loop failed")

    def rebalance(self) -> None:
        with self._lock:
            now = time.monotonic()
            settings = self.config.settings()
            mode = self._effective_mode()
            counts = self._demand_counts(now)
            total = counts.get("asr", 0) + counts.get("tts", 0)
            if mode == "time_slice":
                interval = max(30, int(settings.get("elastic_switch_interval_seconds") or 300))
                if now - self._last_switch >= interval:
                    if total:
                        self._focus = "asr" if counts.get("asr", 0) >= counts.get("tts", 0) else "tts"
                    else:
                        self._focus = "tts" if self._focus == "asr" else "asr"
                    self._last_switch = now
                    logger.info("runtime time-slice focus -> %s (%s)", self._focus, counts)
            elif mode == "auto":
                self._focus = ""
                if total >= 4:
                    if counts.get("asr", 0) >= total * 0.72:
                        self._focus = "asr"
                    elif counts.get("tts", 0) >= total * 0.72:
                        self._focus = "tts"
            elif mode in {"asr_focus", "tts_focus"}:
                self._focus = "asr" if mode == "asr_focus" else "tts"
            elif mode == "custom":
                self._focus = ""
            elif mode == "balanced":
                self._focus = ""

            ttl = int(settings.get("elastic_idle_ttl_seconds") or 0)
            pinned = self._pinned_kinds()
            if ttl > 0:
                for kind, loaded in list(self._loaded.items()):
                    if self._busy.get(kind, 0) > 0:
                        continue
                    if kind in pinned:
                        continue
                    if mode == "asr_focus" and kind == "asr":
                        continue
                    if mode == "tts_focus" and kind == "tts":
                        continue
                    if mode == "time_slice" and kind == self._focus:
                        continue
                    if now - loaded.last_used > ttl:
                        logger.info("runtime idle unload %s/%s", kind, loaded.model_id)
                        self._unload_locked(kind)

            # Remove stale reservations after a failed load.
            for token, pending in list(self._pending.items()):
                if now - pending.created_at > 300:
                    self._pending.pop(token, None)
            self._last_rebalance = now

    # ------------------------------------------------------------------ status
    def status(self) -> dict[str, Any]:
        with self._lock:
            settings = self.config.settings()
            budget = self._budget()
            counts = self._demand_counts()
            return {
                "mode": self._effective_mode(),
                "modes": list(MODES),
                "focus": self._focus,
                "loaded": [
                    {
                        **asdict(item),
                        "busy": self._busy.get(item.kind, 0) > 0,
                        "pinned": item.kind in self._pinned_kinds(),
                    }
                    for item in self._loaded.values()
                ],
                "pending": list(self._pending.values()),
                "budget": {
                    **budget,
                    "used_gb": self._used_gb(),
                    "available_gb": self._available_gb(),
                },
                "demand": {
                    **counts,
                    "window_seconds": int(
                        settings.get("elastic_switch_interval_seconds") or 300
                    ),
                },
                "max_loaded_models": int(
                    settings.get("elastic_max_loaded_models") or 4
                ),
                "idle_ttl_seconds": int(settings.get("elastic_idle_ttl_seconds") or 0),
                "switch_interval_seconds": int(
                    settings.get("elastic_switch_interval_seconds") or 300
                ),
                "pinned_kinds": sorted(self._pinned_kinds()),
                "last_rebalance": self._last_rebalance,
                "evictions": list(self._evictions)[:8],
            }
