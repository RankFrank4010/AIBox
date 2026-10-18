#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOME_DIR="${AIBOX_INDEXTTS_HOME:-$ROOT/runtimes/index-tts}"
REPO_URL="https://github.com/index-tts/index-tts.git"

command -v git >/dev/null || { echo "git is required" >&2; exit 1; }
command -v uv >/dev/null || { echo "uv is required: pip install -U uv" >&2; exit 1; }

if [ ! -d "$HOME_DIR/indextts" ]; then
  echo "[AIBox] Cloning IndexTTS runtime to $HOME_DIR ..."
  mkdir -p "$(dirname "$HOME_DIR")"
  git clone --depth 1 "$REPO_URL" "$HOME_DIR"
else
  echo "[AIBox] IndexTTS checkout already exists: $HOME_DIR"
fi

echo "[AIBox] Installing IndexTTS dependencies with uv (this can take a long time)..."
(cd "$HOME_DIR" && uv sync)

echo ""
echo "[AIBox] IndexTTS runtime is ready."
echo "Set these before starting AIBox:"
echo "  AIBOX_INDEXTTS_HOME=$HOME_DIR"
echo "  AIBOX_INDEXTTS_PYTHON=$HOME_DIR/.venv/bin/python"
echo ""
echo "Then open the model library → IndexTTS and download IndexTTS 2.5 or 2."
