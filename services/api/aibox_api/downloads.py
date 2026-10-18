"""Resumable-free Whisper model downloader backed by Hugging Face."""

from __future__ import annotations

import json
import shutil
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .catalog import ModelSpec, get_model
from .config import AppConfig
from .models import directory_size, is_model_installed, model_base_dir, utc_now

USER_AGENT = "AIBox/0.1 (+https://github.com/aibox)"
CHUNK_SIZE = 1024 * 1024
ROOT_FILE_SUFFIXES = {".bin", ".json", ".txt", ".model", ".tiktoken", ".vocab"}
FALLBACK_FILES = (
    "config.json",
    "model.bin",
    "tokenizer.json",
    "vocabulary.txt",
    "vocabulary.json",
    "preprocessor_config.json",
)


class DownloadCancelled(Exception):
    pass


class DownloadError(Exception):
    pass


@dataclass
class DownloadTask:
    id: str
    model_id: str
    model_name: str
    status: str = "queued"
    bytes_downloaded: int = 0
    total_bytes: int = 0
    files_done: int = 0
    files_total: int = 0
    current_file: str | None = None
    error: str | None = None
    created_at: str = field(default_factory=utc_now)
    started_at: str | None = None
    completed_at: str | None = None
    speed_bps: float = 0.0
    eta_seconds: int | None = None
    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)
    started_monotonic: float = 0.0

    @property
    def progress(self) -> float:
        if self.total_bytes > 0:
            return round(min(100.0, self.bytes_downloaded / self.total_bytes * 100), 1)
        return 0.0

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "id": self.id,
                "model_id": self.model_id,
                "model_name": self.model_name,
                "status": self.status,
                "bytes_downloaded": self.bytes_downloaded,
                "total_bytes": self.total_bytes,
                "progress": self.progress,
                "files_done": self.files_done,
                "files_total": self.files_total,
                "current_file": self.current_file,
                "speed_bps": round(self.speed_bps),
                "eta_seconds": self.eta_seconds,
                "error": self.error,
                "created_at": self.created_at,
                "started_at": self.started_at,
                "completed_at": self.completed_at,
            }


