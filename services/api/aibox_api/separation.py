"""Vocal / background separation engine.

Native providers are executed in a separate Python environment so PyTorch /
Demucs / audio-separator do not conflict with faster-whisper. The API only
orchestrates subprocesses and normalizes the resulting stems.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from .config import AppConfig
from .separation_catalog import (
    SEPARATION_MODELS,
    SeparationModel,
    get_separation_model,
)

logger = logging.getLogger("aibox.separation")

STEM_LABELS = {
    "vocals": "人声",
    "instrumental": "伴奏（无人声）",
    "no_vocals": "伴奏（无人声）",
    "drums": "鼓",
    "bass": "贝斯",
    "other": "其他乐器",
}

MODES = {
    "instrumental": "去人声 / 保留伴奏",
    "vocals": "去背景 / 保留人声",
    "stems": "全部分轨",
}


class SeparationUnavailable(RuntimeError):
    pass


class SeparationEngine:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self._demucs_ready: bool | None = None
        self._audio_separator_ready: bool | None = None

    # ------------------------------------------------------------------ status
    def _python(self) -> Path:
        return Path(self.config.separation_python or sys.executable)

    def _module_ready(self, module: str) -> bool:
        python = self._python()
        if not python.is_file():
            return False
        try:
            completed = subprocess.run(
                [str(python), "-c", f"import {module}"],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            return completed.returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False

    def demucs_ready(self) -> bool:
        if self._demucs_ready is None:
            self._demucs_ready = self._module_ready("demucs")
        return bool(self._demucs_ready)

    def audio_separator_ready(self) -> bool:
        if self._audio_separator_ready is None:
            exe = shutil.which("audio-separator")
            self._audio_separator_ready = bool(exe) or self._module_ready(
                "audio_separator"
            )
        return bool(self._audio_separator_ready)

    def status(self) -> dict[str, Any]:
        return {
            "demo": self.config.demo_separation,
            "python": str(self._python()),
            "device": self.config.separation_device,
            "demucs_ready": self.demucs_ready(),
            "audio_separator_ready": self.audio_separator_ready(),
            "models": [
                {
                    **model.to_dict(),
                    "available": self._model_available(model),
                }
                for model in self.models()
            ],
            "modes": [
                {"id": key, "label": label}
                for key, label in MODES.items()
            ],
        }

    def models(self) -> tuple[SeparationModel, ...]:
        return SEPARATION_MODELS

    def _model_available(self, model: SeparationModel) -> bool:
        if self.config.demo_separation:
            return True
        if model.engine == "demucs":
            return self.demucs_ready()
        if model.engine == "audio-separator":
            return self.audio_separator_ready()
        return False

    def resolve_model(self, model_id: str | None) -> SeparationModel:
        model = get_separation_model(model_id or "htdemucs")
        if model is None:
            available = ", ".join(item.id for item in SEPARATION_MODELS)
            raise SeparationUnavailable(f"未知分离模型 {model_id}，可用：{available}")
        return model

    # ----------------------------------------------------------------- separate
    def separate(
        self,
        *,
        audio_path: Path,
        model_id: str | None,
        mode: str,
        job_id: str,
        progress=None,
    ) -> dict[str, Any]:
        if mode not in MODES:
            raise SeparationUnavailable(f"未知分离模式 {mode}")
        model = self.resolve_model(model_id)
        provider = self._provider(model)
        if provider not in {"demo", "demucs", "audio-separator"}:
            raise SeparationUnavailable(f"未知分离 provider {provider}")
        output_dir = self.config.separation_outputs_dir / job_id
        output_dir.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        if progress:
            progress(5, f"准备 {model.name}")
        try:
            if provider == "demo":
                demo_outputs = self._demo(audio_path, mode, output_dir)
                outputs = self._select_outputs(
                    {
                        item["role"]: Path(item["path"])
                        for item in demo_outputs
                    },
                    mode,
                )
            elif provider == "demucs":
                outputs = self._run_demucs(
                    model, audio_path, mode, output_dir, progress
                )
            else:
                outputs = self._run_audio_separator(
                    model, audio_path, mode, output_dir, progress
                )
        except SeparationUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001
            raise SeparationUnavailable(f"分离失败：{exc}") from exc
        if not outputs:
            raise SeparationUnavailable("分离完成但没有生成音频文件")
        if progress:
            progress(96, "整理分轨")
        return {
            "outputs": outputs,
            "model_id": model.id,
            "provider": provider,
            "mode": mode,
            "duration": time.monotonic() - started,
        }

    def _provider(self, model: SeparationModel) -> str:
        if self.config.demo_separation:
            return "demo"
        if model.engine == "demucs" and self.demucs_ready():
            return "demucs"
        if model.engine == "audio-separator" and self.audio_separator_ready():
            return "audio-separator"
        raise SeparationUnavailable(
            f"{model.name} 的运行时未安装。请安装 Demucs 或 audio-separator，"
            "设置 AIBOX_SEPARATION_PYTHON 后重启；也可以先设置 AIBOX_DEMO_SEPARATION=1。"
        )

    # -------------------------------------------------------------------- demo
    def _demo(
        self, audio_path: Path, mode: str, output_dir: Path
    ) -> list[dict[str, Any]]:
        roles = ["instrumental", "vocals"] if mode != "stems" else [
            "vocals",
            "drums",
            "bass",
            "other",
        ]
        outputs: list[dict[str, Any]] = []
        ffmpeg = shutil.which("ffmpeg")
        for role in roles:
            target = output_dir / f"{role}.wav"
            filters = {
                "vocals": "highpass=f=180,lowpass=f=9000",
                "instrumental": "lowpass=f=14000",
                "drums": "highpass=f=80,lowpass=f=1200",
                "bass": "lowpass=f=300",
                "other": "highpass=f=3000",
            }
            if ffmpeg and audio_path.suffix.lower() not in {".wav", ".flac"}:
                command = [
                    ffmpeg,
                    "-y",
                    "-i",
                    str(audio_path),
                    "-af",
                    filters.get(role, "anull"),
                    "-ar",
                    "44100",
                    "-ac",
                    "2",
                    str(target),
                ]
                completed = subprocess.run(
                    command, capture_output=True, text=True, check=False
                )
                if completed.returncode != 0:
                    shutil.copyfile(audio_path, target)
            elif ffmpeg:
                command = [
                    ffmpeg,
                    "-y",
                    "-i",
                    str(audio_path),
                    "-af",
                    filters.get(role, "anull"),
                    str(target),
                ]
                completed = subprocess.run(
                    command, capture_output=True, text=True, check=False
                )
                if completed.returncode != 0:
                    shutil.copyfile(audio_path, target)
            else:
                shutil.copyfile(audio_path, target)
            outputs.append(
                {
                    "role": role,
                    "label": STEM_LABELS.get(role, role),
                    "path": str(target),
                }
            )
        return outputs

    # ------------------------------------------------------------------ demucs
    def _run_demucs(
        self,
        model: SeparationModel,
        audio_path: Path,
        mode: str,
        output_dir: Path,
        progress,
    ) -> list[dict[str, Any]]:
        command = [
            str(self._python()),
            "-m",
            "demucs.separate",
            "-n",
            model.model_arg,
            "-o",
            str(output_dir),
        ]
        if self.config.separation_device and self.config.separation_device != "auto":
            command += ["-d", self.config.separation_device]
        if mode != "stems":
            command += ["--two-stems=vocals"]
        command.append(str(audio_path))
        if progress:
            progress(12, "Demucs 正在分离")
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=3600,
            check=False,
        )
        if completed.returncode != 0:
            raise SeparationUnavailable(
                f"Demucs 失败（退出码 {completed.returncode}）：{completed.stderr[-1200:]}"
            )
        files = {
            path.stem.lower(): path
            for path in output_dir.rglob("*.wav")
            if path.is_file()
        }
        if not files:
            raise SeparationUnavailable("Demucs 没有生成 WAV 分轨")
        return self._select_outputs(files, mode)

    # ---------------------------------------------------------- audio-separator
    def _run_audio_separator(
        self,
        model: SeparationModel,
        audio_path: Path,
        mode: str,
        output_dir: Path,
        progress,
    ) -> list[dict[str, Any]]:
        exe = shutil.which("audio-separator")
        if exe:
            command = [exe]
        else:
            command = [str(self._python()), "-m", "audio_separator.cli"]
        command += [
            str(audio_path),
            "--model_filename",
            model.filename or model.model_arg,
            "--output_dir",
            str(output_dir),
        ]
        if self.config.separation_models_dir.is_dir():
            command += ["--model_file_dir", str(self.config.separation_models_dir)]
        if progress:
            progress(12, "UVR / MDX 正在分离")
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=3600,
            check=False,
        )
        if completed.returncode != 0:
            raise SeparationUnavailable(
                f"audio-separator 失败（退出码 {completed.returncode}）：{completed.stderr[-1200:]}"
            )
        files: dict[str, Path] = {}
        for path in output_dir.rglob("*.wav"):
            lower = path.stem.lower()
            if "vocal" in lower:
                files["vocals"] = path
            elif "instrument" in lower or "karaoke" in lower:
                files["instrumental"] = path
            elif "drum" in lower:
                files["drums"] = path
            elif "bass" in lower:
                files["bass"] = path
            elif "other" in lower:
                files["other"] = path
        if not files:
            raise SeparationUnavailable("audio-separator 没有生成 WAV 分轨")
        return self._select_outputs(files, mode)

    # ------------------------------------------------------------------ output
    def _select_outputs(
        self, files: dict[str, Path], mode: str
    ) -> list[dict[str, Any]]:
        aliases = {
            "no_vocals": "instrumental",
            "novocals": "instrumental",
            "accompaniment": "instrumental",
        }
        normalized: dict[str, Path] = {}
        for key, path in files.items():
            role = aliases.get(key, key)
            if role in {"vocals", "instrumental", "drums", "bass", "other"}:
                normalized[role] = path
        if mode == "instrumental":
            selected = ["instrumental"] if "instrumental" in normalized else (
                ["no_vocals"] if "no_vocals" in normalized else []
            )
        elif mode == "vocals":
            selected = ["vocals"] if "vocals" in normalized else []
        else:
            selected = [
                role
                for role in ("vocals", "drums", "bass", "other", "instrumental")
                if role in normalized
            ]
        if not selected and mode == "stems":
            selected = sorted(normalized)
        if not selected:
            raise SeparationUnavailable(
                f"模型没有返回模式 {mode} 需要的分轨：{', '.join(files)}"
            )
        return [
            {
                "role": role,
                "label": STEM_LABELS.get(role, role),
                "path": str(normalized[role]),
            }
            for role in selected
        ]
