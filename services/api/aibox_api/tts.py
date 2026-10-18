"""IndexTTS text-to-speech engine and optional worker process bridge.

The IndexTTS runtime has a very heavy, fast-moving dependency set (PyTorch,
transformers, torchaudio). AIBox intentionally runs it in a separate Python
environment. The worker is a small JSON-lines process; the API can unload it
when the elastic runtime policy needs the memory for ASR.
"""

from __future__ import annotations

import gc
import json
import logging
import queue
import shutil
import subprocess
import sys
import threading
import uuid
import wave
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .adapter_runtime import (
    AdapterExecutionError,
    command_tts,
    openai_tts,
)
from .catalog import find_model_by_alias, get_tts_model, tts_models
from .config import AppConfig
from .models import is_model_installed, list_installed
from .runtime import RuntimeCapacityError, RuntimeManager
from .voices import VoiceError, VoiceManager

if TYPE_CHECKING:
    from .community import CommunityRegistry

logger = logging.getLogger("aibox.tts")

TTS_ALIASES = {
    "tts-1": None,
    "tts-1-hd": None,
    "gpt-4o-mini-tts": None,
    "index-tts": "indextts-2.5",
}

MEDIA_TYPES = {
    "mp3": "audio/mpeg",
    "opus": "audio/ogg",
    "aac": "audio/aac",
    "flac": "audio/flac",
    "wav": "audio/wav",
    "pcm": "audio/pcm",
}

SUPPORTED_FORMATS = {"mp3", "opus", "aac", "flac", "wav", "pcm"}


class TtsUnavailable(RuntimeError):
    pass


