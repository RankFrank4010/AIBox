"""IndexTTS subprocess worker.

This file is executed by the index-tts Python environment, not necessarily by
the AIBox API environment. It speaks a line-delimited JSON protocol on stdout;
all third-party stdout/stderr noise is redirected to stderr.

Example:
    python -u tts_worker.py --repo .../index-tts \
      --model-dir .../models/tts/indextts-2.5 --variant 2.5
"""

from __future__ import annotations

import argparse
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


def load_model(repo: str, model_dir: str, variant: str, device: str = "auto"):
    repo_path = str(Path(repo).resolve())
    if repo_path not in sys.path:
        sys.path.insert(0, repo_path)
    try:
        import torch

        use_cuda = torch.cuda.is_available() and device != "cpu"
        if use_cuda and device.startswith("cuda:"):
            torch.cuda.set_device(int(device.split(":", 1)[1]))
    except Exception:
        use_cuda = False
    cfg = str(Path(model_dir) / "config.yaml")
    if variant == "2.5":
        from indextts.infer_v2_5 import IndexTTS2

        return IndexTTS2(
            cfg_path=cfg,
            model_dir=model_dir,
            use_bf16=use_cuda,
        ), variant
    from indextts.infer_v2 import IndexTTS2

    return IndexTTS2(
        cfg_path=cfg,
        model_dir=model_dir,
        use_fp16=use_cuda,
        use_cuda_kernel=False,
        use_deepspeed=False,
    ), variant


def synthesize(tts, command: dict, variant: str) -> None:
    output = Path(command["output"])
    output.parent.mkdir(parents=True, exist_ok=True)
    reference = command["reference"]
    text = command["text"]
    speed = max(0.25, min(4.0, float(command.get("speed") or 1.0)))
    language = (command.get("language") or "en").upper()
    if variant == "2.5":
        duration_factor = max(0.5, min(2.0, 1.0 / speed))
        tts.infer(
            spk_audio_prompt=reference,
            text=text,
            lang=language,
            output_path=str(output),
            duration_factor=duration_factor,
            verbose=False,
        )
    else:
        tts.infer(
            spk_audio_prompt=reference,
            text=text,
            output_path=str(output),
            verbose=False,
        )


def main() -> int:
    _setup_protocol()
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--variant", choices=("2", "2.5"), default="2.5")
    parser.add_argument("--device", default="auto")
    args = parser.parse_args()

    try:
        tts, variant = load_model(args.repo, args.model_dir, args.variant, args.device)
        _send({"type": "ready", "variant": variant})
    except Exception as exc:
        traceback.print_exc()
        _send({"type": "error", "error": f"模型加载失败：{exc}"})
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
            synthesize(tts, command, variant)
            _send({"type": "result", "id": command_id, "ok": True, "output": command["output"]})
        except Exception as exc:
            traceback.print_exc()
            _send({"type": "error", "id": command_id, "ok": False, "error": f"推理失败：{exc}"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
