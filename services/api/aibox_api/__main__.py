"""CLI entry point for the AIBox API server."""

from __future__ import annotations

import argparse
import os
import sys

import uvicorn

from .config import get_config


def main(argv: list[str] | None = None) -> int:
    config = get_config()
    parser = argparse.ArgumentParser(
        prog="aibox",
        description="AIBox — local-first AI model studio (ASR / Whisper).",
    )
    parser.add_argument("--host", default=config.host, help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=config.port, help="Bind port (default: 8765)")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload for development")
    parser.add_argument("--open", action="store_true", help="Open the WebUI in the default browser")
    args = parser.parse_args(argv)

    if args.open:
        import threading
        import time
        import webbrowser

        def open_browser() -> None:
            time.sleep(1.2)
            webbrowser.open(f"http://{args.host if args.host not in {'0.0.0.0', '::'} else '127.0.0.1'}:{args.port}")

        threading.Thread(target=open_browser, daemon=True).start()

    os.environ.setdefault("AIBOX_HOST", args.host)
    os.environ.setdefault("AIBOX_PORT", str(args.port))
    uvicorn.run(
        "aibox_api.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level=os.getenv("AIBOX_LOG_LEVEL", "info").lower(),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
