"""Standalone cluster coordinator.

This process contains no ASR/TTS/LLM engines. It is intended for a control-plane
host that is not allowed to run AI inference:

    python -m aibox_api.coordinator --host 0.0.0.0 --port 8765

Workers on other physical machines register here and execute AI workloads.
"""

from __future__ import annotations

import argparse

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .cluster import ClusterManager
from .config import APP_NAME, APP_VERSION, AppConfig, get_config
from .protocol import PROTOCOL_HEADER, PROTOCOL_VERSION
from .transports.cluster_api import create_cluster_router


def create_coordinator_app(config: AppConfig | None = None) -> FastAPI:
    cfg = config or get_config()
    cluster = ClusterManager(cfg)
    app = FastAPI(
        title=f"{APP_NAME} Coordinator",
        version=APP_VERSION,
        description="Control plane only: cluster registry and scheduling.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(create_cluster_router(cfg, cluster))

    @app.get("/api/health")
    def health() -> dict[str, object]:
        return {
            "status": "ok",
            "role": "coordinator",
            "ai_inference": False,
            "version": APP_VERSION,
            "cluster": cluster.status(),
        }

    @app.get("/")
    def root() -> JSONResponse:
        return JSONResponse(
            {
                "service": APP_NAME,
                "role": "cluster-coordinator",
                "ai_inference": False,
                "protocol": PROTOCOL_VERSION,
                "status": "/api/cluster/status",
            },
            headers={PROTOCOL_HEADER: PROTOCOL_VERSION},
        )

    return app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="aibox-coordinator")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    uvicorn.run(
        create_coordinator_app(get_config()),
        host=args.host,
        port=args.port,
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
