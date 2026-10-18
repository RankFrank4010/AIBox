"""Video generation engine: MiniMax H3/Hailuo, ComfyUI, and demo."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

from .config import AppConfig
from .image import ComfyUIClient
from .video_catalog import VIDEO_MODELS, VideoModel, get_video_model

logger = logging.getLogger("aibox.video")

VIDEO_EXTENSIONS = {".mp4", ".webm", ".mov", ".gif"}


class VideoUnavailable(RuntimeError):
    pass


class VideoEngine:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    # ------------------------------------------------------------------ status
    def minimax_ready(self) -> bool:
        return bool(self.config.minimax_api_key)

    def comfy_status(self) -> dict[str, Any]:
        return ComfyUIClient(self.config.comfyui_url).status()

    def models(self) -> tuple[VideoModel, ...]:
        return VIDEO_MODELS

    def status(self) -> dict[str, Any]:
        comfy = self.comfy_status()
        return {
            "demo": self.config.demo_video,
            "minimax": {
                "configured": self.minimax_ready(),
                "base_url": self.config.minimax_base_url,
                "default_model": self.config.minimax_model,
            },
            "comfyui": comfy,
            "comfyui_url": self.config.comfyui_url,
            "models": [
                {
                    **model.to_dict(),
                    "available": bool(
                        self.config.demo_video
                        or (model.provider == "minimax" and self.minimax_ready())
                        or (model.provider == "comfyui" and comfy.get("available"))
                    ),
                }
                for model in self.models()
            ],
        }

    def resolve_model(self, model_id: str | None) -> VideoModel:
        if model_id:
            model = get_video_model(model_id)
        else:
            model = get_video_model("minimax-h3")
        if model is None:
            available = ", ".join(item.id for item in VIDEO_MODELS)
            raise VideoUnavailable(f"未知视频模型 {model_id}，可用：{available}")
        return model

    # --------------------------------------------------------------- generate
    def generate(
        self,
        *,
        prompt: str,
        model_id: str | None,
        duration: int,
        resolution: str,
        aspect: str,
        seed: int | None,
        workflow: dict[str, Any] | None,
        job_id: str,
        progress=None,
    ) -> dict[str, Any]:
        prompt = (prompt or "").strip()
        if not prompt:
            raise VideoUnavailable("视频提示词不能为空。")
        model = self.resolve_model(model_id)
        provider = self._provider(model)
        duration = max(1, min(model.max_duration, int(duration)))
        if resolution not in model.resolutions:
            resolution = model.resolutions[-1]
        width, height = self._dimensions(aspect, resolution)
        output_dir = self.config.video_outputs_dir / job_id
        output_dir.mkdir(parents=True, exist_ok=True)
        if progress:
            progress(5, f"准备 {model.name}")
        try:
            if provider == "demo":
                path, poster = self._demo(
                    prompt, width, height, duration, output_dir
                )
            elif provider == "minimax":
                path, poster = self._minimax(
                    model,
                    prompt,
                    duration,
                    resolution,
                    output_dir,
                    progress,
                )
            elif provider == "comfyui":
                if not workflow:
                    raise VideoUnavailable(
                        "ComfyUI 视频需要在高级设置中提供 API workflow JSON。"
                    )
                path, poster = self._comfyui(
                    workflow,
                    prompt,
                    width,
                    height,
                    duration,
                    seed,
                    output_dir,
                    progress,
                )
            else:
                raise VideoUnavailable(f"未知视频 provider {provider}")
        except VideoUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001
            raise VideoUnavailable(f"视频生成失败：{exc}") from exc
        if progress:
            progress(96, "整理视频")
        return {
            "path": path,
            "poster": poster,
            "provider": provider,
            "model_id": model.id,
            "duration": duration,
            "resolution": resolution,
            "width": width,
            "height": height,
        }

    def _provider(self, model: VideoModel) -> str:
        if self.config.demo_video:
            return "demo"
        if model.provider == "minimax" and self.minimax_ready():
            return "minimax"
        if model.provider == "comfyui" and self.comfy_status().get("available"):
            return "comfyui"
        raise VideoUnavailable(
            f"{model.name} 不可用：MiniMax 需要 MINIMAX_API_KEY，"
            "ComfyUI 需要 AIBOX_COMFYUI_URL 和高级 workflow；也可以设置 AIBOX_DEMO_VIDEO=1。"
        )

    def _dimensions(self, aspect: str, resolution: str) -> tuple[int, int]:
        if resolution == "480P":
            long_side = 854
        elif resolution in {"720P", "768P"}:
            long_side = 1280
        elif resolution == "2K":
            long_side = 2048
        else:
            long_side = 1920
        short_side = int(long_side * 9 / 16)
        if aspect == "9:16":
            return short_side, long_side
        if aspect == "1:1":
            return long_side, long_side
        if aspect == "4:5":
            return int(long_side * 0.8), long_side
        return long_side, short_side

    # ------------------------------------------------------------------ demo
    def _demo(
        self, prompt: str, width: int, height: int, duration: int, output_dir: Path
    ) -> tuple[Path, Path | None]:
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise VideoUnavailable("演示视频需要 ffmpeg。")
        video = output_dir / "video.mp4"
        command = [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"testsrc2=size={width}x{height}:rate=24:duration={duration}",
            "-vf",
            "format=yuv420p",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "28",
            "-movflags",
            "+faststart",
            str(video),
        ]
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        if completed.returncode != 0:
            raise VideoUnavailable(f"演示视频生成失败：{completed.stderr[-500:]}")
        poster = output_dir / "poster.jpg"
        subprocess.run(
            [
                ffmpeg,
                "-y",
                "-i",
                str(video),
                "-vframes",
                "1",
                str(poster),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if not poster.is_file():
            poster = None
        return video, poster

    # ---------------------------------------------------------------- MiniMax
    def _minimax(
        self,
        model: VideoModel,
        prompt: str,
        duration: int,
        resolution: str,
        output_dir: Path,
        progress,
    ) -> tuple[Path, Path | None]:
        headers = {
            "Authorization": f"Bearer {self.config.minimax_api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": (
                self.config.minimax_model
                if model.id == "minimax-h3" and self.config.minimax_model
                else model.model_arg or self.config.minimax_model
            ),
            "prompt": prompt,
            "prompt_optimizer": True,
            "duration": duration,
            "resolution": resolution,
        }
        try:
            with httpx.Client(timeout=60) as client:
                response = client.post(
                    f"{self.config.minimax_base_url}/video_generation",
                    headers=headers,
                    json=body,
                )
            if response.status_code >= 400:
                raise VideoUnavailable(
                    f"MiniMax 创建任务失败（HTTP {response.status_code}）：{response.text[:500]}"
                )
            payload = response.json()
        except httpx.HTTPError as exc:
            raise VideoUnavailable(f"无法连接 MiniMax：{exc}") from exc
        task_id = _extract_task_id(payload)
        if not task_id:
            raise VideoUnavailable(f"MiniMax 没有返回 task_id：{json.dumps(payload)[:400]}")
        if progress:
            progress(15, "MiniMax 已排队")
        deadline = time.monotonic() + 1800
        file_id = ""
        while time.monotonic() < deadline:
            time.sleep(1.5)
            try:
                with httpx.Client(timeout=30) as client:
                    response = client.get(
                        f"{self.config.minimax_base_url}/query/video_generation",
                        headers=headers,
                        params={"task_id": task_id},
                    )
                payload = response.json()
            except (httpx.HTTPError, ValueError):
                continue
            if progress:
                elapsed = time.monotonic() - (deadline - 1800)
                progress(min(88, 15 + elapsed / 8), "MiniMax 正在生成")
            status = str(
                payload.get("status")
                or (payload.get("data") or {}).get("status")
                or ""
            ).lower()
            if status in {"success", "succeeded", "completed", "succeed"}:
                file_id = _extract_file_id(payload)
                if file_id:
                    break
                raise VideoUnavailable("MiniMax 任务完成但没有 file_id")
            if status in {"fail", "failed", "error"}:
                raise VideoUnavailable(
                    f"MiniMax 生成失败：{payload.get('base_resp') or payload}"
                )
        if not file_id:
            raise VideoUnavailable("MiniMax 视频生成超时")
        try:
            with httpx.Client(timeout=30) as client:
                response = client.get(
                    f"{self.config.minimax_base_url}/files/retrieve",
                    headers=headers,
                    params={"file_id": file_id},
                )
            payload = response.json()
            file_info = payload.get("file") or payload.get("data") or payload
            download_url = file_info.get("download_url") if isinstance(file_info, dict) else None
            if not download_url:
                raise VideoUnavailable("MiniMax 没有返回下载地址")
            with httpx.Client(timeout=300, follow_redirects=True) as client:
                media = client.get(download_url)
            if media.status_code >= 400:
                raise VideoUnavailable(f"下载 MiniMax 视频失败（HTTP {media.status_code}）")
            video = output_dir / "video.mp4"
            video.write_bytes(media.content)
        except httpx.HTTPError as exc:
            raise VideoUnavailable(f"下载 MiniMax 视频失败：{exc}") from exc
        poster = self._poster(video, output_dir)
        return video, poster

    # ---------------------------------------------------------------- ComfyUI
    def _comfyui(
        self,
        workflow: dict[str, Any],
        prompt: str,
        width: int,
        height: int,
        duration: int,
        seed: int | None,
        output_dir: Path,
        progress,
    ) -> tuple[Path, Path | None]:
        values = {
            "prompt": prompt,
            "width": width,
            "height": height,
            "duration": duration,
            "frames": duration * 24,
            "fps": 24,
            "seed": seed if seed is not None else int(time.time()) % 2_147_483_647,
        }
        injected = _inject(workflow, values)
        if progress:
            progress(15, "ComfyUI 正在排队")
        with httpx.Client(timeout=30) as http:
            response = http.post(
                self.config.comfyui_url + "/prompt",
                json={"prompt": injected, "client_id": uuid.uuid4().hex},
            )
        if response.status_code >= 400:
            raise VideoUnavailable(
                f"ComfyUI 拒绝了视频工作流（HTTP {response.status_code}）：{response.text[:500]}"
            )
        prompt_id = str((response.json() or {}).get("prompt_id") or "")
        if not prompt_id:
            raise VideoUnavailable("ComfyUI 没有返回 prompt_id")
        deadline = time.monotonic() + 1800
        history: dict[str, Any] = {}
        while time.monotonic() < deadline:
            time.sleep(1)
            try:
                with httpx.Client(timeout=30) as http:
                    response = http.get(f"{self.config.comfyui_url}/history/{prompt_id}")
                history = response.json()
            except (httpx.HTTPError, ValueError):
                continue
            if prompt_id in history:
                break
            if progress:
                progress(30, "ComfyUI 正在生成视频")
        entry = history.get(prompt_id) or {}
        outputs = entry.get("outputs") or {}
        items = []
        for value in outputs.values():
            if not isinstance(value, dict):
                continue
            for key in ("videos", "gifs", "images"):
                for item in value.get(key) or []:
                    if isinstance(item, dict) and item.get("filename"):
                        items.append(item)
        video_item = next(
            (
                item
                for item in items
                if Path(str(item.get("filename"))).suffix.lower() in VIDEO_EXTENSIONS
            ),
            None,
        )
        if video_item is None:
            raise VideoUnavailable(
                "ComfyUI 工作流没有返回视频；请确认使用 SaveVideo / VHS_VideoCombine 节点。"
            )
        with httpx.Client(timeout=300) as http:
            response = http.get(
                self.config.comfyui_url + "/view",
                params={
                    "filename": video_item.get("filename"),
                    "subfolder": video_item.get("subfolder", ""),
                    "type": video_item.get("type", "output"),
                },
            )
        if response.status_code >= 400:
            raise VideoUnavailable(f"下载 ComfyUI 视频失败（HTTP {response.status_code}）")
        video = output_dir / "video.mp4"
        video.write_bytes(response.content)
        poster = self._poster(video, output_dir)
        return video, poster

    def _poster(self, video: Path, output_dir: Path) -> Path | None:
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            return None
        poster = output_dir / "poster.jpg"
        subprocess.run(
            [ffmpeg, "-y", "-i", str(video), "-vframes", "1", str(poster)],
            capture_output=True,
            text=True,
            check=False,
        )
        return poster if poster.is_file() else None


def _extract_task_id(payload: dict[str, Any]) -> str:
    if not isinstance(payload, dict):
        return ""
    if payload.get("task_id"):
        return str(payload["task_id"])
    data = payload.get("data")
    if isinstance(data, dict) and data.get("task_id"):
        return str(data["task_id"])
    return ""


def _extract_file_id(payload: dict[str, Any]) -> str:
    if not isinstance(payload, dict):
        return ""
    if payload.get("file_id"):
        return str(payload["file_id"])
    data = payload.get("data")
    if isinstance(data, dict) and data.get("file_id"):
        return str(data["file_id"])
    return ""


def _inject(workflow: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
    def replace(value: Any) -> Any:
        if isinstance(value, str):
            result = value
            for key, replacement in values.items():
                result = result.replace("{{" + key + "}}", str(replacement))
            return result
        if isinstance(value, list):
            return [replace(item) for item in value]
        if isinstance(value, dict):
            return {key: replace(item) for key, item in value.items()}
        return value

    return replace(workflow)
