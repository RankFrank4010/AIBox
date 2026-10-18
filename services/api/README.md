# AIBox API

FastAPI service for AIBox: hardware discovery, Whisper model downloads, local
transcription jobs, SQLite history, and SRT/VTT/TXT/JSON export.

External transports share the same job pipeline:

- OpenAI-compatible `POST /v1/audio/transcriptions`
- WebSocket `WS /ws/asr`
- gRPC `aibox.asr.v1.AsrService` on port 50051
- MRCPv2 `speechrecog` on SIP/UDP 8060, control 8061/TCP, RTP 50000-50100/UDP

The WebUI is built separately from `apps/web` and served by this process in
single-host deployments.

## Run

```bash
python -m pip install -e ".[asr,dev]"
python -m aibox_api --host 127.0.0.1 --port 8765
```

## Optional extras

- `asr`: faster-whisper, PyAV
- `cuda12`: NVIDIA cuBLAS / cuDNN user-space libraries
- `desktop`: PyInstaller for the Tauri sidecar

See the repository [README](../../README.md) and [API documentation](../../docs/api.md).
