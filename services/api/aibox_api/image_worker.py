"""Diffusers image worker.

Runs in the user's image Python environment (install diffusers + torch there).
The API talks JSON lines over stdin/stdout. Model-specific call arguments are
filtered with inspect.signature so FLUX/Qwen/SD pipelines can share one worker.
"""

from __future__ import annotations

import argparse
import inspect
import json
import os
import sys
import traceback
from pathlib import Path

_PROTOCOL = None


def _setup_protocol() -> None:
    global _PROTOCOL
    _PROTOCOL = os.fdopen(os.dup(1), "w", buffering=1, encoding="utf-8")
    os.dup2(2, 1)


def _send(payload: dict) -> None:
    assert _PROTOCOL is not None
    _PROTOCOL.write(json.dumps(payload, ensure_ascii=False) + "\n")
    _PROTOCOL.flush()


def load_pipeline(model_dir: str, pipeline: str):
    import torch
    from diffusers import DiffusionPipeline

    mapping = {
        "stable-diffusion": "StableDiffusionPipeline",
        "stable-diffusion-xl": "StableDiffusionXLPipeline",
        "flux": "FluxPipeline",
        "qwen-image": "QwenImagePipeline",
    }
    cls = None
    name = mapping.get(pipeline)
    if name:
        try:
            import diffusers

            cls = getattr(diffusers, name)
        except Exception:
            cls = None
    if cls is None:
        cls = DiffusionPipeline
    dtype = torch.bfloat16 if torch.cuda.is_available() else torch.float32
    pipe = cls.from_pretrained(
        model_dir,
        torch_dtype=dtype,
        local_files_only=True,
    )
    if torch.cuda.is_available():
        pipe.to("cuda")
    if hasattr(pipe, "set_progress_bar_config"):
        pipe.set_progress_bar_config(disable=True)
    return pipe


def _supported_kwargs(pipe, values: dict) -> dict:
    try:
        parameters = set(inspect.signature(pipe.__call__).parameters)
    except (TypeError, ValueError):
        return values
    return {key: value for key, value in values.items() if key in parameters}


def generate(pipe, command: dict) -> list[str]:
    import torch

    output_dir = Path(command["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    seed = int(command.get("seed") or 0)
    batch = max(1, min(8, int(command.get("batch") or 1)))
    generator = torch.Generator(
        device="cuda" if torch.cuda.is_available() else "cpu"
    ).manual_seed(seed)
    values = {
        "prompt": command["prompt"],
        "negative_prompt": command.get("negative_prompt") or None,
        "width": int(command.get("width") or 1024),
        "height": int(command.get("height") or 1024),
        "num_inference_steps": int(command.get("steps") or 28),
        "guidance_scale": float(command.get("guidance") or 3.5),
        "true_cfg_scale": float(command.get("guidance") or 3.5),
        "generator": generator,
        "num_images_per_prompt": batch,
    }
    kwargs = _supported_kwargs(pipe, values)
    if "negative_prompt" in kwargs and kwargs["negative_prompt"] is None:
        kwargs.pop("negative_prompt")
    result = pipe(**kwargs)
    images = list(getattr(result, "images", []) or [])
    paths: list[str] = []
    for index, image in enumerate(images):
        path = output_dir / f"image-{index + 1}.png"
        image.save(path, format="PNG")
        paths.append(str(path))
    return paths


def main() -> int:
    _setup_protocol()
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--pipeline", default="")
    args = parser.parse_args()
    try:
        pipe = load_pipeline(args.model_dir, args.pipeline)
        _send({"type": "ready", "pipeline": args.pipeline})
    except Exception as exc:
        traceback.print_exc()
        _send({"type": "error", "error": f"加载图像模型失败：{exc}"})
        return 1
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            command = json.loads(line)
        except json.JSONDecodeError as exc:
            _send({"type": "error", "error": f"无效命令：{exc}"})
            continue
        if command.get("type") == "shutdown":
            return 0
        command_id = command.get("id")
        try:
            images = generate(pipe, command)
            _send({"type": "result", "id": command_id, "ok": True, "images": images})
        except Exception as exc:
            traceback.print_exc()
            _send(
                {
                    "type": "error",
                    "id": command_id,
                    "ok": False,
                    "error": f"图像生成失败：{exc}",
                }
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
