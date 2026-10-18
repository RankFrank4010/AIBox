#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON="${PYTHON:-python3}"
if [ ! -x ".venv/bin/python" ]; then
  echo "[AIBox] Creating Python virtual environment..."
  "$PYTHON" -m venv .venv
fi

echo "[AIBox] Installing Python API (ASR + dev tools)..."
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e "services/api[dev,asr]"

if [[ "${1:-}" == "--cuda" ]]; then
  echo "[AIBox] Installing optional NVIDIA CUDA 12 runtime libraries..."
  .venv/bin/python -m pip install -e "services/api[cuda12]"
fi

if ! command -v pnpm >/dev/null 2>&1; then
  echo "[AIBox] pnpm was not found. Install Node.js 20+ and pnpm 10+."
  exit 1
fi

pnpm install --store-dir .pnpm-store
echo "[AIBox] Setup complete. Linux runs the Fluent WebUI only."
echo "  Dev:      ./scripts/dev.sh"
echo "  Prod:     ./scripts/start.sh"
