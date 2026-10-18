#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [ ! -x ".venv/bin/python" ]; then
  echo "Python environment missing. Run scripts/setup.sh first." >&2
  exit 1
fi

.venv/bin/python -m aibox_api --host 127.0.0.1 --port 8765 &
BACKEND_PID=$!
trap 'kill "$BACKEND_PID" 2>/dev/null || true' EXIT

sleep 2
pnpm dev:web
