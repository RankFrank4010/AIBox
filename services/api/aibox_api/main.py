"""AIBox HTTP API: hardware discovery, Whisper models and ASR jobs."""

from __future__ import annotations

import logging
import mimetypes
import os
import urllib.parse
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .asr import AsrPool, WhisperEngine, engine_available
from .catalog import (
    get_model,
    model_catalog,
    recommend_image_model_id,
    recommend_llm_model_id,
    recommend_model_id,
    recommend_tts_model_id,
)
from .community import CommunityRegistry
from .config import APP_NAME, APP_VERSION, AppConfig, get_config
from .devices import DeviceScheduler
from .downloads import DownloadError, DownloadManager
from .external import AUDIO_EXTENSIONS, ExternalAsrGateway, ExternalServiceError
from .hardware import collect_hardware, invalidate_hardware_cache
from .image import ImageEngine
from .image_jobs import ImageJobs
from .image_store import ImageStore
from .jobs import TranscriptionJobs
from .llm import LLMEngine
from .models import (
    delete_model,
    is_model_installed,
    list_installed,
    storage_info,
)
from .runtime import RuntimeManager
from .separation import SeparationEngine
from .separation_jobs import SeparationJobs
from .separation_store import SeparationStore
from .store import TranscriptionStore, render_export
from .training import TrainingEngine, TrainingJobs
from .training_store import TrainingStore
from .translation import TranslationService
from .translation_store import TranslationStore
from .transports.community_api import create_community_router
from .transports.grpc_service import start_grpc_server, stop_grpc_server
from .transports.images_api import create_images_router, create_openai_images_router
from .transports.llm_api import create_llm_router, create_openai_chat_router
from .transports.mrcp import start_mrcp_server, stop_mrcp_server
from .transports.openai_api import create_openai_router
from .transports.separation_api import create_separation_router
from .transports.training_api import create_training_router
from .transports.translation_api import create_translation_router
from .transports.tts_api import create_openai_tts_router, create_tts_router
from .transports.video_api import create_video_router
from .transports.websocket_asr import create_websocket_router
from .tts import TtsEngine
from .video import VideoEngine
from .video_jobs import VideoJobs
from .video_store import VideoStore

