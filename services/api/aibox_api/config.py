"""Runtime configuration and persistent application settings for AIBox."""

from __future__ import annotations

import json
import os
import platform
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

APP_NAME = "AIBox"
APP_VERSION = "0.1.0"


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _valid_clock(value: str) -> bool:
    try:
        hour_text, minute_text = value.split(":", 1)
        hour, minute = int(hour_text), int(minute_text)
    except (ValueError, AttributeError):
        return False
    return 0 <= hour <= 23 and 0 <= minute <= 59


def default_data_dir() -> Path:
    """Return the per-user AIBox data directory for the current platform."""
    override = os.getenv("AIBOX_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()

    system = platform.system()
    if system == "Windows":
        base = os.getenv("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "AIBox"
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "AIBox"
    base = os.getenv("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "aibox"


def detect_repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


DEFAULT_SETTINGS: dict[str, Any] = {
    "default_model": None,
    "default_tts_model": None,
    "tts_default_voice": "default",
    "default_image_model": None,
    "image_provider": "auto",
    "image_steps": 28,
    "image_guidance": 3.5,
    "default_llm_model": None,
    "llm_provider": "auto",
    "llm_temperature": 0.7,
    "llm_max_tokens": 1024,
    "llm_system_prompt": "你是 AIBox 的本地 AI 助手，回答准确、简洁。",
    "parallel_strategy": "auto",
    "parallel_devices": [],
    "parallel_workers": 2,
    "asr_device": "auto",
    "tts_device": "auto",
    "image_device": "auto",
    "llm_device": "auto",
    "default_training_model": "Qwen/Qwen3-8B",
    "training_method": "qlora",
    "compute_priority_mode": "services_first",
    "compute_priority_windows": [],
    "translation_provider": "auto",
    "libre_url": "",
    "libre_api_key": "",
    "index_url": "",
    "index_api_key": "",
    "index_model": "Index-Translate",
    "hunyuan_url": "",
    "hunyuan_api_key": "",
    "hunyuan_model": "hunyuan-mt2",
    "argos_command": "argos-translate",
    "ocr_provider": "auto",
    "glm_base_url": "https://open.bigmodel.cn/api/paas/v4",
    "glm_api_key": "",
    "glm_ocr_model": "glm-ocr",
    "ocr_openai_url": "",
    "ocr_openai_api_key": "",
    "ocr_openai_model": "gpt-4o-mini",
    "tesseract_command": "tesseract",
    "language": "auto",
    "task": "transcribe",
    "device": "auto",
    "compute_type": "auto",
    "beam_size": 5,
    "vad_filter": True,
    "word_timestamps": False,
    "theme": "dark",
    "max_concurrent_jobs": 1,
    "keep_audio": True,
    "elastic_mode": "auto",
    "elastic_idle_ttl_seconds": 600,
    "elastic_switch_interval_seconds": 300,
    "elastic_max_loaded_models": 4,
    "elastic_gpu_reserve_gb": 1.5,
    "elastic_ram_reserve_gb": 2.0,
    "elastic_pinned_kinds": [],
    "community_disabled_adapters": [],
}


def _coerce_settings(raw: dict[str, Any]) -> dict[str, Any]:
    settings = dict(DEFAULT_SETTINGS)
    settings.update({k: v for k, v in raw.items() if k in DEFAULT_SETTINGS})

    if settings["language"] is None:
        settings["language"] = "auto"
    if settings["task"] not in {"transcribe", "translate"}:
        settings["task"] = "transcribe"
    if settings["device"] not in {"auto", "cpu", "cuda", "npu", "metal"}:
        settings["device"] = "auto"
    if settings["compute_type"] not in {
        "auto",
        "int8",
        "int8_float16",
        "int8_float32",
        "float16",
        "float32",
        "bfloat16",
    }:
        settings["compute_type"] = "auto"
    try:
        settings["beam_size"] = max(1, min(10, int(settings["beam_size"])))
    except (TypeError, ValueError):
        settings["beam_size"] = 5
    try:
        settings["max_concurrent_jobs"] = max(1, min(4, int(settings["max_concurrent_jobs"])))
    except (TypeError, ValueError):
        settings["max_concurrent_jobs"] = 1
    settings["vad_filter"] = bool(settings["vad_filter"])
    settings["word_timestamps"] = bool(settings["word_timestamps"])
    settings["keep_audio"] = bool(settings["keep_audio"])
    if settings["theme"] not in {"dark", "light", "system"}:
        settings["theme"] = "dark"
    if settings["image_provider"] not in {"auto", "diffusers", "comfyui", "demo"}:
        settings["image_provider"] = "auto"
    try:
        settings["image_steps"] = max(1, min(100, int(settings["image_steps"])))
    except (TypeError, ValueError):
        settings["image_steps"] = 28
    try:
        settings["image_guidance"] = round(
            max(0.0, min(20.0, float(settings["image_guidance"]))), 2
        )
    except (TypeError, ValueError):
        settings["image_guidance"] = 3.5
    if settings["llm_provider"] not in {"auto", "llama-cpp", "openai", "demo"}:
        settings["llm_provider"] = "auto"
    try:
        settings["llm_temperature"] = round(
            max(0.0, min(2.0, float(settings["llm_temperature"]))), 2
        )
    except (TypeError, ValueError):
        settings["llm_temperature"] = 0.7
    try:
        settings["llm_max_tokens"] = max(1, min(32768, int(settings["llm_max_tokens"])))
    except (TypeError, ValueError):
        settings["llm_max_tokens"] = 1024
    if not isinstance(settings.get("llm_system_prompt"), str):
        settings["llm_system_prompt"] = "你是 AIBox 的本地 AI 助手，回答准确、简洁。"
    if settings.get("parallel_strategy") not in {
        "auto",
        "single",
        "data",
        "tensor",
        "pipeline",
        "hybrid",
    }:
        settings["parallel_strategy"] = "auto"
    try:
        settings["parallel_workers"] = max(1, min(16, int(settings.get("parallel_workers") or 2)))
    except (TypeError, ValueError):
        settings["parallel_workers"] = 2
    if not isinstance(settings.get("parallel_devices"), list):
        settings["parallel_devices"] = []
    else:
        settings["parallel_devices"] = [
            str(item) for item in settings["parallel_devices"] if isinstance(item, str)
        ][:16]
    for key in ("asr_device", "tts_device", "image_device", "llm_device"):
        if not isinstance(settings.get(key), str) or not settings[key]:
            settings[key] = "auto"
    if settings.get("training_method") not in {"lora", "qlora", "full"}:
        settings["training_method"] = "qlora"
    if settings.get("compute_priority_mode") not in {
        "services_first",
        "llm_first",
        "auto",
        "scheduled",
    }:
        settings["compute_priority_mode"] = "services_first"
    windows: list[dict[str, Any]] = []
    raw_windows = settings.get("compute_priority_windows")
    if isinstance(raw_windows, list):
        for item in raw_windows[:16]:
            if not isinstance(item, dict):
                continue
            start = str(item.get("start") or "")
            end = str(item.get("end") or "")
            if not _valid_clock(start) or not _valid_clock(end):
                continue
            days = []
            for day in item.get("days") or list(range(7)):
                try:
                    value = int(day)
                except (TypeError, ValueError):
                    continue
                if 0 <= value <= 6:
                    days.append(value)
            if not days:
                days = list(range(7))
            windows.append({"start": start, "end": end, "days": sorted(set(days))})
    settings["compute_priority_windows"] = windows
    if settings.get("translation_provider") not in {
        "auto",
        "libre",
        "argos",
        "index",
        "hunyuan",
        "openai",
        "demo",
    }:
        settings["translation_provider"] = "auto"
    if settings.get("ocr_provider") not in {
        "auto",
        "glm",
        "openai",
        "tesseract",
        "demo",
    }:
        settings["ocr_provider"] = "auto"
    if settings["elastic_mode"] not in {
        "auto",
        "balanced",
        "asr_focus",
        "tts_focus",
        "time_slice",
        "custom",
    }:
        settings["elastic_mode"] = "auto"
    for key, default, low, high in (
        ("elastic_idle_ttl_seconds", 600, 0, 86400),
        ("elastic_switch_interval_seconds", 300, 30, 86400),
        ("elastic_max_loaded_models", 4, 1, 4),
    ):
        try:
            settings[key] = max(low, min(high, int(settings[key])))
        except (TypeError, ValueError):
            settings[key] = default
    for key, default in (
        ("elastic_gpu_reserve_gb", 1.5),
        ("elastic_ram_reserve_gb", 2.0),
    ):
        try:
            settings[key] = round(max(0.0, min(64.0, float(settings[key]))), 1)
        except (TypeError, ValueError):
            settings[key] = default
    pinned = settings.get("elastic_pinned_kinds")
    if not isinstance(pinned, list):
        pinned = []
    settings["elastic_pinned_kinds"] = [
        kind for kind in pinned if kind in {"asr", "tts"}
    ]
    disabled = settings.get("community_disabled_adapters")
    if not isinstance(disabled, list):
        disabled = []
    settings["community_disabled_adapters"] = [
        str(item) for item in disabled if str(item).strip()
    ]
    return settings


@dataclass
class AppConfig:
    repo_root: Path = field(
        default_factory=lambda: Path(
            os.getenv("AIBOX_REPO_ROOT") or detect_repo_root()
        ).expanduser().resolve()
    )
    data_dir: Path = field(default_factory=default_data_dir)
    host: str = field(default_factory=lambda: os.getenv("AIBOX_HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: int(os.getenv("AIBOX_PORT", "8765")))
    mock_asr: bool = field(default_factory=lambda: _env_bool("AIBOX_DEMO_ASR", False))
    hf_endpoint: str = field(
        default_factory=lambda: (
            os.getenv("AIBOX_HF_ENDPOINT")
            or os.getenv("HF_ENDPOINT")
            or "https://huggingface.co"
        ).rstrip("/")
    )
    hf_token: str | None = field(default_factory=lambda: os.getenv("HF_TOKEN") or None)
    max_upload_mb: int = field(default_factory=lambda: int(os.getenv("AIBOX_MAX_UPLOAD_MB", "512")))
    api_token: str | None = field(default_factory=lambda: os.getenv("AIBOX_API_TOKEN") or None)
    public_base_url: str = field(
        default_factory=lambda: os.getenv("AIBOX_PUBLIC_BASE_URL", "").rstrip("/")
    )
    demo_tts: bool = field(default_factory=lambda: _env_bool("AIBOX_DEMO_TTS", False))
    demo_image: bool = field(default_factory=lambda: _env_bool("AIBOX_DEMO_IMAGE", False))
    comfyui_url: str = field(
        default_factory=lambda: os.getenv("AIBOX_COMFYUI_URL", "http://127.0.0.1:8188").rstrip("/")
    )
    image_python: str = field(default_factory=lambda: os.getenv("AIBOX_IMAGE_PYTHON", ""))
    demo_separation: bool = field(
        default_factory=lambda: _env_bool("AIBOX_DEMO_SEPARATION", False)
    )
    separation_python: str = field(
        default_factory=lambda: os.getenv("AIBOX_SEPARATION_PYTHON", "")
    )
    separation_device: str = field(
        default_factory=lambda: os.getenv("AIBOX_SEPARATION_DEVICE", "auto")
    )
    demo_video: bool = field(default_factory=lambda: _env_bool("AIBOX_DEMO_VIDEO", False))
    minimax_api_key: str | None = field(
        default_factory=lambda: os.getenv("MINIMAX_API_KEY")
        or os.getenv("AIBOX_MINIMAX_API_KEY")
        or None
    )
    minimax_base_url: str = field(
        default_factory=lambda: os.getenv(
            "AIBOX_MINIMAX_BASE_URL", "https://api.minimax.io/v1"
        ).rstrip("/")
    )
    minimax_model: str = field(
        default_factory=lambda: os.getenv("AIBOX_MINIMAX_MODEL", "MiniMax-H3")
    )
    demo_llm: bool = field(default_factory=lambda: _env_bool("AIBOX_DEMO_LLM", False))
    llama_server: str = field(
        default_factory=lambda: os.getenv("AIBOX_LLAMA_SERVER", "")
    )
    llm_base_url: str = field(
        default_factory=lambda: os.getenv("AIBOX_LLM_BASE_URL", "").rstrip("/")
    )
    llm_api_key: str | None = field(
        default_factory=lambda: os.getenv("AIBOX_LLM_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or None
    )
    llm_model: str = field(
        default_factory=lambda: os.getenv("AIBOX_LLM_MODEL", "qwen3-8b")
    )
    llm_context: int = field(
        default_factory=lambda: int(os.getenv("AIBOX_LLM_CONTEXT", "8192"))
    )
    llm_gpu_layers: int = field(
        default_factory=lambda: int(os.getenv("AIBOX_LLM_GPU_LAYERS", "99"))
    )
    demo_training: bool = field(
        default_factory=lambda: _env_bool("AIBOX_DEMO_TRAINING", False)
    )
    training_command: str = field(
        default_factory=lambda: os.getenv("AIBOX_TRAIN_COMMAND", "")
    )
    demo_translation: bool = field(
        default_factory=lambda: _env_bool("AIBOX_DEMO_TRANSLATION", False)
    )
    translation_provider: str = field(
        default_factory=lambda: os.getenv("AIBOX_TRANSLATION_PROVIDER", "auto")
    )
    libre_url: str = field(
        default_factory=lambda: os.getenv("AIBOX_LIBRE_URL", "").rstrip("/")
    )
    libre_api_key: str | None = field(
        default_factory=lambda: os.getenv("AIBOX_LIBRE_API_KEY") or None
    )
    index_url: str = field(
        default_factory=lambda: os.getenv("AIBOX_INDEX_URL", "").rstrip("/")
    )
    index_api_key: str | None = field(
        default_factory=lambda: os.getenv("AIBOX_INDEX_API_KEY") or None
    )
    index_model: str = field(
        default_factory=lambda: os.getenv("AIBOX_INDEX_MODEL", "Index-Translate")
    )
    hunyuan_url: str = field(
        default_factory=lambda: os.getenv("AIBOX_HUNYUAN_URL", "").rstrip("/")
    )
    hunyuan_api_key: str | None = field(
        default_factory=lambda: os.getenv("AIBOX_HUNYUAN_API_KEY") or None
    )
    hunyuan_model: str = field(
        default_factory=lambda: os.getenv("AIBOX_HUNYUAN_MODEL", "hunyuan-mt2")
    )
    argos_command: str = field(
        default_factory=lambda: os.getenv("AIBOX_ARGOS_COMMAND", "argos-translate")
    )
    demo_ocr: bool = field(
        default_factory=lambda: _env_bool("AIBOX_DEMO_OCR", False)
    )
    ocr_provider: str = field(
        default_factory=lambda: os.getenv("AIBOX_OCR_PROVIDER", "auto")
    )
    glm_api_key: str | None = field(
        default_factory=lambda: os.getenv("AIBOX_GLM_API_KEY")
        or os.getenv("GLM_API_KEY")
        or None
    )
    glm_base_url: str = field(
        default_factory=lambda: os.getenv(
            "AIBOX_GLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4"
        ).rstrip("/")
    )
    glm_ocr_model: str = field(
        default_factory=lambda: os.getenv("AIBOX_GLM_OCR_MODEL", "glm-ocr")
    )
    ocr_openai_url: str = field(
        default_factory=lambda: os.getenv("AIBOX_OCR_OPENAI_URL", "").rstrip("/")
    )
    ocr_openai_api_key: str | None = field(
        default_factory=lambda: os.getenv("AIBOX_OCR_OPENAI_API_KEY") or None
    )
    ocr_openai_model: str = field(
        default_factory=lambda: os.getenv("AIBOX_OCR_OPENAI_MODEL", "gpt-4o-mini")
    )
    tesseract_command: str = field(
        default_factory=lambda: os.getenv("AIBOX_TESSERACT_COMMAND", "tesseract")
    )
    allow_adapter_commands: bool = field(
        default_factory=lambda: _env_bool("AIBOX_ALLOW_ADAPTER_COMMANDS", False)
    )
    allow_remote_adapters: bool = field(
        default_factory=lambda: _env_bool("AIBOX_ALLOW_REMOTE_ADAPTERS", False)
    )
    indextts_home: str = field(default_factory=lambda: os.getenv("AIBOX_INDEXTTS_HOME", ""))
    indextts_python: str = field(
        default_factory=lambda: os.getenv("AIBOX_INDEXTTS_PYTHON", "")
    )
    grpc_enabled: bool = field(default_factory=lambda: _env_bool("AIBOX_GRPC_ENABLED", True))
    grpc_host: str = field(default_factory=lambda: os.getenv("AIBOX_GRPC_HOST", "127.0.0.1"))
    grpc_port: int = field(default_factory=lambda: int(os.getenv("AIBOX_GRPC_PORT", "50051")))
    mrcp_enabled: bool = field(default_factory=lambda: _env_bool("AIBOX_MRCP_ENABLED", True))
    mrcp_host: str = field(default_factory=lambda: os.getenv("AIBOX_MRCP_HOST", "127.0.0.1"))
    mrcp_port: int = field(default_factory=lambda: int(os.getenv("AIBOX_MRCP_PORT", "8060")))
    mrcp_control_port: int = field(
        default_factory=lambda: int(os.getenv("AIBOX_MRCP_CONTROL_PORT", "8061"))
    )
    mrcp_rtp_port_start: int = field(
        default_factory=lambda: int(os.getenv("AIBOX_MRCP_RTP_PORT_START", "50000"))
    )
    mrcp_rtp_port_end: int = field(
        default_factory=lambda: int(os.getenv("AIBOX_MRCP_RTP_PORT_END", "50100"))
    )
    mrcp_advertise_host: str = field(
        default_factory=lambda: os.getenv("AIBOX_MRCP_ADVERTISE_HOST", "127.0.0.1")
    )
    cors_origins: list[str] = field(
        default_factory=lambda: [
            origin.strip()
            for origin in os.getenv(
                "AIBOX_CORS_ORIGINS",
                "http://localhost:5173,http://127.0.0.1:5173,"
                "http://localhost:1420,http://127.0.0.1:1420,"
                "tauri://localhost,http://tauri.localhost,https://tauri.localhost",
            ).split(",")
            if origin.strip()
        ]
    )
    _settings_lock: threading.RLock = field(default_factory=threading.RLock, repr=False)
    _settings: dict[str, Any] | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        self.data_dir = Path(self.data_dir).expanduser().resolve()
        self.models_dir = self.data_dir / "models" / "whisper"
        self.tts_models_dir = self.data_dir / "models" / "tts"
        self.image_models_dir = self.data_dir / "models" / "image"
        self.separation_models_dir = self.data_dir / "models" / "separator"
        self.llm_models_dir = self.data_dir / "models" / "llm"
        self.voices_dir = self.data_dir / "voices"
        self.tts_outputs_dir = self.data_dir / "tts"
        self.image_outputs_dir = self.data_dir / "images"
        self.separation_outputs_dir = self.data_dir / "separations"
        self.video_outputs_dir = self.data_dir / "videos"
        self.training_dir = self.data_dir / "training"
        self.ocr_dir = self.data_dir / "ocr"
        self.training_datasets_dir = self.training_dir / "datasets"
        self.training_outputs_dir = self.training_dir / "runs"
        self.training_logs_dir = self.training_dir / "logs"
        self.adapters_dir = Path(
            os.getenv("AIBOX_ADAPTERS_DIR") or (self.data_dir / "adapters")
        ).expanduser().resolve()
        self.uploads_dir = self.data_dir / "uploads"
        self.exports_dir = self.data_dir / "exports"
        self.state_dir = self.data_dir / "state"
        self.settings_path = self.state_dir / "settings.json"
        self.database_path = self.state_dir / "aibox.db"
        self.logs_dir = self.data_dir / "logs"
        for directory in (
            self.data_dir,
            self.models_dir,
            self.tts_models_dir,
            self.image_models_dir,
            self.separation_models_dir,
            self.llm_models_dir,
            self.voices_dir,
            self.tts_outputs_dir,
            self.image_outputs_dir,
            self.separation_outputs_dir,
            self.video_outputs_dir,
            self.training_datasets_dir,
            self.training_outputs_dir,
            self.training_logs_dir,
            self.ocr_dir,
            self.adapters_dir,
            self.uploads_dir,
            self.exports_dir,
            self.state_dir,
            self.logs_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)
        self.static_dir = Path(
            os.getenv("AIBOX_WEB_DIST") or (self.repo_root / "apps" / "web" / "dist")
        ).expanduser().resolve()
        if not self.indextts_home:
            candidate = self.repo_root / "runtimes" / "index-tts"
            if (candidate / "indextts").is_dir():
                self.indextts_home = str(candidate)
        if not self.indextts_python and self.indextts_home:
            home = Path(self.indextts_home).expanduser()
            if platform.system() == "Windows":
                candidate = home / ".venv" / "Scripts" / "python.exe"
            else:
                candidate = home / ".venv" / "bin" / "python"
            if candidate.is_file():
                self.indextts_python = str(candidate)

    def settings(self) -> dict[str, Any]:
        with self._settings_lock:
            if self._settings is None:
                raw: dict[str, Any] = {}
                if self.settings_path.exists():
                    try:
                        raw = json.loads(self.settings_path.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError):
                        raw = {}
                self._settings = _coerce_settings(raw if isinstance(raw, dict) else {})
            return dict(self._settings)

    def update_settings(self, patch: dict[str, Any]) -> dict[str, Any]:
        with self._settings_lock:
            current = self.settings()
            merged = dict(current)
            merged.update({k: v for k, v in patch.items() if k in DEFAULT_SETTINGS and v is not None})
            self._settings = _coerce_settings(merged)
            tmp = self.settings_path.with_suffix(".json.tmp")
            tmp.write_text(
                json.dumps(self._settings, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            tmp.replace(self.settings_path)
            return dict(self._settings)


_CONFIG: AppConfig | None = None


def get_config() -> AppConfig:
    """FastAPI dependency-friendly accessor (a single process-wide config)."""
    global _CONFIG
    if _CONFIG is None:
        _CONFIG = AppConfig()
    return _CONFIG