class TtsEngine:
    def __init__(
        self,
        config: AppConfig,
        runtime: RuntimeManager | None = None,
        community: CommunityRegistry | None = None,
        scheduler: Any | None = None,
    ) -> None:
        self.config = config
        self.runtime = runtime
        self.community = community
        self.scheduler = scheduler
        self.voices = VoiceManager(config)
        self._lock = threading.RLock()
        self._inference_lock = threading.Lock()
        self._worker: subprocess.Popen[str] | None = None
        self._worker_model_id: str | None = None
        self._queue: queue.Queue[str] = queue.Queue()
        self._reader_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None

    # ------------------------------------------------------------------ status
    @property
    def is_busy(self) -> bool:
        return self._inference_lock.locked()

    @property
    def loaded_model_id(self) -> str | None:
        return self._worker_model_id

    def runtime_ready(self) -> bool:
        home = Path(self.config.indextts_home or "")
        if not (home / "indextts").is_dir():
            return False
        python = Path(self.config.indextts_python or sys.executable)
        return python.is_file()

    def status(self) -> dict[str, Any]:
        installed = [entry for entry in list_installed(self.config, "tts")]
        if self.config.demo_tts:
            status = "demo"
        elif not self.runtime_ready():
            status = "runtime-missing"
        elif not installed:
            status = "no-model"
        else:
            status = "ready"
        return {
            "status": status,
            "engine": "indextts",
            "demo": self.config.demo_tts,
            "runtime_ready": self.runtime_ready(),
            "runtime_home": self.config.indextts_home or None,
            "runtime_python": self.config.indextts_python or sys.executable,
            "loaded_model": self._worker_model_id,
            "busy": self.is_busy,
            "installed_models": [entry["id"] for entry in installed],
            "formats": sorted(SUPPORTED_FORMATS),
            "voice_count": len(self.voices.list()),
        }

    # ----------------------------------------------------------------- models
    def resolve_model(self, requested: str | None, allow_demo: bool = True) -> dict[str, Any]:
        installed = {entry["id"]: entry for entry in list_installed(self.config, "tts")}
        raw = (requested or "").strip()
        if raw.lower() in TTS_ALIASES:
            mapped = TTS_ALIASES[raw.lower()]
        elif raw:
            mapped = raw
        else:
            mapped = None
        if mapped is None:
            default = self.config.settings().get("default_tts_model")
            if default in installed:
                return installed[default]
            if installed:
                for candidate in ("indextts-2.5", "indextts-2"):
                    if candidate in installed:
                        return installed[candidate]
                return next(iter(installed.values()))
            if self.config.demo_tts and allow_demo:
                return get_tts_model("indextts-2.5").to_dict()
            raise TtsUnavailable("没有已安装的 IndexTTS 模型，请先在模型库下载。")
        spec = find_model_by_alias(str(mapped), "tts")
        if spec is None:
            available = sorted({model.id for model in tts_models()})
            raise TtsUnavailable(f"未知 TTS 模型 {raw}，可用模型：{', '.join(available)}")
        if spec.id not in installed:
            if self.config.demo_tts and allow_demo:
                return spec.to_dict()
            raise TtsUnavailable(f"TTS 模型 {spec.id} 尚未安装。")
        return installed[spec.id]

    # -------------------------------------------------------------- synthesis
    def synthesize(
        self,
        *,
        text: str,
        model_id: str | None,
        voice: str | None,
        language: str = "auto",
        speed: float = 1.0,
        response_format: str = "wav",
    ) -> dict[str, Any]:
        text = (text or "").strip()
        if not text:
            raise TtsUnavailable("文本为空。")
        if len(text) > 8000:
            raise TtsUnavailable("单次文本不能超过 8000 字符。")
        fmt = (response_format or "wav").lower()
        if fmt not in SUPPORTED_FORMATS:
            raise TtsUnavailable(
                f"不支持的音频格式 {fmt}，可用：{', '.join(sorted(SUPPORTED_FORMATS))}"
            )
        speed = max(0.25, min(4.0, float(speed or 1.0)))
        model = self.resolve_model(model_id)
        model_id = str(model["id"])
        if self.runtime:
            self.runtime.note_request("tts")
        with self._inference_lock:
            if self.runtime:
                self.runtime.begin("tts")
            try:
                adapter = (
                    self.community.adapter_for(model_id)
                    if self.community
                    else None
                )
                if adapter is not None:
                    return self._synthesize_community(
                        adapter=adapter,
                        text=text,
                        model_id=model_id,
                        voice=voice,
                        language=language,
                        speed=speed,
                        fmt=fmt,
                    )
                if self.config.demo_tts:
                    raw_path = self._demo_synthesize(text, speed)
                    warning = "当前为演示 TTS 引擎，输出为提示音，未加载 IndexTTS。"
                else:
                    profile = self.voices.resolve(voice, text)
                    language_code = self._language_code(language, text)
                    self._ensure_worker(model_id)
                    raw_path = self._call_worker(
                        text=text,
                        reference=profile.path,
                        language=language_code,
                        speed=speed,
                        model_id=model_id,
                    )
                    warning = None
                return self._export(raw_path, fmt, speed, model_id, warning)
            except VoiceError as exc:
                raise TtsUnavailable(str(exc)) from exc
            except AdapterExecutionError as exc:
                raise TtsUnavailable(str(exc)) from exc
            except RuntimeCapacityError as exc:
                raise TtsUnavailable(str(exc)) from exc
            finally:
                if self.runtime:
                    self.runtime.end("tts")

    def _synthesize_community(
        self,
        *,
        adapter: Any,
        text: str,
        model_id: str,
        voice: str | None,
        language: str,
        speed: float,
        fmt: str,
    ) -> dict[str, Any]:
        config = adapter.adapter
        timeout = float(config.get("timeout_seconds") or 600)
        output = self.config.tts_outputs_dir / f"community-{uuid.uuid4().hex[:10]}.wav"
        profile = None
        try:
            profile = self.voices.resolve(voice, text)
        except VoiceError:
            profile = None
        model_dir = self.config.tts_models_dir / model_id
        if config.get("model_dir"):
            model_dir = Path(str(config["model_dir"])).expanduser()
        if config.get("type") == "openai-http":
            raw_path = openai_tts(
                config,
                text=text,
                voice=voice,
                speed=speed,
                output_path=output,
                timeout=timeout,
            )
            warning = None
        elif config.get("type") == "command":
            raw_path = command_tts(
                config,
                text=text,
                model_dir=model_dir,
                voice=voice,
                reference=profile.path if profile else None,
                language=self._language_code(language, text),
                speed=speed,
                output_path=output,
                timeout=timeout,
                cancel_check=lambda: False,
            )
            warning = None
        else:
            raise TtsUnavailable(f"社区 TTS 适配器类型不受支持：{config.get('type')}")
        return self._export(raw_path, fmt, speed, model_id, warning)

    def _language_code(self, language: str, text: str) -> str:
        if language and language != "auto":
            return language.split("-")[0].lower()
        for char in text:
            code = ord(char)
            if 0x3040 <= code <= 0x30FF:
                return "ja"
            if 0xAC00 <= code <= 0xD7AF:
                return "ko"
            if 0x4E00 <= code <= 0x9FFF:
                return "zh"
            if 0x0600 <= code <= 0x06FF:
                return "ar"
        return "en"

    # ----------------------------------------------------------------- worker
    def _ensure_worker(self, model_id: str) -> None:
        with self._lock:
            if self._worker is not None and self._worker.poll() is None and self._worker_model_id == model_id:
                return
            if self._worker is not None:
                self._stop_worker()
            if not self.runtime_ready():
                raise TtsUnavailable(
                    "IndexTTS 运行时未安装。请运行 scripts/setup-indextts.ps1 "
                    "并设置 AIBOX_INDEXTTS_HOME / AIBOX_INDEXTTS_PYTHON。"
                )
            if not is_model_installed(self.config, model_id):
                raise TtsUnavailable(f"IndexTTS 模型 {model_id} 文件不完整。")
            model_path = self.config.tts_models_dir / model_id
            reservation = None
            if self.runtime:
                reservation = self.runtime.ensure_capacity("tts", model_id)
            worker_script = Path(__file__).resolve().parent / "tts_worker.py"
            variant = "2.5" if model_id == "indextts-2.5" else "2"
            command = [
                self.config.indextts_python or sys.executable,
                "-u",
                str(worker_script),
                "--repo",
                self.config.indextts_home,
                "--model-dir",
                str(model_path),
                "--variant",
                variant,
            ]
            if self.scheduler:
                command += ["--device", self.scheduler.devices_for("tts")[0]]
            creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            try:
                worker = subprocess.Popen(
                    command,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                    cwd=self.config.indextts_home or str(self.config.repo_root),
                    creationflags=creationflags,
                )
            except OSError as exc:
                if self.runtime:
                    self.runtime.cancel(reservation)
                raise TtsUnavailable(f"无法启动 IndexTTS worker：{exc}") from exc
            self._worker = worker
            self._worker_model_id = model_id
            self._queue = queue.Queue()
            self._start_readers(worker)
            try:
                ready = self._read_message(timeout=900)
                if ready.get("type") != "ready":
                    raise TtsUnavailable(ready.get("error") or "IndexTTS worker 未就绪")
            except Exception:
                self._stop_worker()
                if self.runtime:
                    self.runtime.cancel(reservation)
                raise
            if self.runtime:
                self.runtime.commit(reservation)
            logger.info("IndexTTS worker ready for %s", model_id)

    def _start_readers(self, worker: subprocess.Popen[str]) -> None:
        def read_stdout() -> None:
            assert worker.stdout is not None
            for line in worker.stdout:
                self._queue.put(line.strip())

        def read_stderr() -> None:
            assert worker.stderr is not None
            for line in worker.stderr:
                logger.info("[indextts] %s", line.rstrip())

        self._reader_thread = threading.Thread(target=read_stdout, daemon=True)
        self._stderr_thread = threading.Thread(target=read_stderr, daemon=True)
        self._reader_thread.start()
        self._stderr_thread.start()

    def _read_message(self, timeout: float) -> dict[str, Any]:
        try:
            line = self._queue.get(timeout=timeout)
        except queue.Empty as exc:
            raise TtsUnavailable(f"IndexTTS worker 超时（{timeout:.0f}s）") from exc
        if not line:
            raise TtsUnavailable("IndexTTS worker 已退出。")
        try:
            return json.loads(line)
        except json.JSONDecodeError as exc:
            raise TtsUnavailable(f"IndexTTS worker 返回了非 JSON 输出：{line[:200]}") from exc

    def _call_worker(
        self,
        *,
        text: str,
        reference: str,
        language: str,
        speed: float,
        model_id: str,
    ) -> Path:
        with self._lock:
            worker = self._worker
            if worker is None or worker.poll() is not None:
                raise TtsUnavailable("IndexTTS worker 未运行。")
            command_id = uuid.uuid4().hex[:12]
            output = self.config.tts_outputs_dir / f"{command_id}.wav"
            payload = {
                "id": command_id,
                "text": text,
                "reference": reference,
                "language": language,
                "speed": speed,
                "model_id": model_id,
                "output": str(output),
            }
            try:
                assert worker.stdin is not None
                worker.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
                worker.stdin.flush()
            except (OSError, BrokenPipeError) as exc:
                self._stop_worker()
                raise TtsUnavailable("IndexTTS worker 连接中断。") from exc
            response = self._read_message(timeout=900)
            if response.get("id") not in {None, command_id}:
                raise TtsUnavailable("IndexTTS worker 响应 ID 不匹配。")
            if not response.get("ok"):
                raise TtsUnavailable(response.get("error") or "IndexTTS 推理失败。")
            path = Path(response.get("output") or output)
            if not path.is_file() or path.stat().st_size <= 0:
                raise TtsUnavailable("IndexTTS 没有生成有效音频。")
            return path

    def _stop_worker(self) -> None:
        worker = self._worker
        self._worker = None
        self._worker_model_id = None
        if worker is not None:
            try:
                if worker.stdin:
                    worker.stdin.write('{"type":"shutdown"}\n')
                    worker.stdin.flush()
            except Exception:
                pass
            try:
                worker.wait(timeout=5)
            except subprocess.TimeoutExpired:
                worker.terminate()
                try:
                    worker.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    worker.kill()
        if self.runtime:
            self.runtime.note_unloaded("tts")
        gc.collect()

    def unload(self) -> None:
        with self._lock:
            self._stop_worker()

    # ------------------------------------------------------------------ output
    def _demo_synthesize(self, text: str, speed: float) -> Path:
        del text, speed
        path = self.config.tts_outputs_dir / f"demo-{uuid.uuid4().hex[:10]}.wav"
        template = Path(__file__).resolve().parent / "assets" / "demo-tone.wav"
        if template.is_file():
            shutil.copyfile(template, path)
            return path
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(22050)
            handle.writeframes(b"\x00\x00" * 22050)
        return path

    def _export(
        self,
        raw_path: Path,
        fmt: str,
        speed: float,
        model_id: str,
        warning: str | None,
    ) -> dict[str, Any]:
        needs_atempo = (
            not self.config.demo_tts
            and model_id == "indextts-2"
            and abs(speed - 1.0) > 0.01
        )
        if fmt == "wav":
            target = raw_path.with_name(f"{raw_path.stem}-speed.wav") if needs_atempo else raw_path
        else:
            target = raw_path.with_suffix(f".{fmt}")
        if fmt == "wav" and not needs_atempo:
            if target != raw_path:
                shutil.copyfile(raw_path, target)
                raw_path.unlink(missing_ok=True)
            return {
                "path": target,
                "media_type": MEDIA_TYPES["wav"],
                "format": "wav",
                "warning": warning,
            }
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            if fmt == "wav":
                raise TtsUnavailable("需要 ffmpeg 进行语速处理，请安装 ffmpeg。")
            raise TtsUnavailable(f"需要 ffmpeg 转换 {fmt} 音频，请安装 ffmpeg。")
        command = [ffmpeg, "-y", "-i", str(raw_path)]
        filters = []
        if needs_atempo:
            tempo = max(0.5, min(2.0, speed))
            filters.append(f"atempo={tempo:.4f}")
        if filters:
            command += ["-filter:a", ",".join(filters)]
        if fmt == "pcm":
            command += ["-f", "s16le", "-acodec", "pcm_s16le", "-ar", "24000", "-ac", "1", str(target)]
        else:
            codecs = {
                "mp3": ["-codec:a", "libmp3lame", "-q:a", "2"],
                "opus": ["-codec:a", "libopus", "-b:a", "96k"],
                "aac": ["-codec:a", "aac", "-b:a", "128k"],
                "flac": ["-codec:a", "flac"],
                "wav": ["-codec:a", "pcm_s16le"],
            }
            command += codecs.get(fmt, []) + [str(target)]
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        if completed.returncode != 0 or not target.is_file():
            raise TtsUnavailable(f"音频格式转换失败：{completed.stderr[-400:]}")
        raw_path.unlink(missing_ok=True)
        return {
            "path": target,
            "media_type": MEDIA_TYPES.get(fmt, "application/octet-stream"),
            "format": fmt,
            "warning": warning,
        }

    def status_for_ui(self) -> dict[str, Any]:
        return self.status()