class DownloadManager:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self._tasks: dict[str, DownloadTask] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._lock = threading.RLock()
        self.cleanup_stale()

    # ------------------------------------------------------------------ public
    def cleanup_stale(self) -> None:
        for base in (
            self.config.models_dir,
            self.config.tts_models_dir,
            self.config.image_models_dir,
            self.config.llm_models_dir,
        ):
            if not base.exists():
                continue
            for child in base.iterdir():
                if child.is_dir() and child.name.startswith(".") and child.name.endswith(".download"):
                    shutil.rmtree(child, ignore_errors=True)

    def start(self, model_id: str) -> dict[str, Any]:
        spec = get_model(model_id)
        if spec is None:
            raise KeyError(model_id)
        if is_model_installed(self.config, model_id):
            raise ValueError("该模型已安装")
        with self._lock:
            for task in self._tasks.values():
                if task.model_id == model_id and task.status in {"queued", "downloading"}:
                    return task.snapshot()
            task = DownloadTask(
                id=f"dl_{uuid.uuid4().hex[:12]}",
                model_id=model_id,
                model_name=spec.name,
            )
            self._tasks[task.id] = task
            thread = threading.Thread(
                target=self._run,
                args=(task, spec),
                name=f"aibox-download-{model_id}",
                daemon=True,
            )
            self._threads[task.id] = thread
            thread.start()
            return task.snapshot()

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            tasks = sorted(self._tasks.values(), key=lambda task: task.created_at, reverse=True)
            return [task.snapshot() for task in tasks]

    def get(self, task_id: str) -> dict[str, Any] | None:
        with self._lock:
            task = self._tasks.get(task_id)
            return task.snapshot() if task else None

    def cancel(self, task_id: str) -> bool:
        with self._lock:
            task = self._tasks.get(task_id)
        if task is None:
            return False
        if task.status in {"completed", "failed", "cancelled"}:
            return False
        task.cancel_event.set()
        with task.lock:
            task.status = "cancelling"
        return True

    def cancel_model(self, model_id: str) -> int:
        count = 0
        with self._lock:
            for task in self._tasks.values():
                if task.model_id == model_id and task.status in {"queued", "downloading"}:
                    if self.cancel(task.id):
                        count += 1
        return count

    # ----------------------------------------------------------------- internal
    def _run(self, task: DownloadTask, spec: ModelSpec) -> None:
        base_dir = model_base_dir(self.config, spec.id)
        destination = base_dir / spec.id
        temp_dir = base_dir / f".{spec.id}.download"
        try:
            with task.lock:
                task.status = "downloading"
                task.started_at = utc_now()
                task.started_monotonic = time.monotonic()

            if destination.exists():
                raise DownloadError("模型目录已存在，请刷新后重试")
            if temp_dir.exists():
                shutil.rmtree(temp_dir)
            temp_dir.mkdir(parents=True)

            self._check_disk_space(spec)
            files = self._discover_files(spec)
            if spec.kind == "asr" and "model.bin" not in files:
                raise DownloadError("远程仓库缺少 model.bin，无法安装")
            if spec.kind != "asr" and not files:
                raise DownloadError("远程仓库没有可下载的模型文件")

            sizes: dict[str, int] = {}
            for name in files:
                self._check_cancel(task)
                size = self._head_size(spec, name)
                if size is None:
                    if name in spec.required_files:
                        raise DownloadError(f"无法获取 {name} 的大小")
                    continue
                sizes[name] = size
                with task.lock:
                    task.total_bytes += size
            files = [name for name in files if name in sizes]
            if spec.kind == "asr" and "model.bin" not in files:
                raise DownloadError("远程仓库无法下载 model.bin")

            with task.lock:
                task.files_total = len(files)

            completed_files: list[dict[str, Any]] = []
            for name in files:
                self._check_cancel(task)
                with task.lock:
                    task.current_file = name
                target = temp_dir / Path(name)
                if target.resolve() != temp_dir.resolve() and temp_dir.resolve() not in target.resolve().parents:
                    raise DownloadError(f"非法的模型文件路径：{name}")
                target.parent.mkdir(parents=True, exist_ok=True)
                self._download_file(task, spec, name, target, sizes[name])
                with task.lock:
                    task.files_done += 1
                completed_files.append(
                    {"name": name, "bytes": sizes[name], "url": self._file_url(spec, name)}
                )

            for required in spec.required_files:
                file = temp_dir / required
                if not file.is_file() or file.stat().st_size <= 0:
                    raise DownloadError(f"安装校验失败：缺少 {required}")

            manifest = {
                "model_id": spec.id,
                "repo": spec.repo,
                "installed_at": utc_now(),
                "source": self.config.hf_endpoint,
                "verified": True,
                "bytes": directory_size(temp_dir),
                "files": completed_files,
            }
            (temp_dir / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            temp_dir.rename(destination)
            with task.lock:
                task.status = "completed"
                task.current_file = None
                task.completed_at = utc_now()
                task.bytes_downloaded = task.total_bytes or task.bytes_downloaded
                task.speed_bps = 0
                task.eta_seconds = 0
        except DownloadCancelled:
            shutil.rmtree(temp_dir, ignore_errors=True)
            with task.lock:
                task.status = "cancelled"
                task.current_file = None
                task.completed_at = utc_now()
                task.speed_bps = 0
                task.eta_seconds = None
        except Exception as exc:  # noqa: BLE001 - surfaced to the UI verbatim
            shutil.rmtree(temp_dir, ignore_errors=True)
            with task.lock:
                task.status = "failed"
                task.error = _human_error(exc)
                task.current_file = None
                task.completed_at = utc_now()
                task.speed_bps = 0
                task.eta_seconds = None

    def _check_disk_space(self, spec: ModelSpec) -> None:
        try:
            free = shutil.disk_usage(model_base_dir(self.config, spec.id)).free
        except OSError:
            return
        if free < spec.size_bytes * 0.95:
            need = spec.size_bytes / (1024**3)
            have = free / (1024**3)
            raise DownloadError(f"磁盘空间不足：需要约 {need:.1f} GB，可用 {have:.1f} GB")

    def _discover_files(self, spec: ModelSpec) -> list[str]:
        if spec.download_files:
            return list(spec.download_files)
        url = f"{self.config.hf_endpoint}/api/models/{spec.repo}"
        request = urllib.request.Request(url, headers=self._headers(accept="application/json"))
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code in {401, 403}:
                raise DownloadError(
                    "Hugging Face 拒绝访问（模型可能受地区或授权限制），"
                    "可配置 HF_TOKEN 或使用镜像 AIBOX_HF_ENDPOINT"
                ) from exc
            if exc.code == 404:
                raise DownloadError(f"找不到模型仓库 {spec.repo}") from exc
            raise DownloadError(f"获取模型文件列表失败（HTTP {exc.code}）") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise DownloadError(f"无法连接 Hugging Face：{_human_error(exc)}") from exc

        siblings = data.get("siblings") if isinstance(data, dict) else None
        if not isinstance(siblings, list):
            return list(FALLBACK_FILES) if not spec.recursive_download else []
        files: list[str] = []
        for sibling in siblings:
            name = str(sibling.get("rfilename") or "") if isinstance(sibling, dict) else ""
            if not name or name.startswith("."):
                continue
            if spec.recursive_download:
                if name.lower().endswith((".md", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp")):
                    continue
                files.append(name)
            else:
                if "/" in name:
                    continue
                if Path(name).suffix.lower() not in ROOT_FILE_SUFFIXES:
                    continue
                files.append(name)
        return files or (list(FALLBACK_FILES) if not spec.recursive_download else [])

    def _head_size(self, spec: ModelSpec, name: str) -> int | None:
        request = urllib.request.Request(
            self._file_url(spec, name), headers=self._headers(), method="HEAD"
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                length = response.headers.get("Content-Length")
                return int(length) if length else None
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            if exc.code in {401, 403}:
                raise DownloadError("模型下载被拒绝，请检查 Hugging Face 授权") from exc
            raise DownloadError(f"探测文件失败（HTTP {exc.code}）") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise DownloadError(f"网络连接失败：{_human_error(exc)}") from exc

    def _download_file(
        self,
        task: DownloadTask,
        spec: ModelSpec,
        name: str,
        target: Path,
        expected_size: int,
    ) -> None:
        request = urllib.request.Request(self._file_url(spec, name), headers=self._headers())
        try:
            with urllib.request.urlopen(request, timeout=60) as response, target.open("wb") as handle:
                while True:
                    self._check_cancel(task)
                    chunk = response.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    handle.write(chunk)
                    with task.lock:
                        task.bytes_downloaded += len(chunk)
                        elapsed = max(time.monotonic() - task.started_monotonic, 0.001)
                        task.speed_bps = task.bytes_downloaded / elapsed
                        if task.total_bytes > 0:
                            remaining = max(task.total_bytes - task.bytes_downloaded, 0)
                            task.eta_seconds = int(remaining / task.speed_bps) if task.speed_bps else None
        except urllib.error.HTTPError as exc:
            if exc.code in {401, 403}:
                raise DownloadError("下载被拒绝：模型需要授权，请配置 HF_TOKEN") from exc
            raise DownloadError(f"下载 {name} 失败（HTTP {exc.code}）") from exc
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            raise DownloadError(f"下载 {name} 时网络中断：{_human_error(exc)}") from exc

        actual = target.stat().st_size
        if expected_size and actual != expected_size:
            raise DownloadError(f"{name} 下载不完整（{actual}/{expected_size} 字节）")
        if actual <= 0:
            raise DownloadError(f"{name} 为空文件")

    def _check_cancel(self, task: DownloadTask) -> None:
        if task.cancel_event.is_set():
            raise DownloadCancelled()

    def _headers(self, accept: str | None = None) -> dict[str, str]:
        headers = {"User-Agent": USER_AGENT}
        if accept:
            headers["Accept"] = accept
        if self.config.hf_token:
            headers["Authorization"] = f"Bearer {self.config.hf_token}"
        return headers

    def _file_url(self, spec: ModelSpec, name: str) -> str:
        quoted = urllib.parse.quote(name, safe="/")
        return f"{self.config.hf_endpoint}/{spec.repo}/resolve/main/{quoted}?download=true"


def _human_error(exc: BaseException) -> str:
    message = str(exc).strip()
    if not message:
        return exc.__class__.__name__
    if "timed out" in message.lower():
        return "连接超时，请检查网络或代理设置"
    return message


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
