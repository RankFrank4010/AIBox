#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [ ! -x ".venv/bin/python" ]; then
  echo "Python environment missing. Run scripts/setup.sh first." >&2
  exit 1
fi

.venv/bin/python -m pip install -e "services/api[desktop]"
TRIPLE="$(rustc -vV | awk '/^host:/ {print $2}')"
echo "[AIBox] Building API sidecar for $TRIPLE ..."

.venv/bin/python -m PyInstaller \
  --noconfirm --clean --onefile \
  --name aibox-server \
  --distpath build/sidecar-dist \
  --workpath build/sidecar \
  --specpath build/sidecar \
  --collect-all ctranslate2 \
  --collect-all faster_whisper \
  --collect-all tokenizers \
  --collect-all onnxruntime \
  --collect-all av \
  --collect-submodules uvicorn \
  --collect-submodules grpc \
  --collect-submodules grpc_reflection \
  --collect-submodules aibox_api \
  services/api/aibox_sidecar.py

mkdir -p apps/desktop/src-tauri/binaries
cp "build/sidecar-dist/aibox-server" "apps/desktop/src-tauri/binaries/aibox-server-$TRIPLE"
echo "[AIBox] Sidecar ready. Next: pnpm --filter @aibox/desktop build"
