"""Curated source-separation model catalog.

Demucs models are executed with ``python -m demucs.separate`` in the configured
separation Python environment. UVR/MDX models are executed with the optional
``audio-separator`` CLI.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class SeparationModel:
    id: str
    name: str
    engine: str
    model_arg: str
    stems: tuple[str, ...]
    size_label: str
    description: str
    best_for: str
    quality: float
    speed: float
    license: str = "MIT / 上游许可"
    filename: str = ""
    two_stem: bool = False

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["stems"] = list(self.stems)
        return data


SEPARATION_MODELS: tuple[SeparationModel, ...] = (
    SeparationModel(
        id="htdemucs",
        name="Demucs v4 htdemucs",
        engine="demucs",
        model_arg="htdemucs",
        stems=("vocals", "drums", "bass", "other"),
        size_label="约 80 MB",
        description="Demucs v4 混合 Transformer 模型，四轨分离，速度与质量平衡，最适合默认使用。",
        best_for="去人声 / 伴奏 / 四轨分离",
        quality=4.5,
        speed=4.0,
        license="MIT",
        two_stem=True,
    ),
    SeparationModel(
        id="htdemucs_ft",
        name="Demucs v4 htdemucs_ft",
        engine="demucs",
        model_arg="htdemucs_ft",
        stems=("vocals", "drums", "bass", "other"),
        size_label="约 80 MB",
        description="htdemucs 的微调版本，人声与乐器分离质量更高，速度略慢。",
        best_for="高质量去人声 / 四轨分离",
        quality=4.8,
        speed=3.2,
        license="MIT",
        two_stem=True,
    ),
    SeparationModel(
        id="mdx_extra",
        name="Demucs MDX Extra",
        engine="demucs",
        model_arg="mdx_extra",
        stems=("vocals", "drums", "bass", "other"),
        size_label="约 300 MB",
        description="Demucs 的 MDX 模型，适合对分离质量要求较高的离线处理。",
        best_for="高质量四轨分离",
        quality=4.3,
        speed=2.8,
        license="MIT",
        two_stem=True,
    ),
    SeparationModel(
        id="uvr-mdx-inst-hq3",
        name="UVR MDX-Net Inst HQ3",
        engine="audio-separator",
        model_arg="UVR-MDX-NET-Inst_HQ_3.onnx",
        stems=("vocals", "instrumental"),
        size_label="约 200 MB",
        description="UVR 的 MDX-Net 伴奏/人声分离模型，适合制作卡拉 OK 伴奏。",
        best_for="去人声 / 保留伴奏",
        quality=4.6,
        speed=3.5,
        filename="UVR-MDX-NET-Inst_HQ_3.onnx",
        two_stem=True,
    ),
    SeparationModel(
        id="uvr-mdx-voc-ft",
        name="UVR MDX-Net Voc FT",
        engine="audio-separator",
        model_arg="UVR-MDX-NET-Voc_FT.onnx",
        stems=("vocals", "instrumental"),
        size_label="约 200 MB",
        description="UVR 的人声提取模型，适合提取干净人声或去除背景音乐。",
        best_for="去背景 / 提取人声",
        quality=4.7,
        speed=3.3,
        filename="UVR-MDX-NET-Voc_FT.onnx",
        two_stem=True,
    ),
    SeparationModel(
        id="uvr-mdx-inst-main",
        name="UVR MDX-Net Inst Main",
        engine="audio-separator",
        model_arg="UVR-MDX-NET-Inst_Main.onnx",
        stems=("vocals", "instrumental"),
        size_label="约 200 MB",
        description="UVR MDX-Net 通用伴奏分离模型，兼容性好。",
        best_for="通用去人声",
        quality=4.2,
        speed=3.8,
        filename="UVR-MDX-NET-Inst_Main.onnx",
        two_stem=True,
    ),
)

MODEL_BY_ID = {model.id: model for model in SEPARATION_MODELS}


def get_separation_model(model_id: str) -> SeparationModel | None:
    return MODEL_BY_ID.get(model_id)


def separation_catalog() -> list[dict[str, Any]]:
    return [model.to_dict() for model in SEPARATION_MODELS]
