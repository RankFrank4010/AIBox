"""Image generation engine: native diffusers worker, ComfyUI, and demo mode."""

from __future__ import annotations

import gc
import json
import logging
import queue
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
from PIL import Image, ImageDraw, ImageFont

from .catalog import (
    find_model_by_alias,
    get_image_model,
    image_models,
    recommend_image_model_id,
)
from .config import AppConfig
from .image_workflows import checkpoint_workflow, inject_workflow
from .models import is_model_installed, list_installed
from .runtime import RuntimeCapacityError, RuntimeManager

logger = logging.getLogger("aibox.image")

IMAGE_ALIASES = {
    "dall-e-2": None,
    "dall-e-3": None,
    "gpt-image-1": None,
    "stable-diffusion": "sd15",
    "sdxl": "sdxl",
    "flux": "flux1-schnell",
    "flux.1-schnell": "flux1-schnell",
    "flux.1-dev": "flux1-dev",
    "qwen-image": "qwen-image",
}


class ImageUnavailable(RuntimeError):
    pass


class ComfyUIClient:
    def __init__(self, base_url: str, timeout: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def status(self) -> dict[str, Any]:
        try:
            with httpx.Client(timeout=min(self.timeout, 3)) as client:
                response = client.get(self.base_url + "/system_stats")
            if response.status_code >= 400:
                return {"available": False, "error": f"HTTP {response.status_code}"}
            return {"available": True, "url": self.base_url, "stats": response.json()}
        except Exception as exc:  # noqa: BLE001
            return {"available": False, "url": self.base_url, "error": str(exc)}

    def generate(
        self,
        *,
        workflow: dict[str, Any],
        output_dir: Path,
        timeout: float,
    ) -> list[Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        client_id = uuid.uuid4().hex
        try:
            with httpx.Client(timeout=30) as client:
                response = client.post(
                    self.base_url + "/prompt",
                    json={"prompt": workflow, "client_id": client_id},
                )
            if response.status_code >= 400:
                raise ImageUnavailable(
                    f"ComfyUI 拒绝了工作流（HTTP {response.status_code}）：{response.text[:500]}"
                )
            payload = response.json()
            prompt_id = str(payload.get("prompt_id") or "")
            if not prompt_id:
                raise ImageUnavailable("ComfyUI 没有返回 prompt_id")
        except httpx.HTTPError as exc:
            raise ImageUnavailable(f"无法连接 ComfyUI：{exc}") from exc

        deadline = time.monotonic() + timeout
        history: dict[str, Any] = {}
        while time.monotonic() < deadline:
            try:
                with httpx.Client(timeout=20) as client:
                    response = client.get(f"{self.base_url}/history/{prompt_id}")
                    if response.status_code == 200:
                        history = response.json()
                        if prompt_id in history:
                            break
            except httpx.HTTPError:
                pass
            time.sleep(0.8)
        else:
            raise ImageUnavailable(f"ComfyUI 生成超时（{timeout:.0f}s）")

        entry = history.get(prompt_id) or {}
        outputs = entry.get("outputs") or {}
        images: list[dict[str, Any]] = []
        for node_output in outputs.values():
            if isinstance(node_output, dict):
                for item in node_output.get("images") or []:
                    if isinstance(item, dict) and item.get("filename"):
                        images.append(item)
        if not images:
            raise ImageUnavailable("ComfyUI 没有返回图像；请检查工作流是否包含 SaveImage 节点。")
        paths: list[Path] = []
        for index, item in enumerate(images):
            try:
                with httpx.Client(timeout=60) as client:
                    response = client.get(
                        self.base_url + "/view",
                        params={
                            "filename": item.get("filename"),
                            "subfolder": item.get("subfolder", ""),
                            "type": item.get("type", "output"),
                        },
                    )
                if response.status_code >= 400:
                    raise ImageUnavailable(
                        f"下载 ComfyUI 图像失败（HTTP {response.status_code}）"
                    )
                target = output_dir / f"image-{index + 1}.png"
                target.write_bytes(response.content)
                paths.append(target)
            except httpx.HTTPError as exc:
                raise ImageUnavailable(f"下载 ComfyUI 图像失败：{exc}") from exc
        return paths


class ImageEngine:
    def __init__(self, config: AppConfig, runtime: RuntimeManager | None = None) -> None:
        self.config = config
        self.runtime = runtime
        self._lock = threading.RLock()
        self._worker: subprocess.Popen[str] | None = None
        self._worker_model_id: str | None = None
        self._queue: queue.Queue[str] = queue.Queue()
        self._diffusers_ready: bool | None = None
        self._comfy_cache: tuple[float, dict[str, Any]] | None = None

    # ------------------------------------------------------------------ status
    @property
    def loaded_model_id(self) -> str | None:
        return self._worker_model_id

    def _diffusers_runtime_ready(self) -> bool:
        if self._diffusers_ready is not None:
            return self._diffusers_ready
        python = Path(self.config.image_python or sys.executable)
        if not python.is_file():
            self._diffusers_ready = False
            return False
        try:
            completed = subprocess.run(
                [str(python), "-c", "import diffusers, torch"],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            self._diffusers_ready = completed.returncode == 0
        except (OSError, subprocess.SubprocessError):
            self._diffusers_ready = False
        return bool(self._diffusers_ready)

    def comfy_status(self) -> dict[str, Any]:
        if self._comfy_cache and time.monotonic() - self._comfy_cache[0] < 5:
            return self._comfy_cache[1]
        status = ComfyUIClient(self.config.comfyui_url).status()
        self._comfy_cache = (time.monotonic(), status)
        return status

    def status(self) -> dict[str, Any]:
        installed = [entry for entry in list_installed(self.config, "image")]
        comfy = self.comfy_status()
        return {
            "demo": self.config.demo_image,
            "provider_setting": self.config.settings().get("image_provider", "auto"),
            "comfyui": comfy,
            "comfyui_url": self.config.comfyui_url,
            "diffusers": {
                "runtime_ready": self._diffusers_runtime_ready(),
                "python": self.config.image_python or sys.executable,
                "loaded_model": self._worker_model_id,
            },
            "installed_models": [entry["id"] for entry in installed],
            "recommended_model": recommend_image_model_id(
                installed_ids={entry["id"] for entry in installed}
            ),
        }

    # ----------------------------------------------------------------- models
    def resolve_model(
        self, requested: str | None, *, allow_uninstalled: bool = False
    ) -> dict[str, Any]:
        installed = {entry["id"]: entry for entry in list_installed(self.config, "image")}
        raw = (requested or "").strip()
        if not raw or raw.lower() in IMAGE_ALIASES:
            mapped = IMAGE_ALIASES.get(raw.lower())
            if mapped is None:
                default = self.config.settings().get("default_image_model")
                if default in installed:
                    return installed[default]
                if installed:
                    return installed[recommend_image_model_id(installed_ids=set(installed))]
                mapped = recommend_image_model_id()
        else:
            mapped = raw
        spec = find_model_by_alias(str(mapped), "image")
        if spec is None:
            available = sorted({model.id for model in image_models()})
            raise ImageUnavailable(
                f"未知图像模型 {raw}。可用模型：{', '.join(available)}"
            )
        if spec.id in installed:
            return installed[spec.id]
        if allow_uninstalled or self.config.demo_image:
            return spec.to_dict()
        raise ImageUnavailable(f"图像模型 {spec.id} 尚未安装，请先在模型库下载。")

    # --------------------------------------------------------------- generate
    def generate(
        self,
        *,
        prompt: str,
        negative_prompt: str = "",
        model_id: str | None = None,
        provider: str = "auto",
        width: int = 1024,
        height: int = 1024,
        steps: int = 28,
        guidance: float = 3.5,
        seed: int | None = None,
        batch: int = 1,
        job_id: str = "",
        workflow: dict[str, Any] | None = None,
        checkpoint: str | None = None,
        progress=None,
    ) -> dict[str, Any]:
        prompt = (prompt or "").strip()
        if not prompt:
            raise ImageUnavailable("提示词不能为空。")
        if len(prompt) > 4000:
            raise ImageUnavailable("提示词不能超过 4000 字符。")
        width = max(256, min(2048, int(width)))
        height = max(256, min(2048, int(height)))
        steps = max(1, min(100, int(steps)))
        guidance = max(0.0, min(20.0, float(guidance)))
        batch = max(1, min(8, int(batch)))
        if seed is None:
            seed = int(time.time() * 1000) % 2_147_483_647
        spec = self.resolve_model(model_id, allow_uninstalled=True)
        spec_id = str(spec["id"])
        chosen = self._provider(provider, spec, spec_id)
        job_id = job_id or uuid.uuid4().hex[:12]
        output_dir = self.config.image_outputs_dir / job_id
        if progress:
            progress(8, f"准备 {chosen} 引擎")

        try:
            if chosen == "demo":
                paths = self._demo(
                    prompt=prompt,
                    model_id=spec_id,
                    width=width,
                    height=height,
                    batch=batch,
                    seed=seed,
                    output_dir=output_dir,
                )
                warning = "当前为演示图像引擎，输出为程序生成的示意图。"
            elif chosen == "comfyui":
                paths = self._comfyui(
                    spec=spec,
                    prompt=prompt,
                    negative_prompt=negative_prompt,
                    width=width,
                    height=height,
                    steps=steps,
                    guidance=guidance,
                    seed=seed,
                    batch=batch,
                    output_dir=output_dir,
                    workflow=workflow,
                    checkpoint=checkpoint,
                    progress=progress,
                )
                warning = None
            elif chosen == "diffusers":
                if self.runtime:
                    self.runtime.begin("image")
                try:
                    paths = self._diffusers(
                        spec=spec,
                        prompt=prompt,
                        negative_prompt=negative_prompt,
                        width=width,
                        height=height,
                        steps=steps,
                        guidance=guidance,
                        seed=seed,
                        batch=batch,
                        output_dir=output_dir,
                        progress=progress,
                    )
                finally:
                    if self.runtime:
                        self.runtime.end("image")
                warning = None
            else:
                raise ImageUnavailable(f"未知图像引擎 {chosen}")
        except RuntimeCapacityError as exc:
            raise ImageUnavailable(str(exc)) from exc
        return {
            "paths": paths,
            "provider": chosen,
            "model_id": spec_id,
            "seed": seed,
            "warning": warning,
        }

    def _provider(self, requested: str, spec: dict[str, Any], spec_id: str) -> str:
        requested = (requested or self.config.settings().get("image_provider") or "auto").lower()
        if requested == "demo":
            if not self.config.demo_image:
                raise ImageUnavailable("演示图像引擎未启用（AIBOX_DEMO_IMAGE=1）。")
            return "demo"
        if requested == "comfyui":
            if not self.comfy_status().get("available"):
                raise ImageUnavailable("ComfyUI 不可达，请检查 AIBOX_COMFYUI_URL。")
            return "comfyui"
        if requested == "diffusers":
            return "diffusers"
        if requested != "auto":
            raise ImageUnavailable(f"未知图像 provider：{requested}")
        if is_model_installed(self.config, spec_id) and self._diffusers_runtime_ready():
            return "diffusers"
        if self.comfy_status().get("available"):
            return "comfyui"
        if self.config.demo_image:
            return "demo"
        raise ImageUnavailable(
            "没有可用的图像引擎：请配置 ComfyUI、安装本地 Diffusers 模型，"
            "或设置 AIBOX_DEMO_IMAGE=1 进行界面测试。"
        )

    # ------------------------------------------------------------------ demo
    def _demo(
        self,
        *,
        prompt: str,
        model_id: str,
        width: int,
        height: int,
        batch: int,
        seed: int,
        output_dir: Path,
    ) -> list[Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        paths: list[Path] = []
        palette = [
            ((18, 38, 58), (53, 224, 194)),
            ((41, 27, 70), (167, 139, 250)),
            ((62, 36, 18), (245, 179, 1)),
            ((18, 54, 38), (110, 231, 183)),
        ]
        for index in range(batch):
            start, end = palette[(seed + index) % len(palette)]
            image = Image.new("RGB", (width, height), start)
            draw = ImageDraw.Draw(image)
            for y in range(height):
                ratio = y / max(1, height - 1)
                color = tuple(
                    int(start[channel] * (1 - ratio) + end[channel] * ratio)
                    for channel in range(3)
                )
                draw.line([(0, y), (width, y)], fill=color)
            cx = int(width * (0.28 + ((seed + index * 17) % 40) / 100))
            cy = int(height * (0.32 + ((seed + index * 11) % 30) / 100))
            radius = int(min(width, height) * 0.16)
            draw.ellipse(
                [cx - radius, cy - radius, cx + radius, cy + radius],
                outline=(255, 255, 255, 90),
                width=max(2, radius // 18),
            )
            draw.ellipse(
                [cx - radius // 2, cy - radius // 2, cx + radius // 2, cy + radius // 2],
                fill=tuple(min(255, channel + 25) for channel in end),
            )
            font = ImageFont.load_default()
            label = f"AIBox demo · {model_id} · {width}x{height} · seed {seed + index}"
            draw.text((24, 24), label, fill=(240, 245, 255), font=font)
            words = prompt.split()
            lines: list[str] = []
            line = ""
            for word in words:
                candidate = f"{line} {word}".strip()
                if len(candidate) > 54 and line:
                    lines.append(line)
                    line = word
                else:
                    line = candidate
            if line:
                lines.append(line)
            for line_index, text_line in enumerate(lines[:8]):
                draw.text(
                    (24, height - 150 + line_index * 16),
                    text_line,
                    fill=(235, 242, 250),
                    font=font,
                )
            path = output_dir / f"image-{index + 1}.png"
            image.save(path, format="PNG")
            paths.append(path)
        return paths

    # --------------------------------------------------------------- ComfyUI
    def _comfyui(
        self,
        *,
        spec: dict[str, Any],
        prompt: str,
        negative_prompt: str,
        width: int,
        height: int,
        steps: int,
        guidance: float,
        seed: int,
        batch: int,
        output_dir: Path,
        workflow: dict[str, Any] | None,
        checkpoint: str | None,
        progress,
    ) -> list[Path]:
        selected = workflow or checkpoint_workflow()
        if not isinstance(selected, dict):
            raise ImageUnavailable("ComfyUI 工作流必须是 API 格式的 JSON 对象。")
        checkpoint_name = (
            checkpoint
            or str(spec.get("comfyui_checkpoint") or "")
            or "v1-5-pruned-emaonly.safetensors"
        )
        injected = inject_workflow(
            selected,
            prompt=prompt,
            negative_prompt=negative_prompt,
            width=width,
            height=height,
            steps=steps,
            guidance=guidance,
            seed=seed,
            batch=batch,
            checkpoint=checkpoint_name,
        )
        if progress:
            progress(18, "ComfyUI 正在排队")
        client = ComfyUIClient(self.config.comfyui_url)
        return client.generate(
            workflow=injected,
            output_dir=output_dir,
            timeout=900,
        )

    # -------------------------------------------------------------- diffusers
    def _diffusers(
        self,
        *,
        spec: dict[str, Any],
        prompt: str,
        negative_prompt: str,
        width: int,
        height: int,
        steps: int,
        guidance: float,
        seed: int,
        batch: int,
        output_dir: Path,
        progress,
    ) -> list[Path]:
        model_id = str(spec["id"])
        if not is_model_installed(self.config, model_id):
            raise ImageUnavailable(f"图像模型 {model_id} 尚未安装。")
        self._ensure_worker(model_id)
        if progress:
            progress(25, "Diffusers 正在生成")
        command_id = uuid.uuid4().hex[:12]
        output_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "id": command_id,
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "width": width,
            "height": height,
            "steps": steps,
            "guidance": guidance,
            "seed": seed,
            "batch": batch,
            "output_dir": str(output_dir),
        }
        with self._lock:
            worker = self._worker
            if worker is None or worker.poll() is not None:
                raise ImageUnavailable("Diffusers worker 未运行。")
            try:
                assert worker.stdin is not None
                worker.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
                worker.stdin.flush()
            except (OSError, BrokenPipeError) as exc:
                self._stop_worker()
                raise ImageUnavailable("Diffusers worker 连接中断。") from exc
        response = self._read_message(timeout=1800)
        if not response.get("ok"):
            raise ImageUnavailable(response.get("error") or "Diffusers 推理失败。")
        paths = [Path(item) for item in response.get("images") or []]
        valid = [path for path in paths if path.is_file()]
        if not valid:
            raise ImageUnavailable("Diffusers 没有生成有效图像。")
        if progress:
            progress(92, "图像解码完成")
        return valid

    def _ensure_worker(self, model_id: str) -> None:
        with self._lock:
            if self._worker is not None and self._worker.poll() is None and self._worker_model_id == model_id:
                return
            if self._worker is not None:
                self._stop_worker()
            python = Path(self.config.image_python or sys.executable)
            if not python.is_file():
                raise ImageUnavailable(f"Diffusers Python 不存在：{python}")
            if not self._diffusers_runtime_ready():
                raise ImageUnavailable(
                    "Diffusers 运行时不可用。请设置 AIBOX_IMAGE_PYTHON 并安装 diffusers + torch。"
                )
            model_dir = self.config.image_models_dir / model_id
            if not model_dir.is_dir():
                raise ImageUnavailable(f"图像模型目录不存在：{model_dir}")
            spec = get_image_model(model_id)
            pipeline = spec.pipeline if spec else ""
            reservation = None
            if self.runtime:
                reservation = self.runtime.ensure_capacity("image", model_id)
            worker_script = Path(__file__).resolve().parent / "image_worker.py"
            command = [
                str(python),
                "-u",
                str(worker_script),
                "--model-dir",
                str(model_dir),
                "--pipeline",
                pipeline,
            ]
            creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            try:
                worker = subprocess.Popen(
                    command,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                    creationflags=creationflags,
                )
            except OSError as exc:
                if self.runtime:
                    self.runtime.cancel(reservation)
                raise ImageUnavailable(f"无法启动 Diffusers worker：{exc}") from exc
            self._worker = worker
            self._worker_model_id = model_id
            self._queue = queue.Queue()
            self._start_readers(worker)
            try:
                ready = self._read_message(timeout=1800)
                if ready.get("type") != "ready":
                    raise ImageUnavailable(ready.get("error") or "Diffusers worker 未就绪")
            except Exception:
                self._stop_worker()
                if self.runtime:
                    self.runtime.cancel(reservation)
                raise
            if self.runtime:
                self.runtime.commit(reservation)

    def _start_readers(self, worker: subprocess.Popen[str]) -> None:
        def read_stdout() -> None:
            assert worker.stdout is not None
            for line in worker.stdout:
                self._queue.put(line.strip())

        def read_stderr() -> None:
            assert worker.stderr is not None
            for line in worker.stderr:
                logger.info("[diffusers] %s", line.rstrip())

        threading.Thread(target=read_stdout, daemon=True).start()
        threading.Thread(target=read_stderr, daemon=True).start()

    def _read_message(self, timeout: float) -> dict[str, Any]:
        try:
            line = self._queue.get(timeout=timeout)
        except queue.Empty as exc:
            raise ImageUnavailable(f"Diffusers worker 超时（{timeout:.0f}s）") from exc
        if not line:
            raise ImageUnavailable("Diffusers worker 已退出。")
        try:
            return json.loads(line)
        except json.JSONDecodeError as exc:
            raise ImageUnavailable(f"Diffusers worker 返回非 JSON：{line[:200]}") from exc

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
            self.runtime.note_unloaded("image")
        gc.collect()

    def unload(self) -> None:
        with self._lock:
            self._stop_worker()
