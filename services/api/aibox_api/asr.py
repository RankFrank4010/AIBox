"""Whisper ASR execution for AIBox.

The primary engine is faster-whisper/CTranslate2. The module deliberately keeps
the engine boundary small so future NPU backends (OpenVINO, QNN, Core ML) can be
registered without changing the HTTP API or WebUI.
"""

from __future__ import annotations

import importlib.util
import math
import subprocess
import threading
import time
import wave
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .adapter_runtime import AdapterExecutionError, command_asr, openai_asr
from .config import AppConfig
from .cuda_runtime import cuda_runtime_hint, cuda_runtime_ready, register_for_process
from .runtime import RuntimeCapacityError, RuntimeManager

if TYPE_CHECKING:
    from .community import CommunityRegistry


class AsrUnavailable(RuntimeError):
    pass


class TranscriptionCancelled(RuntimeError):
    pass


ProgressCallback = Callable[[float, str], None]
CancelCheck = Callable[[], bool]


def engine_available() -> bool:
    return importlib.util.find_spec("faster_whisper") is not None


def probe_duration(path: Path) -> float | None:
    """Read media duration without requiring ffprobe when av is available."""
    try:
        import av

        with av.open(str(path)) as container:
            if container.duration:
                return round(float(container.duration) / 1_000_000, 3)
    except Exception:
        pass

    try:
        completed = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if completed.returncode == 0:
            return round(float(completed.stdout.strip()), 3)
    except (OSError, ValueError, subprocess.SubprocessError):
        pass

    if path.suffix.lower() == ".wav":
        try:
            with wave.open(str(path), "rb") as handle:
                return round(handle.getnframes() / handle.getframerate(), 3)
        except (wave.Error, OSError):
            pass
    return None


