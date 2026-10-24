"""Image and video watermark removal.

Providers:
* ``demo``: local blur/median fill, deterministic and dependency-free.
* ``lama``: optional simple-lama-inpainting package.
* ``iopaint``: external IOPaint HTTP API.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
from PIL import Image, ImageDraw, ImageFilter

from .config import AppConfig

logger = logging.getLogger("aibox.watermark")

Progress = Callable[[float, str], None]


class WatermarkError(RuntimeError):
    pass


def _regions_mask(size: tuple[int, int], regions: list[dict[str, Any]]) -> Image.Image:
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    width, height = size
    for region in regions:
        try:
            x = float(region.get("x", 0))
            y = float(region.get("y", 0))
            w = float(region.get("w", 0))
            h = float(region.get("h", 0))
        except (TypeError, ValueError):
            continue
        if max(x, y, w, h) <= 1:
            x, y, w, h = x * width, y * height, w * width, h * height
        pad = 3
        draw.rectangle(
            [
                max(0, x - pad),
                max(0, y - pad),
                min(width, x + w + pad),
                min(height, y + h + pad),
            ],
            fill=255,
        )
    return mask


def _normalize_mask(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    mask = image.convert("L").resize(size, Image.Resampling.LANCZOS)
    return mask.point(lambda value: 255 if value >= 32 else 0)


class WatermarkService:
    PROVIDERS = ("auto", "iopaint", "lama", "demo")

    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def _provider(self, requested: str | None) -> str:
        provider = (requested or self.config.settings().get("watermark_provider") or "auto").lower()
        if provider not in self.PROVIDERS:
            raise WatermarkError(f"未知去水印服务：{provider}")
        if provider == "auto":
            if self.config.demo_watermark:
                return "demo"
            if self.iopaint_available():
                return "iopaint"
            if self.lama_available():
                return "lama"
            return "demo"
        return provider

    def iopaint_available(self) -> bool:
        url = (self.config.settings().get("iopaint_url") or self.config.iopaint_url or "").rstrip("/")
        if not url:
            return False
        try:
            with httpx.Client(timeout=2) as client:
                return client.get(url + "/api/v1/server-config").status_code < 500
        except Exception:  # noqa: BLE001
            return False

    def lama_available(self) -> bool:
        try:
            import simple_lama_inpainting  # noqa: F401
        except Exception:  # noqa: BLE001
            return False
        return True

    def status(self) -> dict[str, Any]:
        return {
            "demo": self.config.demo_watermark,
            "providers": [
                {"id": "auto", "name": "自动选择", "available": True},
                {"id": "iopaint", "name": "IOPaint / LaMa", "available": self.iopaint_available()},
                {"id": "lama", "name": "Simple LaMa", "available": self.lama_available()},
                {"id": "demo", "name": "演示修复", "available": True},
            ],
            "ffmpeg": bool(shutil.which(self.config.ffmpeg_command)),
            "iopaint_url": self.config.settings().get("iopaint_url") or self.config.iopaint_url,
            "model": self.config.settings().get("watermark_model") or self.config.watermark_model,
            "image_formats": ["png", "jpg", "jpeg", "webp", "bmp"],
            "video_formats": ["mp4", "mov", "webm", "mkv", "avi"],
        }

    # ------------------------------------------------------------------ image
    def _demo_image(self, image: Image.Image, mask: Image.Image) -> Image.Image:
        blurred = image.filter(ImageFilter.GaussianBlur(radius=18))
        median = image.filter(ImageFilter.MedianFilter(size=7))
        fill = Image.blend(blurred, median, 0.35)
        result = image.copy()
        result.paste(fill, (0, 0), mask)
        return result

    def _lama_image(self, image: Image.Image, mask: Image.Image) -> Image.Image:
        try:
            from simple_lama_inpainting import SimpleLama

            model = SimpleLama()
            return model(image.convert("RGB"), mask).convert("RGB")
        except Exception as exc:  # noqa: BLE001
            raise WatermarkError(f"LaMa 修复失败：{exc}") from exc

    def _iopaint_image(self, image: Image.Image, mask: Image.Image) -> Image.Image:
        url = (
            self.config.settings().get("iopaint_url") or self.config.iopaint_url
        ).rstrip("/")
        model = self.config.settings().get("watermark_model") or self.config.watermark_model
        image_buffer = io.BytesIO()
        mask_buffer = io.BytesIO()
        image.save(image_buffer, format="PNG")
        mask.save(mask_buffer, format="PNG")
        try:
            with httpx.Client(timeout=300) as client:
                response = client.post(
                    url + "/api/v1/inpaint",
                    files={
                        "image": ("image.png", image_buffer.getvalue(), "image/png"),
                        "mask": ("mask.png", mask_buffer.getvalue(), "image/png"),
                    },
                    data={"model": model, "hd_strategy": "Original"},
                )
            response.raise_for_status()
            return Image.open(io.BytesIO(response.content)).convert("RGB")
        except Exception as exc:  # noqa: BLE001
            raise WatermarkError(f"IOPaint 修复失败：{exc}") from exc

    def _inpaint(self, image: Image.Image, mask: Image.Image, provider: str) -> Image.Image:
        if provider == "demo":
            return self._demo_image(image, mask)
        if provider == "lama":
            return self._lama_image(image, mask)
        if provider == "iopaint":
            return self._iopaint_image(image, mask)
        raise WatermarkError(f"未知修复服务：{provider}")

    def remove_image(
        self,
        *,
        input_path: Path,
        output_path: Path,
        regions: list[dict[str, Any]] | None = None,
        mask_path: Path | None = None,
        provider: str | None = None,
    ) -> dict[str, Any]:
        try:
            image = Image.open(input_path).convert("RGB")
        except Exception as exc:  # noqa: BLE001
            raise WatermarkError(f"无法读取图片：{exc}") from exc
        mask = (
            _normalize_mask(Image.open(mask_path), image.size)
            if mask_path
            else _regions_mask(image.size, regions or [])
        )
        if mask.getbbox() is None:
            raise WatermarkError("请先标记需要去除的水印区域。")
        selected = self._provider(provider)
        result = self._inpaint(image, mask, selected)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        result.save(output_path, format="PNG")
        return {
            "provider": selected,
            "width": result.width,
            "height": result.height,
        }

    # ------------------------------------------------------------------ video
    def _probe(self, input_path: Path) -> dict[str, Any]:
        ffprobe = shutil.which("ffprobe") or "ffprobe"
        command = [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,r_frame_rate",
            "-of",
            "json",
            str(input_path),
        ]
        try:
            result = subprocess.run(command, capture_output=True, text=True, check=True)
            stream = json.loads(result.stdout)["streams"][0]
            rate = stream.get("r_frame_rate", "25/1").split("/")
            fps = float(rate[0]) / float(rate[1] or 1)
            return {"width": int(stream["width"]), "height": int(stream["height"]), "fps": fps}
        except Exception as exc:  # noqa: BLE001
            raise WatermarkError(f"无法读取视频信息：{exc}") from exc

    def remove_video(
        self,
        *,
        input_path: Path,
        output_path: Path,
        regions: list[dict[str, Any]] | None = None,
        mask_path: Path | None = None,
        provider: str | None = None,
        progress: Progress | None = None,
    ) -> dict[str, Any]:
        if not shutil.which(self.config.ffmpeg_command):
            raise WatermarkError("找不到 ffmpeg，无法处理视频。")
        info = self._probe(input_path)
        mask = (
            _normalize_mask(Image.open(mask_path), (info["width"], info["height"]))
            if mask_path
            else _regions_mask((info["width"], info["height"]), regions or [])
        )
        if mask.getbbox() is None:
            raise WatermarkError("请先标记需要去除的水印区域。")
        selected = self._provider(provider)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="aibox-watermark-") as tmp:
            frame_dir = Path(tmp) / "frames"
            frame_dir.mkdir()
            extract = [
                self.config.ffmpeg_command,
                "-y",
                "-i",
                str(input_path),
                "-fps_mode",
                "passthrough",
                str(frame_dir / "%08d.png"),
            ]
            try:
                subprocess.run(extract, capture_output=True, check=True)
            except subprocess.CalledProcessError as exc:
                raise WatermarkError(f"视频拆帧失败：{exc.stderr[-300:]}") from exc
            frames = sorted(frame_dir.glob("*.png"))
            if not frames:
                raise WatermarkError("视频没有可处理帧。")
            for index, frame_path in enumerate(frames, start=1):
                frame = Image.open(frame_path).convert("RGB")
                repaired = self._inpaint(frame, mask, selected)
                repaired.save(frame_path, format="PNG")
                if progress and (index == 1 or index % 5 == 0 or index == len(frames)):
                    progress(index / len(frames), f"处理帧 {index}/{len(frames)}")
            encode = [
                self.config.ffmpeg_command,
                "-y",
                "-framerate",
                str(info["fps"]),
                "-i",
                str(frame_dir / "%08d.png"),
                "-i",
                str(input_path),
                "-map",
                "0:v:0",
                "-map",
                "1:a?",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "18",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "copy",
                "-shortest",
                str(output_path),
            ]
            try:
                subprocess.run(encode, capture_output=True, check=True)
            except subprocess.CalledProcessError as exc:
                raise WatermarkError(f"视频编码失败：{exc.stderr[-300:]}") from exc
        return {
            "provider": selected,
            "width": info["width"],
            "height": info["height"],
            "fps": info["fps"],
            "frames": len(frames),
        }


def encode_mask_png(mask: Image.Image) -> str:
    buffer = io.BytesIO()
    mask.save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")
