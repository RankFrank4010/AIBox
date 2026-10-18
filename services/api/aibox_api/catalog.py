"""Curated model catalog for speech recognition and synthesis.

Whisper entries are CTranslate2 checkpoints compatible with faster-whisper.
IndexTTS entries are PyTorch checkpoints used by the optional IndexTTS worker.
The download/install pipeline is shared; ``kind`` controls the storage root and
which runtime consumes the model.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

ASR_REQUIRED_FILES = ("model.bin", "config.json", "tokenizer.json")


@dataclass(frozen=True)
class ModelSpec:
    id: str
    name: str
    repo: str
    parameters: str
    size_bytes: int
    size_label: str
    speed: float
    accuracy: float
    languages: str
    memory_gb: float
    description: str
    best_for: str
    tags: tuple[str, ...] = field(default_factory=tuple)
    english_only: bool = False
    license: str = "MIT"
    source: str = "Hugging Face"
    kind: str = "asr"
    engine: str = "faster-whisper"
    format: str = "CTranslate2"
    recursive_download: bool = False
    required_files: tuple[str, ...] = ASR_REQUIRED_FILES
    external: bool = False
    community: bool = False
    adapter_id: str = ""
    aliases: tuple[str, ...] = field(default_factory=tuple)
    homepage: str = ""
    install_docs: str = ""
    pipeline: str = ""
    comfyui_checkpoint: str = ""
    default_width: int = 1024
    default_height: int = 1024
    download_files: tuple[str, ...] = field(default_factory=tuple)
    quantization: str = ""
    context_length: int = 0

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["tags"] = list(self.tags)
        data["required_files"] = list(self.required_files)
        data["aliases"] = list(self.aliases)
        data["download_files"] = list(self.download_files)
        data["family"] = (
            "whisper"
            if self.kind == "asr" and not self.external
            else "indextts"
            if self.kind == "tts" and not self.external
            else "diffusers"
            if self.kind == "image" and not self.external
            else "llama-cpp"
            if self.kind == "llm" and not self.external
            else "community"
        )
        data["download_url"] = (
            f"https://huggingface.co/{self.repo}" if self.repo else None
        )
        return data


WHISPER_MODELS: tuple[ModelSpec, ...] = (
    ModelSpec(
        id="tiny",
        name="Whisper Tiny",
        repo="Systran/faster-whisper-tiny",
        parameters="39M",
        size_bytes=75_500_000,
        size_label="75 MB",
        speed=5.0,
        accuracy=1.6,
        languages="99 种语言",
        memory_gb=1.0,
        description="最轻量的 Whisper 模型，适合低功耗设备、实时字幕与快速草稿。",
        best_for="CPU / 低内存设备",
        tags=("极速", "轻量"),
    ),
    ModelSpec(
        id="base",
        name="Whisper Base",
        repo="Systran/faster-whisper-base",
        parameters="74M",
        size_bytes=145_000_000,
        size_label="145 MB",
        speed=4.6,
        accuracy=2.2,
        languages="99 种语言",
        memory_gb=1.5,
        description="比 Tiny 更稳的识别质量，仍然是笔记本与迷你主机上的高性价比选择。",
        best_for="日常语音笔记",
        tags=("轻量", "均衡"),
    ),
    ModelSpec(
        id="small",
        name="Whisper Small",
        repo="Systran/faster-whisper-small",
        parameters="244M",
        size_bytes=484_000_000,
        size_label="484 MB",
        speed=3.7,
        accuracy=3.2,
        languages="99 种语言",
        memory_gb=3.0,
        description="CPU 上可用的质量甜点，适合会议记录、播客转写与中英混说。",
        best_for="CPU 高质量转写",
        tags=("推荐", "CPU 友好"),
    ),
    ModelSpec(
        id="medium",
        name="Whisper Medium",
        repo="Systran/faster-whisper-medium",
        parameters="769M",
        size_bytes=1_530_000_000,
        size_label="1.53 GB",
        speed=2.4,
        accuracy=4.0,
        languages="99 种语言",
        memory_gb=6.0,
        description="精度明显提升，建议搭配 6 GB 以上显存；CPU 上速度较慢。",
        best_for="GPU 会议 / 访谈",
        tags=("高精度",),
    ),
    ModelSpec(
        id="large-v3-turbo",
        name="Whisper Large v3 Turbo",
        repo="deepdml/faster-whisper-large-v3-turbo-ct2",
        parameters="809M",
        size_bytes=1_620_000_000,
        size_label="1.62 GB",
        speed=3.9,
        accuracy=4.3,
        languages="99 种语言",
        memory_gb=6.0,
        description="Large v3 的蒸馏加速版，接近大模型精度但解码快数倍，是 GPU 首选。",
        best_for="GPU 实时转写",
        tags=("GPU 首选", "快速"),
    ),
    ModelSpec(
        id="large-v3",
        name="Whisper Large v3",
        repo="Systran/faster-whisper-large-v3",
        parameters="1.55B",
        size_bytes=3_090_000_000,
        size_label="3.09 GB",
        speed=2.0,
        accuracy=4.8,
        languages="99 种语言",
        memory_gb=10.0,
        description="Whisper 系列最高精度，适合复杂口音、嘈杂环境与专业字幕制作。",
        best_for="专业字幕 / 高精度",
        tags=("最高精度",),
    ),
    ModelSpec(
        id="distil-large-v3",
        name="Distil Whisper Large v3",
        repo="Systran/faster-distil-whisper-large-v3",
        parameters="756M",
        size_bytes=1_510_000_000,
        size_label="1.51 GB",
        speed=4.2,
        accuracy=4.2,
        languages="英语",
        memory_gb=6.0,
        description="面向英文的蒸馏模型，在英文长音频上兼顾速度与准确率。",
        best_for="英文播客 / 长音频",
        tags=("英文专用", "长音频"),
        english_only=True,
    ),
)

TTS_MODELS: tuple[ModelSpec, ...] = (
    ModelSpec(
        id="indextts-2.5",
        name="IndexTTS 2.5",
        repo="IndexTeam/IndexTTS-2.5",
        parameters="—",
        size_bytes=5_491_182_363,
        size_label="5.11 GB",
        speed=3.6,
        accuracy=4.8,
        languages="中文 / 英语 / 日语 / 西班牙语 / 阿拉伯语",
        memory_gb=10.0,
        description="IndexTTS 最新版。单段参考音频即可克隆音色，支持多语言、情绪控制、语速与发音控制。",
        best_for="多语言配音 / 声音克隆",
        tags=("IndexTTS", "声音克隆", "多语言", "情绪控制"),
        license="IndexTTS License",
        kind="tts",
        engine="indextts",
        format="PyTorch",
        recursive_download=True,
        required_files=(
            "config.yaml",
            "gpt.pth",
            "codec.pth",
            "s2mel.pth",
            "qwen0.6bemo4-merge/model.safetensors",
        ),
    ),
    ModelSpec(
        id="indextts-2",
        name="IndexTTS 2",
        repo="IndexTeam/IndexTTS-2",
        parameters="—",
        size_bytes=5_895_818_637,
        size_label="5.49 GB",
        speed=3.3,
        accuracy=4.7,
        languages="中文 / 英语",
        memory_gb=10.0,
        description="IndexTTS 2 稳定版，零样本音色克隆、跨语言与情绪参考控制，兼容社区工具链。",
        best_for="中英双语配音 / 声音克隆",
        tags=("IndexTTS", "声音克隆", "中英双语"),
        license="IndexTTS License",
        kind="tts",
        engine="indextts",
        format="PyTorch",
        recursive_download=True,
        required_files=(
            "config.yaml",
            "gpt.pth",
            "s2mel.pth",
            "qwen0.6bemo4-merge/model.safetensors",
        ),
    ),
)

IMAGE_MODELS: tuple[ModelSpec, ...] = (
    ModelSpec(
        id="sd15",
        name="Stable Diffusion 1.5",
        repo="stable-diffusion-v1-5/stable-diffusion-v1-5",
        parameters="约 1B",
        size_bytes=4_200_000_000,
        size_label="约 4.2 GB",
        speed=4.3,
        accuracy=3.1,
        languages="英文提示词",
        memory_gb=6.0,
        description="经典 SD 1.5 底模，生态最大、LoRA 与 ControlNet 资源最丰富，适合 6 GB 以上显存。",
        best_for="通用文生图 / 二次元 / LoRA 生态",
        tags=("Stable Diffusion", "SD1.5", "轻量"),
        license="CreativeML Open RAIL-M",
        source="Stability AI",
        kind="image",
        engine="diffusers",
        format="Diffusers",
        recursive_download=True,
        required_files=("model_index.json",),
        pipeline="stable-diffusion",
        comfyui_checkpoint="v1-5-pruned-emaonly.safetensors",
        default_width=512,
        default_height=512,
        homepage="https://huggingface.co/stable-diffusion-v1-5/stable-diffusion-v1-5",
    ),
    ModelSpec(
        id="sdxl",
        name="Stable Diffusion XL",
        repo="stabilityai/stable-diffusion-xl-base-1.0",
        parameters="约 3.5B",
        size_bytes=6_900_000_000,
        size_label="约 6.9 GB",
        speed=2.9,
        accuracy=4.2,
        languages="英文提示词",
        memory_gb=10.0,
        description="SDXL 1.0 底模，1024 分辨率与构图能力显著强于 SD1.5，适合 10 GB 以上显存。",
        best_for="高质量插画 / 写实 / 1024 文生图",
        tags=("Stable Diffusion", "SDXL", "1024"),
        license="CreativeML Open RAIL++-M",
        source="Stability AI",
        kind="image",
        engine="diffusers",
        format="Diffusers",
        recursive_download=True,
        required_files=("model_index.json",),
        pipeline="stable-diffusion-xl",
        comfyui_checkpoint="sd_xl_base_1.0.safetensors",
        default_width=1024,
        default_height=1024,
        homepage="https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0",
    ),
    ModelSpec(
        id="flux1-schnell",
        name="FLUX.1 schnell",
        repo="black-forest-labs/FLUX.1-schnell",
        parameters="12B",
        size_bytes=23_800_000_000,
        size_label="约 23.8 GB",
        speed=3.7,
        accuracy=4.5,
        languages="英文提示词",
        memory_gb=24.0,
        description="FLUX.1 schnell 是 4 步快速模型，文字渲染与提示词遵循强，适合 24 GB 级显存。",
        best_for="快速高质量文生图 / 文字排版",
        tags=("FLUX", "Schnell", "12B", "快速"),
        license="Apache-2.0",
        source="Black Forest Labs",
        kind="image",
        engine="diffusers",
        format="Diffusers",
        recursive_download=True,
        required_files=("model_index.json",),
        pipeline="flux",
        comfyui_checkpoint="flux1-schnell.safetensors",
        default_width=1024,
        default_height=1024,
        homepage="https://huggingface.co/black-forest-labs/FLUX.1-schnell",
    ),
    ModelSpec(
        id="flux1-dev",
        name="FLUX.1 dev",
        repo="black-forest-labs/FLUX.1-dev",
        parameters="12B",
        size_bytes=23_800_000_000,
        size_label="约 23.8 GB",
        speed=2.8,
        accuracy=4.7,
        languages="英文提示词",
        memory_gb=24.0,
        description="FLUX.1 dev 质量更高，需要接受上游许可并配置 HF_TOKEN；建议 24 GB 显存。",
        best_for="高质量商业视觉 / 写实 / 文字",
        tags=("FLUX", "Dev", "12B", "高质量"),
        license="FLUX.1 dev Non-Commercial License",
        source="Black Forest Labs",
        kind="image",
        engine="diffusers",
        format="Diffusers",
        recursive_download=True,
        required_files=("model_index.json",),
        pipeline="flux",
        comfyui_checkpoint="flux1-dev.safetensors",
        default_width=1024,
        default_height=1024,
        homepage="https://huggingface.co/black-forest-labs/FLUX.1-dev",
    ),
    ModelSpec(
        id="qwen-image",
        name="Qwen-Image",
        repo="Qwen/Qwen-Image",
        parameters="20B",
        size_bytes=40_000_000_000,
        size_label="约 40 GB",
        speed=2.0,
        accuracy=4.6,
        languages="中 / 英提示词",
        memory_gb=40.0,
        description="通义千问图像生成模型，中文提示词与复杂文字渲染突出；建议 40 GB 级显存或量化。",
        best_for="中文文生图 / 海报 / 文字排版",
        tags=("Qwen-Image", "20B", "中文", "文字渲染"),
        license="Apache-2.0",
        source="Qwen",
        kind="image",
        engine="diffusers",
        format="Diffusers",
        recursive_download=True,
        required_files=("model_index.json",),
        pipeline="qwen-image",
        comfyui_checkpoint="qwen_image_fp8_e4m3fn.safetensors",
        default_width=1024,
        default_height=1024,
        homepage="https://huggingface.co/Qwen/Qwen-Image",
    ),
)

LLM_MODELS: tuple[ModelSpec, ...] = (
    ModelSpec(
        id="qwen3-8b",
        name="Qwen3 8B",
        repo="unsloth/Qwen3-8B-GGUF",
        parameters="8B",
        size_bytes=5_030_000_000,
        size_label="约 4.7 GB",
        speed=3.8,
        accuracy=4.4,
        languages="中 / 英 / 多语言",
        memory_gb=8.0,
        description="Qwen3 8B 指令模型，中文、推理与工具调用均衡，GGUF Q4_K_M 适合 8 GB+ 显存。",
        best_for="中文对话 / 推理 / 本地助手",
        tags=("Qwen3", "中文", "GGUF", "Q4_K_M"),
        license="Apache-2.0",
        kind="llm",
        engine="llama-cpp",
        format="GGUF",
        required_files=("Qwen3-8B-Q4_K_M.gguf",),
        download_files=("Qwen3-8B-Q4_K_M.gguf",),
        quantization="Q4_K_M",
        context_length=32768,
        aliases=("qwen", "qwen3"),
        homepage="https://huggingface.co/unsloth/Qwen3-8B-GGUF",
    ),
    ModelSpec(
        id="qwen2.5-7b",
        name="Qwen2.5 7B Instruct",
        repo="bartowski/Qwen2.5-7B-Instruct-GGUF",
        parameters="7B",
        size_bytes=4_680_000_000,
        size_label="约 4.4 GB",
        speed=4.0,
        accuracy=4.0,
        languages="中 / 英 / 多语言",
        memory_gb=7.0,
        description="Qwen2.5 7B 指令模型，稳定的中文对话与写作能力，部署成本低。",
        best_for="中文写作 / 客服 / 本地对话",
        tags=("Qwen2.5", "中文", "GGUF", "Q4_K_M"),
        license="Apache-2.0",
        kind="llm",
        engine="llama-cpp",
        format="GGUF",
        required_files=("Qwen2.5-7B-Instruct-Q4_K_M.gguf",),
        download_files=("Qwen2.5-7B-Instruct-Q4_K_M.gguf",),
        quantization="Q4_K_M",
        context_length=32768,
        aliases=("qwen2.5",),
        homepage="https://huggingface.co/bartowski/Qwen2.5-7B-Instruct-GGUF",
    ),
    ModelSpec(
        id="llama-3.1-8b",
        name="Llama 3.1 8B Instruct",
        repo="bartowski/Meta-Llama-3.1-8B-Instruct-GGUF",
        parameters="8B",
        size_bytes=4_920_000_000,
        size_label="约 4.6 GB",
        speed=3.7,
        accuracy=4.1,
        languages="英语 / 多语言",
        memory_gb=8.0,
        description="Meta Llama 3.1 8B 指令模型，英文对话、总结与代码能力均衡。",
        best_for="英文助手 / 总结 / 代码",
        tags=("Llama 3.1", "英文", "GGUF", "Q4_K_M"),
        license="Llama 3.1 Community License",
        kind="llm",
        engine="llama-cpp",
        format="GGUF",
        required_files=("Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf",),
        download_files=("Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf",),
        quantization="Q4_K_M",
        context_length=131072,
        aliases=("llama", "llama3.1"),
        homepage="https://huggingface.co/bartowski/Meta-Llama-3.1-8B-Instruct-GGUF",
    ),
    ModelSpec(
        id="llama-3.2-3b",
        name="Llama 3.2 3B Instruct",
        repo="bartowski/Llama-3.2-3B-Instruct-GGUF",
        parameters="3B",
        size_bytes=2_020_000_000,
        size_label="约 1.9 GB",
        speed=5.0,
        accuracy=3.4,
        languages="英语 / 多语言",
        memory_gb=4.0,
        description="轻量 3B 指令模型，适合低显存、CPU 或快速草稿。",
        best_for="低配设备 / 快速草稿 / 英文",
        tags=("Llama 3.2", "轻量", "GGUF", "Q4_K_M"),
        license="Llama 3.2 Community License",
        kind="llm",
        engine="llama-cpp",
        format="GGUF",
        required_files=("Llama-3.2-3B-Instruct-Q4_K_M.gguf",),
        download_files=("Llama-3.2-3B-Instruct-Q4_K_M.gguf",),
        quantization="Q4_K_M",
        context_length=131072,
        aliases=("llama3.2",),
        homepage="https://huggingface.co/bartowski/Llama-3.2-3B-Instruct-GGUF",
    ),
    ModelSpec(
        id="mistral-7b",
        name="Mistral 7B Instruct v0.3",
        repo="bartowski/Mistral-7B-Instruct-v0.3-GGUF",
        parameters="7B",
        size_bytes=4_370_000_000,
        size_label="约 4.1 GB",
        speed=4.1,
        accuracy=3.8,
        languages="英语 / 多语言",
        memory_gb=7.0,
        description="Mistral 7B 指令模型，英文写作与检索增强场景表现稳定。",
        best_for="英文写作 / RAG / 本地助手",
        tags=("Mistral", "英文", "GGUF", "Q4_K_M"),
        license="Apache-2.0",
        kind="llm",
        engine="llama-cpp",
        format="GGUF",
        required_files=("Mistral-7B-Instruct-v0.3-Q4_K_M.gguf",),
        download_files=("Mistral-7B-Instruct-v0.3-Q4_K_M.gguf",),
        quantization="Q4_K_M",
        context_length=32768,
        aliases=("mistral",),
        homepage="https://huggingface.co/bartowski/Mistral-7B-Instruct-v0.3-GGUF",
    ),
    ModelSpec(
        id="deepseek-r1-7b",
        name="DeepSeek R1 Distill Qwen 7B",
        repo="bartowski/DeepSeek-R1-Distill-Qwen-7B-GGUF",
        parameters="7B",
        size_bytes=4_680_000_000,
        size_label="约 4.4 GB",
        speed=3.4,
        accuracy=4.2,
        languages="中 / 英",
        memory_gb=7.0,
        description="基于 Qwen 的 R1 蒸馏推理模型，适合数学、逻辑与逐步推理。",
        best_for="推理 / 数学 / 中文",
        tags=("DeepSeek R1", "推理", "中文", "GGUF"),
        license="MIT",
        kind="llm",
        engine="llama-cpp",
        format="GGUF",
        required_files=("DeepSeek-R1-Distill-Qwen-7B-Q4_K_M.gguf",),
        download_files=("DeepSeek-R1-Distill-Qwen-7B-Q4_K_M.gguf",),
        quantization="Q4_K_M",
        context_length=32768,
        aliases=("deepseek", "r1"),
        homepage="https://huggingface.co/bartowski/DeepSeek-R1-Distill-Qwen-7B-GGUF",
    ),
    ModelSpec(
        id="gemma-3-12b",
        name="Gemma 3 12B IT",
        repo="unsloth/gemma-3-12b-it-GGUF",
        parameters="12B",
        size_bytes=7_300_000_000,
        size_label="约 6.8 GB",
        speed=3.0,
        accuracy=4.3,
        languages="英语 / 多语言",
        memory_gb=10.0,
        description="Gemma 3 12B 指令模型，长上下文与多语言能力较强，需要 10 GB+ 显存。",
        best_for="长文档 / 多语言 / 高质量对话",
        tags=("Gemma 3", "多语言", "GGUF", "Q4_K_M"),
        license="Gemma Terms of Use",
        kind="llm",
        engine="llama-cpp",
        format="GGUF",
        required_files=("gemma-3-12b-it-Q4_K_M.gguf",),
        download_files=("gemma-3-12b-it-Q4_K_M.gguf",),
        quantization="Q4_K_M",
        context_length=32768,
        aliases=("gemma", "gemma3"),
        homepage="https://huggingface.co/unsloth/gemma-3-12b-it-GGUF",
    ),
    ModelSpec(
        id="phi-3.5-mini",
        name="Phi-3.5 mini Instruct",
        repo="bartowski/Phi-3.5-mini-instruct-GGUF",
        parameters="3.8B",
        size_bytes=2_390_000_000,
        size_label="约 2.2 GB",
        speed=4.6,
        accuracy=3.5,
        languages="英语 / 多语言",
        memory_gb=5.0,
        description="微软 Phi-3.5 mini，轻量、推理快，适合低显存设备与英文助手。",
        best_for="低显存 / 英文 / 快速回答",
        tags=("Phi-3.5", "轻量", "GGUF", "Q4_K_M"),
        license="MIT",
        kind="llm",
        engine="llama-cpp",
        format="GGUF",
        required_files=("Phi-3.5-mini-instruct-Q4_K_M.gguf",),
        download_files=("Phi-3.5-mini-instruct-Q4_K_M.gguf",),
        quantization="Q4_K_M",
        context_length=131072,
        aliases=("phi", "phi3.5"),
        homepage="https://huggingface.co/bartowski/Phi-3.5-mini-instruct-GGUF",
    ),
)

WHISPER_BY_ID: dict[str, ModelSpec] = {model.id: model for model in WHISPER_MODELS}
TTS_BY_ID: dict[str, ModelSpec] = {model.id: model for model in TTS_MODELS}
BUILTIN_BY_ID: dict[str, ModelSpec] = {
    model.id: model
    for model in WHISPER_MODELS + TTS_MODELS + IMAGE_MODELS + LLM_MODELS
}
COMMUNITY_MODELS: list[ModelSpec] = []


def all_models() -> tuple[ModelSpec, ...]:
    return (
        WHISPER_MODELS
        + TTS_MODELS
        + IMAGE_MODELS
        + LLM_MODELS
        + tuple(COMMUNITY_MODELS)
    )


def asr_models() -> tuple[ModelSpec, ...]:
    return tuple(model for model in all_models() if model.kind == "asr")


def tts_models() -> tuple[ModelSpec, ...]:
    return tuple(model for model in all_models() if model.kind == "tts")


def image_models() -> tuple[ModelSpec, ...]:
    return tuple(model for model in all_models() if model.kind == "image")


def llm_models() -> tuple[ModelSpec, ...]:
    return tuple(model for model in all_models() if model.kind == "llm")


def register_community_models(specs: list[ModelSpec]) -> None:
    """Replace the community model view without touching built-in entries."""
    seen: set[str] = set()
    for spec in specs:
        if spec.id in BUILTIN_BY_ID:
            raise ValueError(f"社区模型 ID 与内置模型冲突：{spec.id}")
        if spec.id in seen:
            raise ValueError(f"重复的社区模型 ID：{spec.id}")
        seen.add(spec.id)
    COMMUNITY_MODELS.clear()
    COMMUNITY_MODELS.extend(specs)


def get_model(model_id: str) -> ModelSpec | None:
    if model_id in BUILTIN_BY_ID:
        return BUILTIN_BY_ID[model_id]
    for spec in COMMUNITY_MODELS:
        if spec.id == model_id:
            return spec
    return None


def get_asr_model(model_id: str) -> ModelSpec | None:
    spec = get_model(model_id)
    return spec if spec and spec.kind == "asr" else None


def get_tts_model(model_id: str) -> ModelSpec | None:
    spec = get_model(model_id)
    return spec if spec and spec.kind == "tts" else None


def get_image_model(model_id: str) -> ModelSpec | None:
    spec = get_model(model_id)
    return spec if spec and spec.kind == "image" else None


def get_llm_model(model_id: str) -> ModelSpec | None:
    spec = get_model(model_id)
    return spec if spec and spec.kind == "llm" else None


def find_model_by_alias(identifier: str, kind: str | None = None) -> ModelSpec | None:
    needle = identifier.strip().lower()
    if not needle:
        return None
    for spec in all_models():
        if kind and spec.kind != kind:
            continue
        if spec.id.lower() == needle:
            return spec
        if any(alias.lower() == needle for alias in spec.aliases):
            return spec
    return None


def model_catalog(kind: str | None = None) -> list[dict[str, Any]]:
    models = all_models()
    if kind == "asr":
        models = asr_models()
    elif kind == "tts":
        models = tts_models()
    elif kind == "image":
        models = image_models()
    elif kind == "llm":
        models = llm_models()
    return [model.to_dict() for model in models]


def recommend_llm_model_id(
    gpu_memory_gb: float | None = None,
    system_memory_gb: float | None = None,
    installed_ids: set[str] | None = None,
) -> str:
    installed_ids = installed_ids or set()
    for candidate in (
        "qwen3-8b",
        "qwen2.5-7b",
        "llama-3.1-8b",
        "deepseek-r1-7b",
        "llama-3.2-3b",
    ):
        if candidate in installed_ids:
            return candidate
    memory = max(gpu_memory_gb or 0, system_memory_gb or 0)
    if memory >= 16:
        return "qwen3-8b"
    if memory >= 8:
        return "qwen2.5-7b"
    if memory >= 4:
        return "llama-3.2-3b"
    return "phi-3.5-mini"


def recommend_tts_model_id(installed_ids: set[str] | None = None) -> str:
    installed_ids = installed_ids or set()
    for candidate in ("indextts-2.5", "indextts-2"):
        if candidate in installed_ids:
            return candidate
    for candidate in sorted(installed_ids):
        if get_tts_model(candidate):
            return candidate
    return "indextts-2.5"


def recommend_image_model_id(
    gpu_memory_gb: float | None = None,
    installed_ids: set[str] | None = None,
) -> str:
    installed_ids = installed_ids or set()
    for candidate in ("sdxl", "sd15", "flux1-schnell", "qwen-image"):
        if candidate in installed_ids:
            return candidate
    memory = gpu_memory_gb or 0
    if memory >= 32:
        return "qwen-image"
    if memory >= 20:
        return "flux1-schnell"
    if memory >= 10:
        return "sdxl"
    return "sd15"


def recommend_model_id(
    gpu_memory_gb: float | None = None,
    system_memory_gb: float | None = None,
    has_cuda: bool = False,
) -> str:
    """Pick a sensible default without hiding the trade-off from the user."""
    if has_cuda and gpu_memory_gb:
        if gpu_memory_gb >= 10:
            return "large-v3"
        if gpu_memory_gb >= 6:
            return "large-v3-turbo"
        if gpu_memory_gb >= 3:
            return "small"
        return "base"
    if (system_memory_gb or 0) >= 16:
        return "small"
    if (system_memory_gb or 0) >= 8:
        return "base"
    return "tiny"