class WhisperEngine:
    """Lazy, single-slot model cache plus a deterministic mock mode."""

    def __init__(
        self,
        config: AppConfig,
        runtime: RuntimeManager | None = None,
        community: CommunityRegistry | None = None,
    ) -> None:
        self.config = config
        self.runtime = runtime
        self.community = community
        self._model: Any = None
        self._model_key: tuple[str, str, str] | None = None
        self._lock = threading.RLock()
        self._inference_lock = threading.Lock()
        self._active_device: str | None = None
        self._active_compute_type: str | None = None

    @property
    def loaded_model(self) -> dict[str, Any] | None:
        if self._model is None or self._model_key is None:
            return None
        return {
            "path": self._model_key[0],
            "model_id": Path(self._model_key[0]).name,
            "device": self._active_device,
            "compute_type": self._active_compute_type,
        }

    def _resolve_backend(
        self, device: str, compute_type: str
    ) -> tuple[str, str, str | None]:
        warning: str | None = None
        if device == "npu":
            raise AsrUnavailable(
                "NPU 加速正在适配中。当前版本请选择自动 / CPU / CUDA；"
                "驱动与设备已可在系统页查看。"
            )
        if device == "metal":
            raise AsrUnavailable("Apple Metal 的 Whisper 后端尚未启用，请选择 CPU 或自动。")

        resolved_device = device
        if device == "auto":
            register_for_process()
            try:
                import ctranslate2

                if ctranslate2.get_cuda_device_count() > 0 and cuda_runtime_ready():
                    resolved_device = "cuda"
                else:
                    resolved_device = "cpu"
                    if ctranslate2.get_cuda_device_count() > 0:
                        warning = (
                            "已检测到 CUDA 设备，但 cuBLAS / cuDNN 运行时不可用，"
                            "已使用 CPU（int8）。"
                        )
            except Exception:
                resolved_device = "cpu"

        if resolved_device == "cuda":
            register_for_process()
            try:
                import ctranslate2

                if ctranslate2.get_cuda_device_count() <= 0:
                    raise RuntimeError("no CUDA device")
                if not cuda_runtime_ready():
                    raise RuntimeError("missing cuBLAS / cuDNN")
            except Exception:
                if device == "auto":
                    warning = f"{cuda_runtime_hint()} 已回退到 CPU（int8）。"
                    resolved_device = "cpu"
                else:
                    raise AsrUnavailable(
                        f"无法使用 CUDA：{cuda_runtime_hint()}"
                    ) from None

        if resolved_device == "cpu":
            resolved_compute = compute_type if compute_type != "auto" else "int8"
            if resolved_compute not in {"int8", "int8_float32", "float32"}:
                if compute_type != "auto":
                    raise AsrUnavailable("CPU 推理仅支持 int8 / int8_float32 / float32。")
                resolved_compute = "int8"
        else:
            resolved_compute = compute_type if compute_type != "auto" else "float16"
            if resolved_compute not in {"float16", "float32", "int8_float16", "int8"}:
                resolved_compute = "float16"
        return resolved_device, resolved_compute, warning

    def _get_model(
        self,
        model_path: Path,
        device: str,
        compute_type: str,
        status: Callable[[str], None] | None = None,
    ) -> tuple[Any, str, str, str | None]:
        with self._lock:
            resolved_device, resolved_compute, warning = self._resolve_backend(device, compute_type)
            key = (str(model_path), resolved_device, resolved_compute)
            if self._model is not None and self._model_key == key:
                if self.runtime:
                    self.runtime.mark_used("asr")
                return (
                    self._model,
                    self._active_device or resolved_device,
                    self._active_compute_type or resolved_compute,
                    None,
                )

            if status:
                status(
                    "正在加载模型 · "
                    f"{'CUDA' if resolved_device == 'cuda' else 'CPU'} / {resolved_compute}"
                )
            if not engine_available():
                raise AsrUnavailable(
                    "faster-whisper 未安装。请运行 pip install -e 'services/api[asr]' 后重启服务。"
                )
            try:
                from faster_whisper import WhisperModel
            except Exception as exc:  # noqa: BLE001
                raise AsrUnavailable(f"加载 faster-whisper 失败：{exc}") from exc

            if self._model is not None:
                self._model = None
                self._model_key = None
                if self.runtime:
                    self.runtime.note_unloaded("asr")

            reservation = None
            if self.runtime:
                try:
                    reservation = self.runtime.ensure_capacity("asr", model_path.name)
                except RuntimeCapacityError as exc:
                    raise AsrUnavailable(str(exc)) from exc

            try:
                model = WhisperModel(
                    str(model_path),
                    device=resolved_device,
                    compute_type=resolved_compute,
                    cpu_threads=0,
                    num_workers=1,
                )
            except Exception as exc:  # noqa: BLE001
                if device == "auto" and resolved_device == "cuda":
                    warning = f"CUDA 初始化失败，已回退到 CPU（int8）：{exc}"
                    if status:
                        status("CUDA 初始化失败，正在回退到 CPU")
                    resolved_device, resolved_compute = "cpu", "int8"
                    try:
                        model = WhisperModel(
                            str(model_path),
                            device="cpu",
                            compute_type="int8",
                            cpu_threads=0,
                            num_workers=1,
                        )
                    except Exception as fallback_exc:  # noqa: BLE001
                        if self.runtime:
                            self.runtime.cancel(reservation)
                        raise AsrUnavailable(f"模型加载失败：{fallback_exc}") from fallback_exc
                else:
                    if self.runtime:
                        self.runtime.cancel(reservation)
                    raise AsrUnavailable(f"模型加载失败：{exc}") from exc

            self._model = model
            self._model_key = (str(model_path), resolved_device, resolved_compute)
            self._active_device = resolved_device
            self._active_compute_type = resolved_compute
            if self.runtime:
                self.runtime.commit(reservation)
            return model, resolved_device, resolved_compute, warning

    def unload(self) -> None:
        with self._lock:
            self._model = None
            self._model_key = None
            self._active_device = None
            self._active_compute_type = None
        if self.runtime:
            self.runtime.note_unloaded("asr")
        import gc

        gc.collect()

    @property
    def is_busy(self) -> bool:
        return self._inference_lock.locked()

    def transcribe(
        self,
        *,
        audio_path: Path,
        model_path: Path,
        options: dict[str, Any],
        progress: ProgressCallback,
        cancel_check: CancelCheck,
    ) -> dict[str, Any]:
        # CTranslate2 model instances are kept in a single slot. Serialize
        # inference so UI jobs and external transports cannot overlap decoders.
        if self.runtime:
            self.runtime.note_request("asr")
            self.runtime.begin("asr")
        try:
            with self._inference_lock:
                adapter = (
                    self.community.adapter_for(model_path.name)
                    if self.community
                    else None
                )
                if adapter is not None:
                    return self._transcribe_community(
                        adapter=adapter,
                        audio_path=audio_path,
                        model_path=model_path,
                        options=options,
                        progress=progress,
                        cancel_check=cancel_check,
                    )
                return self._transcribe_unlocked(
                    audio_path=audio_path,
                    model_path=model_path,
                    options=options,
                    progress=progress,
                    cancel_check=cancel_check,
                )
        finally:
            if self.runtime:
                self.runtime.end("asr")

    def _transcribe_community(
        self,
        *,
        adapter: Any,
        audio_path: Path,
        model_path: Path,
        options: dict[str, Any],
        progress: ProgressCallback,
        cancel_check: CancelCheck,
    ) -> dict[str, Any]:
        if cancel_check():
            raise TranscriptionCancelled("任务已取消")
        progress(4, f"社区适配器 · {adapter.name}")
        config = adapter.adapter
        timeout = float(config.get("timeout_seconds") or 600)
        try:
            if config.get("type") == "openai-http":
                result = openai_asr(
                    config,
                    audio_path=audio_path,
                    options=options,
                    timeout=timeout,
                )
            elif config.get("type") == "command":
                result = command_asr(
                    config,
                    audio_path=audio_path,
                    model_dir=model_path,
                    options=options,
                    timeout=timeout,
                    cancel_check=cancel_check,
                )
            else:
                raise AsrUnavailable(
                    f"社区适配器 {adapter.name} 的类型不受支持：{config.get('type')}"
                )
        except AdapterExecutionError as exc:
            raise AsrUnavailable(str(exc)) from exc
        if cancel_check():
            raise TranscriptionCancelled("任务已取消")
        progress(98, "社区适配器转写完成")
        return result

    def _transcribe_unlocked(
        self,
        *,
        audio_path: Path,
        model_path: Path,
        options: dict[str, Any],
        progress: ProgressCallback,
        cancel_check: CancelCheck,
    ) -> dict[str, Any]:
        duration = probe_duration(audio_path)
        if self.config.mock_asr:
            return self._transcribe_mock(duration, options, progress, cancel_check)

        if not model_path.is_dir():
            raise AsrUnavailable("模型文件不存在，请在模型页重新下载。")
        register_for_process()

        language = options.get("language") or None
        if language == "auto":
            language = None
        task = options.get("task") or "transcribe"
        beam_size = int(options.get("beam_size") or 5)
        vad_filter = bool(options.get("vad_filter", True))
        word_timestamps = bool(options.get("word_timestamps", False))
        requested_device = str(options.get("device") or "auto")
        requested_compute = str(options.get("compute_type") or "auto")
        warning: str | None = None
        used_device = "cpu"
        used_compute = "int8"

        for attempt in range(2):
            if cancel_check():
                raise TranscriptionCancelled("任务已取消")
            load_stage = 2 if attempt == 0 else 3

            def report_load(message: str, stage: int = load_stage) -> None:
                progress(stage, message)

            model, used_device, used_compute, load_warning = self._get_model(
                model_path,
                requested_device if attempt == 0 else "cpu",
                requested_compute if attempt == 0 else "int8",
                status=report_load,
            )
            if load_warning:
                warning = load_warning
            progress(4, "开始解码音频")

            collected: list[dict[str, Any]] = []
            text_parts: list[str] = []
            last_emit = 0.0
            media_duration = float(duration or 0)
            detected_language = language or "unknown"
            language_probability: float | None = None
            cancelled = False
            try:
                segments_iter, info = model.transcribe(
                    str(audio_path),
                    language=language,
                    task=task,
                    beam_size=beam_size,
                    vad_filter=vad_filter,
                    word_timestamps=word_timestamps,
                    vad_parameters={"min_silence_duration_ms": 500} if vad_filter else None,
                    condition_on_previous_text=False,
                )
                media_duration = float(getattr(info, "duration", 0) or duration or 0)
                detected_language = getattr(info, "language", None) or language or "unknown"
                language_probability = getattr(info, "language_probability", None)
                progress(6, f"识别中 · 语言 {detected_language}")

                for index, segment in enumerate(segments_iter, start=1):
                    if cancel_check():
                        cancelled = True
                        break
                    segment_text = str(segment.text).strip()
                    entry: dict[str, Any] = {
                        "id": index,
                        "start": round(float(segment.start), 3),
                        "end": round(float(segment.end), 3),
                        "text": segment_text,
                    }
                    words = getattr(segment, "words", None)
                    if word_timestamps and words:
                        entry["words"] = [
                            {
                                "word": str(word.word),
                                "start": round(float(word.start), 3),
                                "end": round(float(word.end), 3),
                                "probability": round(float(word.probability), 3)
                                if getattr(word, "probability", None) is not None
                                else None,
                            }
                            for word in words
                        ]
                    collected.append(entry)
                    if segment_text:
                        text_parts.append(segment_text)

                    if media_duration > 0:
                        ratio = min(float(segment.end) / media_duration, 0.985)
                        value = 6 + ratio * 92
                    else:
                        value = min(6 + len(collected) * 2.5, 95)
                    now = time.monotonic()
                    if now - last_emit > 0.2 or value >= 96:
                        timestamp = _format_clock(float(segment.end))
                        progress(
                            value,
                            f"识别中 · {timestamp} / {_format_clock(media_duration)}",
                        )
                        last_emit = now
            except Exception as exc:  # noqa: BLE001
                if (
                    attempt == 0
                    and requested_device == "auto"
                    and used_device == "cuda"
                    and _is_cuda_failure(exc)
                ):
                    warning = f"CUDA 推理不可用，已自动回退到 CPU（int8）：{exc}"
                    self.unload()
                    progress(3, "CUDA 运行时不可用，正在回退到 CPU")
                    continue
                raise AsrUnavailable(f"转写失败：{exc}") from exc

            if cancelled:
                raise TranscriptionCancelled("任务已取消")

            result_text = _join_text(text_parts) if collected else ""
            progress(100, "转写完成")
            return {
                "text": result_text,
                "segments": collected,
                "duration": media_duration or duration,
                "detected_language": detected_language,
                "language_probability": round(float(language_probability), 4)
                if language_probability is not None
                else None,
                "device": used_device,
                "compute_type": used_compute,
                "warning": warning,
                "engine": "faster-whisper",
            }

        raise AsrUnavailable("转写失败：CUDA 与 CPU 后端均未能完成推理")

    def _transcribe_mock(
        self,
        duration: float | None,
        options: dict[str, Any],
        progress: ProgressCallback,
        cancel_check: CancelCheck,
    ) -> dict[str, Any]:
        """Deterministic demo pipeline used by UI development and CI."""
        sample = [
            "欢迎使用 AIBox，一个跨平台的本地 AI 模型工作台。",
            "这段文字由演示转写引擎生成，用于验证界面与导出流程。",
            "安装 faster-whisper 后，选择真实的 Whisper 模型即可获得本地识别结果。",
            "所有音频都留在你的设备上，不会上传到云端。",
        ]
        total = max(duration or 12.0, 6.0)
        segments = []
        count = min(len(sample), max(2, math.ceil(total / 3)))
        step = total / count
        for index in range(count):
            if cancel_check():
                raise TranscriptionCancelled("任务已取消")
            time.sleep(0.25)
            start = round(index * step, 3)
            end = round((index + 1) * step, 3)
            segments.append(
                {
                    "id": index + 1,
                    "start": start,
                    "end": end,
                    "text": sample[index],
                }
            )
            progress((index + 1) / count * 100, f"演示转写 · {_format_clock(end)} / {_format_clock(total)}")
        return {
            "text": " ".join(sample[:count]),
            "segments": segments,
            "duration": total,
            "detected_language": options.get("language") or "zh",
            "language_probability": 0.98,
            "device": "demo",
            "compute_type": "demo",
            "warning": "当前为演示转写引擎，未加载真实模型。",
            "engine": "demo",
        }


def _is_cuda_failure(exc: BaseException) -> bool:
    message = str(exc).lower()
    return any(
        token in message
        for token in (
            "cublas",
            "cudnn",
            "cuda",
            "gpu",
            "dll",
            "device memory",
            "out of memory",
            "no kernel image",
        )
    )


def _format_clock(seconds: float | None) -> str:
    if not seconds or seconds <= 0:
        return "00:00"
    total = int(seconds)
    minutes, secs = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _join_text(parts: list[str]) -> str:
    if not parts:
        return ""
    joined = ""
    for part in parts:
        if not joined:
            joined = part
        elif _is_cjk(part[0]) or _is_cjk(joined[-1]):
            joined += part
        else:
            joined += " " + part
    return joined.strip()


def _is_cjk(char: str) -> bool:
    code = ord(char)
    return (
        0x4E00 <= code <= 0x9FFF
        or 0x3400 <= code <= 0x4DBF
        or 0x3040 <= code <= 0x30FF
        or 0xAC00 <= code <= 0xD7AF
    )
