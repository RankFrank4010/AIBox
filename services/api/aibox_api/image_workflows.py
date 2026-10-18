"""Hidden ComfyUI workflow helpers.

The default AIBox image form does not expose node graphs. A built-in checkpoint
workflow is used for SD/SDXL. Advanced users can supply a ComfyUI API workflow
with {{placeholders}}; the same injector fills prompt/seed/size/steps fields.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def checkpoint_workflow() -> dict[str, Any]:
    return {
        "3": {
            "class_type": "KSampler",
            "inputs": {
                "seed": "{{seed}}",
                "steps": "{{steps}}",
                "cfg": "{{guidance}}",
                "sampler_name": "euler",
                "scheduler": "normal",
                "denoise": 1,
                "model": ["4", 0],
                "positive": ["6", 0],
                "negative": ["7", 0],
                "latent_image": ["5", 0],
            },
        },
        "4": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "{{checkpoint}}"},
        },
        "5": {
            "class_type": "EmptyLatentImage",
            "inputs": {
                "width": "{{width}}",
                "height": "{{height}}",
                "batch_size": "{{batch}}",
            },
        },
        "6": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": "{{prompt}}", "clip": ["4", 1]},
            "_meta": {"title": "positive"},
        },
        "7": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": "{{negative_prompt}}", "clip": ["4", 1]},
            "_meta": {"title": "negative"},
        },
        "8": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["3", 0], "vae": ["4", 2]},
        },
        "9": {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": "aibox", "images": ["8", 0]},
        },
    }


def inject_workflow(
    workflow: dict[str, Any],
    *,
    prompt: str,
    negative_prompt: str,
    width: int,
    height: int,
    steps: int,
    guidance: float,
    seed: int,
    batch: int,
    checkpoint: str,
) -> dict[str, Any]:
    data = deepcopy(workflow)
    values = {
        "prompt": prompt,
        "negative_prompt": negative_prompt,
        "width": width,
        "height": height,
        "steps": steps,
        "guidance": guidance,
        "seed": seed,
        "batch": batch,
        "checkpoint": checkpoint,
    }

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

    data = replace(data)
    for node in data.values():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            continue
        class_type = str(node.get("class_type") or "")
        title = str((node.get("_meta") or {}).get("title") or "").lower()
        if class_type in {"EmptyLatentImage", "EmptySD3LatentImage"}:
            inputs["width"] = width
            inputs["height"] = height
            inputs["batch_size"] = batch
        elif class_type in {"KSampler", "KSamplerAdvanced"}:
            inputs["seed"] = seed
            inputs["steps"] = steps
            if "cfg" in inputs:
                inputs["cfg"] = guidance
        elif class_type == "FluxGuidance":
            inputs["guidance"] = guidance
        elif class_type == "CLIPTextEncode" and title:
            if "negative" in title:
                inputs["text"] = negative_prompt
            elif "positive" in title or "prompt" in title:
                inputs["text"] = prompt
        if "filename_prefix" in inputs and inputs["filename_prefix"] == "aibox":
            inputs["filename_prefix"] = "aibox"
    return data