logging.basicConfig(
    level=os.getenv("AIBOX_LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("aibox.api")

ALLOWED_AUDIO = AUDIO_EXTENSIONS


def create_app(config: AppConfig | None = None) -> FastAPI:
    cfg = config or get_config()
    store = TranscriptionStore(cfg.database_path)
    image_store = ImageStore(cfg.database_path)
    separation_store = SeparationStore(cfg.database_path)
    video_store = VideoStore(cfg.database_path)
    training_store = TrainingStore(cfg.database_path)
    downloads = DownloadManager(cfg)
    community = CommunityRegistry(cfg)
    runtime = RuntimeManager(cfg)
    scheduler = DeviceScheduler(cfg)
    engine: Any = WhisperEngine(cfg, runtime, community)
    if (
        str(cfg.settings().get("parallel_strategy") or "auto") == "data"
        and len(scheduler.selected_devices()) > 1
    ):
        engine = AsrPool(cfg, runtime, community, scheduler)
    tts_engine = TtsEngine(cfg, runtime, community, scheduler)
    image_engine = ImageEngine(cfg, runtime, scheduler)
    image_jobs = ImageJobs(cfg, image_store, image_engine)
    llm_engine = LLMEngine(cfg, runtime, scheduler)
    separation_engine = SeparationEngine(cfg)
    separation_jobs = SeparationJobs(cfg, separation_store, separation_engine)
    video_engine = VideoEngine(cfg)
    video_jobs = VideoJobs(cfg, video_store, video_engine)
    training_engine = TrainingEngine(cfg, training_store)
    training_jobs = TrainingJobs(cfg, training_store, training_engine)
    translation_service = TranslationService(cfg)
    translation_store = TranslationStore(cfg.database_path)
    jobs = TranscriptionJobs(
        cfg,
        store,
        engine,
        max_workers=max(
            int(cfg.settings().get("max_concurrent_jobs") or 2),
            int(cfg.settings().get("parallel_workers") or 2),
        ),
        scheduler=scheduler,
    )
    gateway = ExternalAsrGateway(cfg, store, jobs)
    runtime.register("asr", engine.unload)
    runtime.register("tts", tts_engine.unload)
    runtime.register("image", image_engine.unload)
    runtime.register("llm", llm_engine.unload)

    def service_status(app: FastAPI) -> dict[str, Any]:
        transport_status = getattr(app.state, "transport_status", {})
        tts_status = tts_engine.status()
        image_status = image_engine.status()
        image_ready = image_status.get("comfyui", {}).get("available") or image_status.get(
            "diffusers", {}
        ).get("runtime_ready")
        image_ready = bool(image_ready or image_status.get("demo"))
        display_host = (
            "127.0.0.1" if cfg.host in {"0.0.0.0", "::", "[::]"} else cfg.host
        )
        http_base = cfg.public_base_url or f"http://{display_host}:{cfg.port}"
        ws_base = http_base.replace("https://", "wss://").replace("http://", "ws://")
        ready = engine_available() or cfg.mock_asr
        tts_ready = tts_status["status"] in {"ready", "demo"}
        return {
            "openai": {
                "status": "ready" if ready else "engine-unavailable",
                "base_url": f"{http_base}/v1",
                "transcriptions": "/v1/audio/transcriptions",
                "speech": "/v1/audio/speech",
                "models": "/v1/models",
                "auth_required": bool(cfg.api_token),
                "response_formats": ["json", "text", "srt", "verbose_json", "vtt"],
            },
            "openai_tts": {
                "status": "ready" if tts_ready else tts_status["status"],
                "base_url": f"{http_base}/v1",
                "speech": "/v1/audio/speech",
                "auth_required": bool(cfg.api_token),
                "formats": ["mp3", "opus", "aac", "flac", "wav", "pcm"],
                "engine": tts_status,
            },
            "openai_images": {
                "status": "ready" if image_ready else "engine-unavailable",
                "base_url": f"{http_base}/v1",
                "generations": "/v1/images/generations",
                "auth_required": bool(cfg.api_token),
                "sizes": ["512x512", "768x768", "1024x1024", "1024x1536", "1536x1024"],
                "engine": image_status,
            },
            "websocket": {
                "status": "ready" if ready else "engine-unavailable",
                "url": f"{ws_base}/ws/asr",
                "path": "/ws/asr",
                "auth_required": bool(cfg.api_token),
                "formats": ["pcm16", "wav", "mp3", "m4a", "webm", "ogg", "flac"],
                "partial_supported": True,
            },
            "grpc": transport_status.get(
                "grpc",
                {
                    "status": "starting",
                    "enabled": cfg.grpc_enabled and cfg.grpc_port > 0,
                    "host": cfg.grpc_host,
                    "port": cfg.grpc_port,
                    "service": "aibox.asr.v1.AsrService",
                    "auth_required": bool(cfg.api_token),
                },
            ),
            "mrcp": transport_status.get(
                "mrcp",
                {
                    "status": "starting",
                    "enabled": cfg.mrcp_enabled and cfg.mrcp_port > 0,
                    "host": cfg.mrcp_host,
                    "port": cfg.mrcp_port,
                    "transport": "SIP/UDP + RTP/AVP + MRCPv2/TCP",
                    "resource": "speechrecog",
                },
            ),
        }

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        interrupted = store.mark_interrupted()
        image_interrupted = image_store.mark_interrupted()
        separation_interrupted = separation_store.mark_interrupted()
        video_interrupted = video_store.mark_interrupted()
        training_interrupted = training_store.mark_interrupted()
        if interrupted:
            logger.info("marked %s interrupted transcription(s)", interrupted)
        if image_interrupted:
            logger.info("marked %s interrupted image generation(s)", image_interrupted)
        if separation_interrupted:
            logger.info("marked %s interrupted separation(s)", separation_interrupted)
        if video_interrupted:
            logger.info("marked %s interrupted video generation(s)", video_interrupted)
        if training_interrupted:
            logger.info("marked %s interrupted training job(s)", training_interrupted)
        grpc_status, grpc_server = await start_grpc_server(cfg, gateway, tts_engine)
        mrcp_status, mrcp_server = await start_mrcp_server(cfg, gateway)
        runtime.start()
        app.state.grpc_server = grpc_server
        app.state.mrcp_server = mrcp_server
        app.state.transport_status = {"grpc": grpc_status, "mrcp": mrcp_status}
        logger.info(
            "external transports: grpc=%s mrcp=%s",
            grpc_status.get("status"),
            mrcp_status.get("status"),
        )
        try:
            yield
        finally:
            await stop_mrcp_server(mrcp_server)
            await stop_grpc_server(grpc_server)
            await runtime.stop()
            jobs.shutdown()
            image_jobs.shutdown()
            separation_jobs.shutdown()
            video_jobs.shutdown()
            training_jobs.shutdown()
            llm_engine.unload()
            tts_engine.unload()
            image_engine.unload()

    app = FastAPI(
        title=f"{APP_NAME} API",
        version=APP_VERSION,
        description="Local-first ASR, TTS, image generation, model downloads and hardware discovery.",
        lifespan=lifespan,
    )
    app.state.config = cfg
    app.state.store = store
    app.state.image_store = image_store
    app.state.downloads = downloads
    app.state.engine = engine
    app.state.tts = tts_engine
    app.state.image = image_engine
    app.state.image_jobs = image_jobs
    app.state.separation = separation_engine
    app.state.separation_jobs = separation_jobs
    app.state.video = video_engine
    app.state.video_jobs = video_jobs
    app.state.training = training_engine
    app.state.training_jobs = training_jobs
    app.state.llm = llm_engine
    app.state.scheduler = scheduler
    app.state.runtime = runtime
    app.state.community = community
    app.state.jobs = jobs
    app.state.gateway = gateway
    app.state.grpc_server = None
    app.state.mrcp_server = None
    app.state.transport_status = {}

    app.include_router(create_openai_router(cfg, gateway, llm_engine.model_list))
    app.include_router(create_openai_chat_router(cfg, llm_engine))
    app.include_router(create_llm_router(cfg, llm_engine))
    app.include_router(create_openai_tts_router(cfg, tts_engine))
    app.include_router(create_tts_router(cfg, tts_engine))
    app.include_router(create_images_router(cfg, image_store, image_jobs, image_engine))
    app.include_router(
        create_openai_images_router(cfg, image_store, image_jobs, image_engine)
    )
    app.include_router(
        create_separation_router(
            cfg, separation_store, separation_jobs, separation_engine
        )
    )
    app.include_router(
        create_video_router(cfg, video_store, video_jobs, video_engine)
    )
    app.include_router(
        create_training_router(
            cfg, training_store, training_jobs, training_engine
        )
    )
    app.include_router(create_community_router(cfg, community))
    app.include_router(
        create_translation_router(translation_service, translation_store)
    )
    app.include_router(create_websocket_router(cfg, gateway))

    @app.exception_handler(ExternalServiceError)
    async def external_service_error_handler(
        request: Request, exc: ExternalServiceError
    ) -> JSONResponse:
        del request
        headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
        return JSONResponse(
            status_code=exc.status_code,
            content=exc.as_openai(),
            headers=headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        if request.url.path.startswith("/v1/"):
            return JSONResponse(
                status_code=400,
                content={
                    "error": {
                        "message": "Invalid request parameters.",
                        "type": "invalid_request_error",
                        "param": None,
                        "code": "invalid_request",
                        "details": exc.errors(),
                    }
                },
            )
        return await request_validation_exception_handler(request, exc)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.cors_origins or ["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ------------------------------------------------------------------ health
    @app.get("/api/devices")
    def devices() -> dict[str, Any]:
        return scheduler.status()

    @app.post("/api/devices/refresh")
    def refresh_devices() -> dict[str, Any]:
        scheduler.refresh()
        return scheduler.status()

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        settings = cfg.settings()
        return {
            "status": "ok",
            "app": APP_NAME,
            "version": APP_VERSION,
            "engine": {
                "id": "demo" if cfg.mock_asr else "faster-whisper",
                "installed": engine_available(),
                "demo": cfg.mock_asr,
                "ready": engine_available() or cfg.mock_asr,
            },
            "platform": collect_hardware()["platform"]["id"],
            "transports": service_status(app),
            "tts": tts_engine.status(),
            "image": image_engine.status(),
            "separation": separation_engine.status(),
            "video": video_engine.status(),
            "llm": llm_engine.status(),
            "training": training_engine.status(),
            "devices": scheduler.status(),
            "runtime": runtime.status(),
            "community": community.list_public()["summary"],
            "settings": settings,
        }

    # ------------------------------------------------------------------ system
    @app.get("/api/system")
    def system() -> dict[str, Any]:
        hardware = collect_hardware()
        installed = list_installed(cfg)
        installed_asr = [entry for entry in installed if entry.get("kind") == "asr"]
        installed_tts = [entry for entry in installed if entry.get("kind") == "tts"]
        installed_image = [entry for entry in installed if entry.get("kind") == "image"]
        installed_llm = [entry for entry in installed if entry.get("kind") == "llm"]
        installed_asr_ids = {entry["id"] for entry in installed_asr}
        installed_tts_ids = {entry["id"] for entry in installed_tts}
        installed_image_ids = {entry["id"] for entry in installed_image}
        installed_llm_ids = {entry["id"] for entry in installed_llm}
        gpu_memory = max(
            (float(item.get("vram_gb") or 0) for item in hardware.get("gpus") or []),
            default=0.0,
        )
        system_memory = float((hardware.get("memory") or {}).get("total_gb") or 0)
        recommendation = hardware["recommendation"]["model_id"]
        recommended_installed = recommendation if recommendation in installed_asr_ids else None
        if not recommended_installed and installed_asr:
            recommended_installed = next(
                (entry["id"] for entry in installed_asr if not entry.get("english_only")),
                installed_asr[0]["id"],
            )
        tts_recommended = recommend_tts_model_id(installed_tts_ids)
        tts_installed_id = tts_recommended if tts_recommended in installed_tts_ids else None
        image_recommended = recommend_image_model_id(
            gpu_memory, installed_ids=installed_image_ids
        )
        image_installed_id = image_recommended if image_recommended in installed_image_ids else None
        llm_recommended = recommend_llm_model_id(
            gpu_memory,
            system_memory,
            installed_ids=installed_llm_ids,
        )
        llm_installed_id = llm_recommended if llm_recommended in installed_llm_ids else None
        return {
            **hardware,
            "storage": storage_info(cfg),
            "models": {
                "installed_count": len(installed),
                "installed_ids": [entry["id"] for entry in installed],
                "asr_installed_count": len(installed_asr),
                "asr_installed_ids": [entry["id"] for entry in installed_asr],
                "tts_installed_count": len(installed_tts),
                "tts_installed_ids": [entry["id"] for entry in installed_tts],
                "image_installed_count": len(installed_image),
                "image_installed_ids": [entry["id"] for entry in installed_image],
                "llm_installed_count": len(installed_llm),
                "llm_installed_ids": [entry["id"] for entry in installed_llm],
                "recommended_id": recommendation,
                "recommended_installed_id": recommended_installed,
                "tts_recommended_id": tts_recommended,
                "tts_recommended_installed_id": tts_installed_id,
                "image_recommended_id": image_recommended,
                "image_recommended_installed_id": image_installed_id,
                "llm_recommended_id": llm_recommended,
                "llm_recommended_installed_id": llm_installed_id,
            },
            "server": {
                "host": cfg.host,
                "port": cfg.port,
                "data_dir": str(cfg.data_dir),
                "hf_endpoint": cfg.hf_endpoint,
                "demo": cfg.mock_asr,
                "demo_tts": cfg.demo_tts,
            },
            "services": service_status(app),
            "tts": tts_engine.status(),
            "image": image_engine.status(),
            "separation": separation_engine.status(),
            "video": video_engine.status(),
            "llm": llm_engine.status(),
            "training": training_engine.status(),
            "devices": scheduler.status(),
            "runtime": runtime.status(),
            "community": community.list_public(),
            "settings": cfg.settings(),
        }

    @app.get("/api/runtime")
    def runtime_status() -> dict[str, Any]:
        return runtime.status()

    @app.patch("/api/runtime")
    def patch_runtime(payload: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "elastic_mode",
            "elastic_idle_ttl_seconds",
            "elastic_switch_interval_seconds",
            "elastic_max_loaded_models",
            "elastic_gpu_reserve_gb",
            "elastic_ram_reserve_gb",
            "elastic_pinned_kinds",
        }
        patch = {key: value for key, value in payload.items() if key in allowed}
        cfg.update_settings(patch)
        runtime.refresh_budget()
        runtime.rebalance()
        return runtime.status()

    @app.post("/api/runtime/unload/{kind}")
    def unload_runtime(kind: str) -> dict[str, Any]:
        if kind not in {"asr", "tts", "image"}:
            raise HTTPException(status_code=400, detail="kind 必须是 asr、tts 或 image")
        try:
            runtime.unload_kind(kind)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return runtime.status()

    @app.get("/api/services")
    def services() -> dict[str, Any]:
        return service_status(app)

    @app.get("/api/services/proto")
    def grpc_proto() -> Response:
        proto = Path(__file__).resolve().parent / "proto" / "aibox_asr.proto"
        if not proto.is_file():
            raise HTTPException(status_code=404, detail="Proto file not found")
        return Response(
            content=proto.read_text(encoding="utf-8"),
            media_type="text/plain; charset=utf-8",
            headers={
                "Content-Disposition": "attachment; filename=aibox_asr.proto"
            },
        )

    @app.get("/api/services/proto/tts")
    def grpc_tts_proto() -> Response:
        proto = Path(__file__).resolve().parent / "proto" / "aibox_tts.proto"
        if not proto.is_file():
            raise HTTPException(status_code=404, detail="Proto file not found")
        return Response(
            content=proto.read_text(encoding="utf-8"),
            media_type="text/plain; charset=utf-8",
            headers={
                "Content-Disposition": "attachment; filename=aibox_tts.proto"
            },
        )

    @app.get("/api/system/refresh")
    def system_refresh() -> dict[str, Any]:
        invalidate_hardware_cache()
        return system()

    # ------------------------------------------------------------------ models
    def _task_for_model(model_id: str) -> dict[str, Any] | None:
        active = [
            task
            for task in downloads.list()
            if task["model_id"] == model_id and task["status"] in {"queued", "downloading", "cancelling"}
        ]
        return active[0] if active else None

    @app.get("/api/models")
    def models() -> dict[str, Any]:
        installed = list_installed(cfg)
        installed_by_id = {entry["id"]: entry for entry in installed}
        installed_asr = [entry for entry in installed if entry.get("kind") == "asr"]
        installed_tts = [entry for entry in installed if entry.get("kind") == "tts"]
        installed_image = [entry for entry in installed if entry.get("kind") == "image"]
        installed_llm = [entry for entry in installed if entry.get("kind") == "llm"]
        catalog: list[dict[str, Any]] = []
        for spec in model_catalog():
            installed_entry = installed_by_id.get(spec["id"])
            catalog.append(
                {
                    **spec,
                    "installed": installed_entry is not None,
                    "installed_at": installed_entry.get("installed_at") if installed_entry else None,
                    "installed_bytes": installed_entry.get("installed_bytes") if installed_entry else 0,
                    "path": installed_entry.get("path") if installed_entry else None,
                    "download": _task_for_model(spec["id"]),
                }
            )
        hardware = collect_hardware()
        recommended = hardware["recommendation"]["model_id"]
        if recommended not in {entry["id"] for entry in installed_asr} and installed_asr:
            installed_pref = next(
                (entry["id"] for entry in installed_asr if not entry.get("english_only")), None
            )
            recommended = installed_pref or recommended
        tts_recommended = recommend_tts_model_id({entry["id"] for entry in installed_tts})
        tts_installed = (
            tts_recommended
            if any(entry["id"] == tts_recommended for entry in installed_tts)
            else (installed_tts[0]["id"] if installed_tts else None)
        )
        gpu_memory = max(
            (float(item.get("vram_gb") or 0) for item in hardware.get("gpus") or []),
            default=0.0,
        )
        image_recommended = recommend_image_model_id(
            gpu_memory, installed_ids={entry["id"] for entry in installed_image}
        )
        image_installed = (
            image_recommended
            if any(entry["id"] == image_recommended for entry in installed_image)
            else (installed_image[0]["id"] if installed_image else None)
        )
        llm_recommended = recommend_llm_model_id(
            gpu_memory,
            float((hardware.get("memory") or {}).get("total_gb") or 0),
            installed_ids={entry["id"] for entry in installed_llm},
        )
        llm_installed = (
            llm_recommended
            if any(entry["id"] == llm_recommended for entry in installed_llm)
            else (installed_llm[0]["id"] if installed_llm else None)
        )
        return {
            "catalog": catalog,
            "installed": installed,
            "downloads": downloads.list(),
            "storage": storage_info(cfg),
            "recommendation": {
                "model_id": hardware["recommendation"]["model_id"],
                "installed_id": recommended if recommended in installed_by_id else None,
                "reason": hardware["recommendation"]["reason"],
            },
            "tts_recommendation": {
                "model_id": tts_recommended,
                "installed_id": tts_installed,
                "reason": "IndexTTS 2.5 支持最多语言与最佳质量；显存不足时可选择 IndexTTS 2。",
            },
            "image_recommendation": {
                "model_id": image_recommended,
                "installed_id": image_installed,
                "reason": "按显存推荐：6 GB 级 SD1.5、10 GB 级 SDXL、20 GB 级 FLUX、32 GB+ Qwen-Image。",
            },
            "llm_recommendation": {
                "model_id": llm_recommended,
                "installed_id": llm_installed,
                "reason": "按内存/显存推荐：4 GB 级 3B、8 GB 级 7B–8B、12 GB+ 12B。",
            },
        }

    @app.post("/api/models/downloads", status_code=202)
    def start_download(payload: dict[str, Any]) -> dict[str, Any]:
        model_id = str(payload.get("model_id") or "").strip()
        spec = get_model(model_id)
        if not spec:
            raise HTTPException(status_code=404, detail="未知模型 ID")
        if spec.external:
            raise HTTPException(
                status_code=409,
                detail="这是社区外部模型，不需要下载；请在社区适配页配置并启用适配器。",
            )
        if is_model_installed(cfg, model_id):
            raise HTTPException(status_code=409, detail="该模型已安装")
        try:
            return downloads.start(model_id)
        except (DownloadError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/models/downloads")
    def list_downloads() -> dict[str, Any]:
        return {"downloads": downloads.list()}

    @app.post("/api/models/downloads/{task_id}/cancel", status_code=202)
    def cancel_download(task_id: str) -> dict[str, Any]:
        if not downloads.cancel(task_id):
            raise HTTPException(status_code=404, detail="下载任务不存在或已结束")
        return {"ok": True, "task": downloads.get(task_id)}

    @app.delete("/api/models/{model_id}")
    def remove_model(model_id: str) -> dict[str, Any]:
        spec = get_model(model_id)
        if spec is None:
            raise HTTPException(status_code=404, detail="未知模型 ID")
        if spec.external:
            raise HTTPException(
                status_code=409,
                detail="社区外部模型请在社区适配页停用适配器，不能删除本地文件。",
            )
        if spec.kind == "asr" and jobs.model_in_use(model_id):
            raise HTTPException(status_code=409, detail="该模型正在转写任务中使用，请稍后再试")
        if spec.kind == "tts":
            if tts_engine.is_busy:
                raise HTTPException(status_code=409, detail="TTS 模型正在合成中，请稍后再试")
            if tts_engine.loaded_model_id == model_id:
                tts_engine.unload()
        if spec.kind == "image":
            if image_jobs.model_in_use(model_id):
                raise HTTPException(status_code=409, detail="图像模型正在生成中使用，请稍后再试")
            if image_engine.loaded_model_id == model_id:
                image_engine.unload()
        if spec.kind == "llm":
            if llm_engine.loaded_model_id == model_id:
                llm_engine.unload()
        downloads.cancel_model(model_id)
        deleted = delete_model(cfg, model_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="模型未安装")
        settings = cfg.settings()
        clear: dict[str, Any] = {}
        if settings.get("default_model") == model_id:
            clear["default_model"] = None
        if settings.get("default_tts_model") == model_id:
            clear["default_tts_model"] = None
        if settings.get("default_image_model") == model_id:
            clear["default_image_model"] = None
        if settings.get("default_llm_model") == model_id:
            clear["default_llm_model"] = None
        if clear:
            cfg.update_settings(clear)
        return {"ok": True}

    # ---------------------------------------------------------------- settings
    @app.get("/api/settings")
    def get_settings() -> dict[str, Any]:
        return cfg.settings()

    @app.patch("/api/settings")
    def patch_settings(payload: dict[str, Any]) -> dict[str, Any]:
        if "default_model" in payload:
            model_id = payload["default_model"]
            if model_id and not is_model_installed(cfg, str(model_id)):
                raise HTTPException(status_code=409, detail="默认模型尚未安装")
            spec = get_model(str(model_id)) if model_id else None
            if model_id and (spec is None or spec.kind != "asr"):
                raise HTTPException(status_code=409, detail="默认 ASR 模型类型不正确")
        if "default_tts_model" in payload:
            model_id = payload["default_tts_model"]
            if model_id and not is_model_installed(cfg, str(model_id)):
                raise HTTPException(status_code=409, detail="默认 TTS 模型尚未安装")
            spec = get_model(str(model_id)) if model_id else None
            if model_id and (spec is None or spec.kind != "tts"):
                raise HTTPException(status_code=409, detail="默认 TTS 模型类型不正确")
        if "default_image_model" in payload:
            model_id = payload["default_image_model"]
            if model_id and not is_model_installed(cfg, str(model_id)):
                raise HTTPException(status_code=409, detail="默认图像模型尚未安装")
            spec = get_model(str(model_id)) if model_id else None
            if model_id and (spec is None or spec.kind != "image"):
                raise HTTPException(status_code=409, detail="默认图像模型类型不正确")
        if "default_llm_model" in payload:
            model_id = payload["default_llm_model"]
            if model_id and not is_model_installed(cfg, str(model_id)):
                raise HTTPException(status_code=409, detail="默认语言模型尚未安装")
            spec = get_model(str(model_id)) if model_id else None
            if model_id and (spec is None or spec.kind != "llm"):
                raise HTTPException(status_code=409, detail="默认语言模型类型不正确")
        settings = cfg.update_settings(payload)
        if any(key.startswith("elastic_") for key in payload):
            runtime.refresh_budget()
            runtime.rebalance()
        if "community_disabled_adapters" in payload:
            community.reload()
        logger.info("settings updated: %s", sorted(payload.keys()))
        return settings

    # ------------------------------------------------------------ transcription
    @app.post("/api/transcriptions", status_code=202)
    async def create_transcription(
        file: UploadFile = File(...),
        model_id: str | None = Form(None),
        language: str = Form("auto"),
        task: str = Form("transcribe"),
        beam_size: int = Form(5),
        vad_filter: bool = Form(True),
        word_timestamps: bool = Form(False),
        device: str = Form("auto"),
        compute_type: str = Form("auto"),
    ) -> dict[str, Any]:
        settings = cfg.settings()
        selected_model = model_id or settings.get("default_model")
        if not selected_model:
            installed_ids = [entry["id"] for entry in list_installed(cfg)]
            selected_model = (
                recommend_model_id(
                    gpu_memory_gb=collect_hardware().get("gpu_memory_gb"),
                    system_memory_gb=collect_hardware().get("memory_gb"),
                    has_cuda=collect_hardware().get("has_cuda", False),
                )
                if installed_ids
                else None
            )
            if selected_model not in installed_ids:
                selected_model = installed_ids[0] if installed_ids else None
        if not selected_model or get_model(selected_model) is None:
            raise HTTPException(status_code=400, detail="请先安装并选择一个 Whisper 模型")
        if not is_model_installed(cfg, selected_model):
            raise HTTPException(status_code=409, detail="所选模型尚未安装完成")
        if not (engine_available() or cfg.mock_asr):
            raise HTTPException(
                status_code=503,
                detail="ASR 引擎未安装：请执行 pip install -e 'services/api[asr]' 后重启 AIBox",
            )
        if language not in {"auto", "zh", "en", "ja", "ko", "de", "fr", "es", "ru", "pt", "it"}:
            language = "auto"
        if task not in {"transcribe", "translate"}:
            task = "transcribe"
        if device not in {"auto", "cpu", "cuda", "npu", "metal"}:
            device = "auto"
        if compute_type not in {
            "auto",
            "int8",
            "int8_float16",
            "int8_float32",
            "float16",
            "float32",
            "bfloat16",
        }:
            compute_type = "auto"

        filename = Path(file.filename or "audio").name
        suffix = Path(filename).suffix.lower()
        if suffix not in ALLOWED_AUDIO:
            raise HTTPException(
                status_code=415,
                detail="不支持的音频格式。请上传 WAV / MP3 / M4A / FLAC / OGG / WEBM 等格式。",
            )

        transcription_id = f"tr_{uuid.uuid4().hex[:14]}"
        audio_path = cfg.uploads_dir / f"{transcription_id}{suffix}"
        max_bytes = cfg.max_upload_mb * 1024 * 1024
        written = 0
        try:
            with audio_path.open("wb") as handle:
                while True:
                    chunk = await file.read(4 * 1024 * 1024)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > max_bytes:
                        raise HTTPException(
                            status_code=413,
                            detail=f"音频超过 {cfg.max_upload_mb} MB 上限",
                        )
                    handle.write(chunk)
        except HTTPException:
            audio_path.unlink(missing_ok=True)
            raise
        except OSError as exc:
            audio_path.unlink(missing_ok=True)
            raise HTTPException(status_code=500, detail=f"无法保存音频：{exc}") from exc
        finally:
            await file.close()

        if written == 0:
            audio_path.unlink(missing_ok=True)
            raise HTTPException(status_code=400, detail="音频文件为空")

        options = {
            "language": language,
            "task": task,
            "beam_size": max(1, min(10, beam_size)),
            "vad_filter": bool(vad_filter),
            "word_timestamps": bool(word_timestamps),
            "device": device,
            "compute_type": compute_type,
        }
        record = store.create(
            id=transcription_id,
            filename=filename,
            audio_path=str(audio_path),
            audio_size=written,
            model_id=selected_model,
            task=task,
            language=language,
            options=options,
        )
        jobs.submit(transcription_id, selected_model, options)
        logger.info(
            "queued transcription %s (%s, %.1f MB) model=%s",
            transcription_id,
            filename,
            written / (1024 * 1024),
            selected_model,
        )
        return record

    @app.get("/api/transcriptions")
    def list_transcriptions(limit: int = 40, offset: int = 0) -> dict[str, Any]:
        limit = max(1, min(100, limit))
        offset = max(0, offset)
        return {"items": store.list(limit=limit, offset=offset)}

    @app.get("/api/transcriptions/{transcription_id}")
    def get_transcription(transcription_id: str) -> dict[str, Any]:
        record = store.get(transcription_id)
        if record is None:
            raise HTTPException(status_code=404, detail="转写记录不存在")
        return record

    @app.post("/api/transcriptions/{transcription_id}/cancel", status_code=202)
    def cancel_transcription(transcription_id: str) -> dict[str, Any]:
        if store.get(transcription_id) is None:
            raise HTTPException(status_code=404, detail="转写记录不存在")
        if not jobs.cancel(transcription_id):
            raise HTTPException(status_code=409, detail="任务不在运行中")
        return {"ok": True}

    @app.delete("/api/transcriptions/{transcription_id}")
    def delete_transcription(transcription_id: str) -> dict[str, Any]:
        record = store.get(transcription_id, include_audio_path=True)
        if record is None:
            raise HTTPException(status_code=404, detail="转写记录不存在")
        if record["status"] in {"queued", "running", "cancelling"}:
            raise HTTPException(status_code=409, detail="请先取消正在运行的任务")
        deleted = store.delete(transcription_id)
        if deleted and deleted.get("audio_path"):
            try:
                audio = Path(deleted["audio_path"]).resolve()
                if audio.is_relative_to(cfg.uploads_dir.resolve()):
                    audio.unlink(missing_ok=True)
            except OSError:
                pass
        return {"ok": True}

    @app.get("/api/transcriptions/{transcription_id}/audio")
    def transcription_audio(transcription_id: str) -> FileResponse:
        record = store.get(transcription_id, include_audio_path=True)
        if record is None or not record.get("audio_path"):
            raise HTTPException(status_code=404, detail="音频不存在")
        try:
            path = Path(record["audio_path"]).resolve()
            if not path.is_relative_to(cfg.uploads_dir.resolve()) or not path.is_file():
                raise HTTPException(status_code=404, detail="音频不存在")
        except OSError:
            raise HTTPException(status_code=404, detail="音频不存在") from None
        media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return FileResponse(path, media_type=media_type, filename=record["filename"])

    @app.get("/api/transcriptions/{transcription_id}/export")
    def export_transcription(transcription_id: str, format: str = "srt") -> Response:
        record = store.get(transcription_id)
        if record is None:
            raise HTTPException(status_code=404, detail="转写记录不存在")
        fmt = format.lower()
        if fmt not in {"txt", "srt", "vtt", "json"}:
            raise HTTPException(status_code=400, detail="导出格式仅支持 txt / srt / vtt / json")
        if record["status"] != "completed":
            raise HTTPException(status_code=409, detail="任务尚未完成")
        content, media_type, filename = render_export(record, fmt)
        quoted = urllib.parse.quote(filename)
        return Response(
            content=content,
            media_type=media_type,
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quoted}"},
        )

    # ------------------------------------------------------------------ static
    dist = cfg.static_dir
    assets = dist / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str, request: Request):
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")
        if dist.is_dir():
            candidate = (dist / full_path).resolve()
            try:
                if full_path and candidate.is_relative_to(dist.resolve()) and candidate.is_file():
                    return FileResponse(candidate)
            except OSError:
                pass
            index = dist / "index.html"
            if index.is_file():
                return FileResponse(index)
        if not full_path:
            return JSONResponse(
                {
                    "app": APP_NAME,
                    "version": APP_VERSION,
                    "message": "AIBox API is running. Build the WebUI with pnpm build:web.",
                    "docs": "/docs",
                }
            )
        raise HTTPException(status_code=404, detail="WebUI not built")

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    config = get_config()
    uvicorn.run(
        "aibox_api.main:app",
        host=config.host,
        port=config.port,
        reload=bool(os.getenv("AIBOX_RELOAD")),
    )
