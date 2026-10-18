"""Curated video generation model catalog.

MiniMax H3 / Hailuo are cloud API providers. ComfyUI entries are local workflow
presets; they require an API-format workflow supplied in the advanced panel.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class VideoModel:
    id: str
    name: str
    provider: str
    model_arg: str
    durations: tuple[int, ...]
    resolutions: tuple[str, ...]
    description: str
    best_for: str
    max_duration: int
    audio: bool = False
    requires_workflow: bool = False
    license: str = "见上游"
    homepage: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["durations"] = list(self.durations)
        data["resolutions"] = list(self.resolutions)
        return data


VIDEO_MODELS: tuple[VideoModel, ...] = (
    VideoModel(
        id="minimax-h3",
        name="MiniMax H3",
        provider="minimax",
        model_arg="MiniMax-H3",
        durations=(6, 10, 15),
        resolutions=("768P", "1080P", "2K"),
        description="MiniMax H3 全能视频生成，最高 2K / 15 秒，支持原生立体声音频与多模态参考。",
        best_for="高质量广告 / 品牌 / 多镜头视频",
        max_duration=15,
        audio=True,
        license="MiniMax / 上游许可",
        homepage="https://www.minimax.io/blog/minimax-h3",
    ),
    VideoModel(
        id="minimax-hailuo-02",
        name="MiniMax Hailuo 02",
        provider="minimax",
        model_arg="MiniMax-Hailuo-02",
        durations=(6, 10),
        resolutions=("768P", "1080P"),
        description="Hailuo 02 视频模型，适合通用文生视频与图生视频工作流。",
        best_for="通用短视频 / 产品展示",
        max_duration=10,
        license="MiniMax / 上游许可",
        homepage="https://www.minimax.io",
    ),
    VideoModel(
        id="wan2.1-t2v",
        name="Wan2.1 文生视频",
        provider="comfyui",
        model_arg="wan2.1-t2v",
        durations=(3, 5),
        resolutions=("480P", "720P"),
        description="通过 ComfyUI 运行 Wan2.1 工作流；需要在高级设置中粘贴 API workflow。",
        best_for="本地文生视频 / ComfyUI 工作流",
        max_duration=5,
        requires_workflow=True,
        license="Apache-2.0",
        homepage="https://github.com/Wan-Video/Wan2.1",
    ),
    VideoModel(
        id="hunyuan-video",
        name="HunyuanVideo",
        provider="comfyui",
        model_arg="hunyuan-video",
        durations=(3, 5),
        resolutions=("480P", "720P"),
        description="通过 ComfyUI 运行 HunyuanVideo 工作流；需要在高级设置中粘贴 API workflow。",
        best_for="本地高质量视频 / ComfyUI",
        max_duration=5,
        requires_workflow=True,
        license="腾讯混元许可",
        homepage="https://github.com/Tencent-Hunyuan/HunyuanVideo",
    ),
    VideoModel(
        id="ltx-video",
        name="LTX-Video",
        provider="comfyui",
        model_arg="ltx-video",
        durations=(3, 5),
        resolutions=("480P", "720P"),
        description="通过 ComfyUI 运行 LTX-Video 工作流；速度快，适合本地迭代。",
        best_for="快速本地视频草稿",
        max_duration=5,
        requires_workflow=True,
        license="LTX-Video License",
        homepage="https://github.com/Lightricks/LTX-Video",
    ),
)

MODEL_BY_ID = {model.id: model for model in VIDEO_MODELS}


def get_video_model(model_id: str) -> VideoModel | None:
    return MODEL_BY_ID.get(model_id)


def video_catalog() -> list[dict[str, Any]]:
    return [model.to_dict() for model in VIDEO_MODELS]
