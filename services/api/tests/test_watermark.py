"""Watermark removal image/video tests with the demo provider."""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from aibox_api.config import AppConfig
from aibox_api.main import create_app


def make_client(tmp_path: Path) -> TestClient:
    config = AppConfig(
        data_dir=tmp_path / "data",
        mock_asr=True,
        demo_tts=True,
        demo_image=True,
        demo_separation=True,
        demo_video=True,
        demo_llm=True,
        demo_training=True,
        demo_translation=True,
        demo_ocr=True,
        demo_watermark=True,
        grpc_port=0,
        mrcp_port=0,
    )
    return TestClient(create_app(config))


def test_image_watermark_removal(tmp_path):
    client = make_client(tmp_path)
    image_path = tmp_path / "watermarked.png"
    image = Image.new("RGB", (320, 240), "#355c7d")
    draw = ImageDraw.Draw(image)
    draw.rectangle([220, 190, 310, 225], fill="white")
    image.save(image_path)

    with image_path.open("rb") as handle:
        response = client.post(
            "/api/watermarks/images",
            files={"file": ("watermarked.png", handle, "image/png")},
            data={
                "provider": "demo",
                "regions": '[{"x":0.68,"y":0.78,"w":0.29,"h":0.16}]',
            },
        )
    assert response.status_code == 200, response.text
    record = response.json()
    assert record["status"] == "completed"
    assert client.get(f"/api/watermarks/{record['id']}/file").status_code == 200
    assert any(item["id"] == record["id"] for item in client.get("/api/watermarks").json()["records"])
    assert client.delete(f"/api/watermarks/{record['id']}").status_code == 200


def test_video_watermark_removal(tmp_path):
    if not shutil.which("ffmpeg"):
        return
    client = make_client(tmp_path)
    video_path = tmp_path / "watermarked.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=160x120:d=1:r=8",
            "-pix_fmt",
            "yuv420p",
            str(video_path),
        ],
        capture_output=True,
        check=True,
    )
    with video_path.open("rb") as handle:
        response = client.post(
            "/api/watermarks/videos",
            files={"file": ("watermarked.mp4", handle, "video/mp4")},
            data={
                "provider": "demo",
                "regions": '[{"x":0.55,"y":0.55,"w":0.35,"h":0.3}]',
            },
        )
    assert response.status_code == 202, response.text
    job_id = response.json()["id"]
    record = {}
    for _ in range(120):
        record = client.get(f"/api/watermarks/{job_id}").json()
        if record["status"] in {"completed", "failed"}:
            break
        time.sleep(0.25)
    assert record["status"] == "completed", record
    assert client.get(f"/api/watermarks/{job_id}/file").status_code == 200
