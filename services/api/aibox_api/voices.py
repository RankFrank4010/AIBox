"""Voice reference profiles for IndexTTS."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import AppConfig

OPENAI_VOICES = {"alloy", "echo", "fable", "onyx", "nova", "shimmer"}
AUDIO_SUFFIXES = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".opus"}


class VoiceError(RuntimeError):
    pass


@dataclass
class VoiceProfile:
    id: str
    name: str
    language: str
    path: str
    source: str = "custom"
    created_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class VoiceManager:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.builtin_dir = config.repo_root / "examples" / "audio"
        self._builtin = self._builtin_profiles()

    def _builtin_profiles(self) -> dict[str, VoiceProfile]:
        profiles: dict[str, VoiceProfile] = {}
        zh = self.builtin_dir / "chinese-test.wav"
        en = self.builtin_dir / "english-test.wav"
        if en.is_file():
            profiles["default-en"] = VoiceProfile(
                "default-en", "内置英文参考音", "en", str(en), "builtin"
            )
        if zh.is_file():
            profiles["default-zh"] = VoiceProfile(
                "default-zh", "内置中文参考音", "zh", str(zh), "builtin"
            )
        indextts_examples = Path(self.config.indextts_home or "") / "examples"
        if indextts_examples.is_dir():
            for candidate in sorted(indextts_examples.glob("voice_*.wav"))[:2]:
                voice_id = f"indextts-{candidate.stem}"
                profiles.setdefault(
                    voice_id,
                    VoiceProfile(voice_id, f"IndexTTS {candidate.stem}", "auto", str(candidate), "builtin"),
                )
        return profiles

    def _metadata_files(self):
        if not self.config.voices_dir.is_dir():
            return []
        return sorted(self.config.voices_dir.glob("*.json"))

    def list(self) -> list[dict[str, Any]]:
        profiles = [profile.to_dict() for profile in self._builtin.values()]
        for metadata in self._metadata_files():
            try:
                data = json.loads(metadata.read_text(encoding="utf-8"))
                path = Path(data.get("path") or "")
                if path.is_file():
                    profiles.append(
                        VoiceProfile(
                            id=str(data["id"]),
                            name=str(data.get("name") or data["id"]),
                            language=str(data.get("language") or "auto"),
                            path=str(path),
                            source="custom",
                            created_at=data.get("created_at"),
                        ).to_dict()
                    )
            except (OSError, KeyError, ValueError, json.JSONDecodeError):
                continue
        return profiles

    def resolve(self, voice: str | None, text: str) -> VoiceProfile:
        if voice in self._builtin:
            return self._builtin[str(voice)]
        for metadata in self._metadata_files():
            try:
                data = json.loads(metadata.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if str(data.get("id")) == voice:
                path = Path(data.get("path") or "")
                if path.is_file():
                    return VoiceProfile(
                        id=str(data["id"]),
                        name=str(data.get("name") or data["id"]),
                        language=str(data.get("language") or "auto"),
                        path=str(path),
                        source="custom",
                        created_at=data.get("created_at"),
                    )
        if voice in OPENAI_VOICES or not voice or voice == "default":
            use_zh = _contains_cjk(text)
            preferred = "default-zh" if use_zh else "default-en"
            if preferred in self._builtin:
                return self._builtin[preferred]
            fallback = next(iter(self._builtin.values()), None)
            if fallback:
                return fallback
        raise VoiceError(
            "没有可用的参考音频。请上传一段 WAV/MP3 参考音，"
            "或确保 examples/audio/ 中的示例参考音存在。"
        )

    def create(
        self,
        *,
        name: str,
        filename: str,
        content: bytes,
        language: str = "auto",
    ) -> dict[str, Any]:
        suffix = Path(filename or "voice.wav").suffix.lower()
        if suffix not in AUDIO_SUFFIXES:
            raise VoiceError("参考音频仅支持 WAV / MP3 / M4A / FLAC / OGG / OPUS")
        if not content:
            raise VoiceError("参考音频为空")
        if len(content) > 50 * 1024 * 1024:
            raise VoiceError("参考音频不能超过 50 MB")
        voice_id = f"voice-{uuid.uuid4().hex[:10]}"
        target = self.config.voices_dir / f"{voice_id}{suffix}"
        target.write_bytes(content)
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        metadata = {
            "id": voice_id,
            "name": (name or "自定义音色").strip()[:60],
            "language": language or "auto",
            "path": str(target),
            "created_at": now,
        }
        (self.config.voices_dir / f"{voice_id}.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return {**metadata, "source": "custom"}

    def delete(self, voice_id: str) -> bool:
        metadata = self.config.voices_dir / f"{voice_id}.json"
        if not metadata.is_file():
            return False
        try:
            data = json.loads(metadata.read_text(encoding="utf-8"))
            audio = Path(data.get("path") or "")
            if audio.is_file() and self.config.voices_dir.resolve() in audio.resolve().parents:
                audio.unlink(missing_ok=True)
        except (OSError, json.JSONDecodeError):
            pass
        metadata.unlink(missing_ok=True)
        return True


def _contains_cjk(text: str) -> bool:
    return any(
        0x4E00 <= ord(char) <= 0x9FFF
        or 0x3040 <= ord(char) <= 0x30FF
        or 0xAC00 <= ord(char) <= 0xD7AF
        for char in text
    )
