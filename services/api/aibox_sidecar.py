"""Launcher used by PyInstaller to build the Tauri desktop sidecar."""

from __future__ import annotations

import sys

from aibox_api.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
