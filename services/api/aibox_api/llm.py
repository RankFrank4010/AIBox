"""Local / external large language model chat engine.

Native local models run as GGUF files through the ``llama-server`` binary.
Any OpenAI-compatible endpoint (Ollama, LM Studio, vLLM, llama.cpp server or a
cloud API) is supported through ``AIBOX_LLM_BASE_URL``.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import socket
import subprocess
import threading
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx

from .catalog import get_llm_model, recommend_llm_model_id
from .config import AppConfig
from .models import is_model_installed, list_installed
from .runtime import RuntimeCapacityError, RuntimeManager

logger = logging.getLogger("aibox.llm")


class LLMUnavailable(RuntimeError):
    pass


class LLMEngine:
    def __init__(
        self,
        config: AppConfig,
        runtime: RuntimeManager | None = None,
        scheduler: Any | None = None,
    ) -> None:
        self.config = config
        self.runtime = runtime
        self.scheduler = scheduler
        self._lock = threading.RLock()
        self._server: subprocess.Popen[bytes] | None = None
        self._server_port: int | None = None
        self._server_model: str | None = None
        self._started_at: float = 0.0

    # ------------------------------------------------------------------ status
    def llama_binary(self) -> str | None:
        if self.config.llama_server:
            path = Path(self.config.llama_server).expanduser()
            return str(path) if path.is_file() else None
        return shutil.which("llama-server")

    def external_ready(self) -> bool:
        return bool(self.config.llm_base_url)

    def status(self) -> dict[str, Any]:
        installed = list_installed(self.config, "llm")
        installed_ids = {entry["id"] for entry in installed}
        recommended = recommend_llm_model_id(installed_ids=installed_ids)
        external_models: list[str] = []
        if self.external_ready():
            try:
                headers = self._headers()
                with httpx.Client(timeout=3) as client:
                    response = client.get(self.config.llm_base_url + "/models", headers=headers)
                if response.status_code == 200:
                    external_models = [
                        str(item.get("id"))
                        for item in (response.json().get("data") or [])
                        if isinstance(item, dict) and item.get("id")
                    ]
            except Exception:  # noqa: BLE001
                pass
        return {
            "demo": self.config.demo_llm,
            "provider_setting": self.config.settings().get("llm_provider", "auto"),
            "llama_server": self.llama_binary(),
            "external": {
                "configured": self.external_ready(),
                "base_url": self.config.llm_base_url,
                "models": external_models,
            },
            "installed_models": [entry["id"] for entry in installed],
            "models": [
                {
                    **entry,
                    "recommended": entry["id"] == recommended,
                }
                for entry in installed
            ],
            "recommended_model": recommended,
            "loaded_model": self._server_model,
            "server_port": self._server_port,
            "context": self.config.llm_context,
            "parallel": (
                self.scheduler.llm_runtime_config() if self.scheduler else None
            ),
        }

    # ----------------------------------------------------------------- models
    def resolve_model(self, requested: str | None) -> tuple[str, str]:
        """Return (model_id, provider). External providers accept arbitrary IDs."""
        raw = (requested or "").strip()
        provider = self._provider()
        installed = {
            entry["id"]: entry for entry in list_installed(self.config, "llm")
        }
        if provider == "openai":
            model = raw or self.config.llm_model
            if not model:
                raise LLMUnavailable("外部 LLM 未指定模型，请设置 AIBOX_LLM_MODEL。")
            return model, "openai"
        if provider == "demo":
            model = raw or (
                self.config.settings().get("default_llm_model")
                or "qwen3-8b"
            )
            return model, "demo"
        if not installed:
            raise LLMUnavailable("没有已安装的 GGUF 模型，请先在模型库下载。")
        default = self.config.settings().get("default_llm_model")
        if raw:
            spec = get_llm_model(raw)
            if spec is None:
                raise LLMUnavailable(f"未知本地 LLM 模型 {raw}")
            model_id = spec.id
        elif default in installed:
            model_id = str(default)
        else:
            model_id = recommend_llm_model_id(installed_ids=set(installed))
        if model_id not in installed:
            raise LLMUnavailable(f"LLM 模型 {model_id} 尚未安装。")
        return model_id, "llama-cpp"

    def _provider(self) -> str:
        setting = str(self.config.settings().get("llm_provider") or "auto")
        if self.config.demo_llm:
            return "demo"
        if setting == "demo":
            raise LLMUnavailable("LLM 演示引擎未启用（AIBOX_DEMO_LLM=1）。")
        if setting == "openai":
            if not self.external_ready():
                raise LLMUnavailable("AIBOX_LLM_BASE_URL 未配置。")
            return "openai"
        if setting == "llama-cpp":
            if not self.llama_binary():
                raise LLMUnavailable("找不到 llama-server，请设置 AIBOX_LLAMA_SERVER。")
            return "llama-cpp"
        if setting != "auto":
            raise LLMUnavailable(f"未知 LLM provider：{setting}")
        if self.external_ready():
            return "openai"
        if self.llama_binary():
            return "llama-cpp"
        if self.config.demo_llm:
            return "demo"
        raise LLMUnavailable(
            "没有可用的 LLM：请设置 AIBOX_LLM_BASE_URL（OpenAI 兼容服务）、"
            "安装 llama-server，或设置 AIBOX_DEMO_LLM=1。"
        )

    def model_list(self) -> list[dict[str, Any]]:
        models = []
        for entry in list_installed(self.config, "llm"):
            models.append(
                {
                    "id": entry["id"],
                    "object": "model",
                    "created": 0,
                    "owned_by": "aibox",
                    "permission": [],
                    "root": entry["id"],
                    "parent": None,
                    "name": entry["name"],
                }
            )
        if self.external_ready():
            try:
                with httpx.Client(timeout=3) as client:
                    response = client.get(
                        self.config.llm_base_url + "/models", headers=self._headers()
                    )
                if response.status_code == 200:
                    for item in response.json().get("data") or []:
                        model_id = item.get("id")
                        if model_id and not any(m["id"] == model_id for m in models):
                            models.append(
                                {
                                    "id": model_id,
                                    "object": "model",
                                    "created": 0,
                                    "owned_by": "external",
                                    "permission": [],
                                    "root": model_id,
                                    "parent": None,
                                    "name": model_id,
                                }
                            )
            except Exception:  # noqa: BLE001
                pass
        return models

    # ------------------------------------------------------------------ chat
    def chat(
        self,
        *,
        messages: list[dict[str, Any]],
        model_id: str | None = None,
        stream: bool = False,
        temperature: float | None = None,
        max_tokens: int | None = None,
        system_prompt: str | None = None,
    ) -> dict[str, Any] | Iterator[dict[str, Any]]:
        model, provider = self.resolve_model(model_id)
        if self.runtime:
            self.runtime.note_request("llm")
            if provider == "llama-cpp":
                try:
                    self.runtime.admit("llm")
                except RuntimeCapacityError as exc:
                    raise LLMUnavailable(str(exc)) from exc
        payload_messages = list(messages)
        if system_prompt and not any(
            item.get("role") == "system" for item in payload_messages
        ):
            payload_messages.insert(0, {"role": "system", "content": system_prompt})
        temperature = (
            float(temperature)
            if temperature is not None
            else float(self.config.settings().get("llm_temperature") or 0.7)
        )
        max_tokens = (
            int(max_tokens)
            if max_tokens is not None
            else int(self.config.settings().get("llm_max_tokens") or 1024)
        )
        if provider == "demo":
            return self._demo_chat(
                messages=payload_messages,
                model=model,
                stream=stream,
                max_tokens=max_tokens,
            )
        if provider == "llama-cpp":
            self._ensure_server(model)
            base_url = f"http://127.0.0.1:{self._server_port}/v1"
        else:
            base_url = self.config.llm_base_url
        body: dict[str, Any] = {
            "model": model,
            "messages": payload_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
        }
        if stream:
            if self.runtime and provider == "llama-cpp":
                self.runtime.begin("llm")
            return self._stream_external(
                base_url=base_url, body=body, provider=provider
            )
        if self.runtime and provider == "llama-cpp":
            self.runtime.begin("llm")
        try:
            with httpx.Client(timeout=600) as client:
                response = client.post(
                    base_url + "/chat/completions",
                    headers=self._headers(),
                    json=body,
                )
            if response.status_code >= 400:
                raise LLMUnavailable(
                    f"LLM 返回 HTTP {response.status_code}: {response.text[:500]}"
                )
            return response.json()
        finally:
            if self.runtime and provider == "llama-cpp":
                self.runtime.end("llm")

    def _stream_external(
        self, *, base_url: str, body: dict[str, Any], provider: str
    ) -> Iterator[dict[str, Any]]:
        client = httpx.Client(timeout=600)
        try:
            with client.stream(
                "POST",
                base_url + "/chat/completions",
                headers=self._headers(),
                json={**body, "stream": True},
            ) as response:
                if response.status_code >= 400:
                    text = response.read().decode("utf-8", errors="replace")
                    raise LLMUnavailable(
                        f"LLM 返回 HTTP {response.status_code}: {text[:500]}"
                    )
                for line in response.iter_lines():
                    line = line.strip()
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        return
                    try:
                        yield json.loads(data)
                    except json.JSONDecodeError:
                        continue
        finally:
            client.close()
            if self.runtime and provider == "llama-cpp":
                self.runtime.end("llm")

    # ---------------------------------------------------------------- llama.cpp
    def _ensure_server(self, model_id: str) -> None:
        with self._lock:
            if (
                self._server is not None
                and self._server.poll() is None
                and self._server_model == model_id
                and self._server_port
            ):
                return
            self._stop_server()
            spec = get_llm_model(model_id)
            if spec is None or not is_model_installed(self.config, model_id):
                raise LLMUnavailable(f"LLM 模型 {model_id} 未安装。")
            model_path = self.config.llm_models_dir / model_id / spec.required_files[0]
            if not model_path.is_file():
                raise LLMUnavailable(f"GGUF 文件不存在：{model_path}")
            binary = self.llama_binary()
            if not binary:
                raise LLMUnavailable("找不到 llama-server。")
            reservation = None
            if self.runtime:
                try:
                    reservation = self.runtime.ensure_capacity("llm", model_id)
                except RuntimeCapacityError as exc:
                    raise LLMUnavailable(str(exc)) from exc
            port = _free_port()
            context = max(512, min(131072, int(spec.context_length or self.config.llm_context)))
            parallel = self.scheduler.llm_runtime_config() if self.scheduler else {
                "strategy": "single",
                "cuda_indices": [],
                "split_mode": "none",
                "tensor_split": [],
                "parallel": 1,
            }
            command = [
                binary,
                "-m",
                str(model_path),
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "-c",
                str(min(context, self.config.llm_context)),
                "--n-gpu-layers",
                str(self.config.llm_gpu_layers),
                "--parallel",
                str(max(1, min(8, int(parallel.get("parallel") or 1)))),
            ]
            cuda_indices = [int(item) for item in parallel.get("cuda_indices") or []]
            split_mode = str(parallel.get("split_mode") or "none")
            if len(cuda_indices) > 1 and split_mode in {"row", "layer"}:
                command += ["--split-mode", split_mode]
                command += [
                    "--tensor-split",
                    ",".join(f"{float(item):g}" for item in parallel.get("tensor_split") or []),
                ]
            elif cuda_indices:
                command += ["--main-gpu", "0"]
            env = dict(os.environ)
            if cuda_indices:
                env["CUDA_VISIBLE_DEVICES"] = ",".join(str(item) for item in cuda_indices)
            log_path = self.config.logs_dir / "llama-server.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log = log_path.open("ab")
            try:
                server = subprocess.Popen(
                    command,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    cwd=str(model_path.parent),
                    env=env,
                )
            except OSError as exc:
                log.close()
                if self.runtime:
                    self.runtime.cancel(reservation)
                raise LLMUnavailable(f"无法启动 llama-server：{exc}") from exc
            log.close()
            self._server = server
            self._server_port = port
            self._server_model = model_id
            self._started_at = time.monotonic()
            try:
                self._wait_ready(server, port)
            except Exception:
                self._stop_server()
                if self.runtime:
                    self.runtime.cancel(reservation)
                raise
            if self.runtime:
                self.runtime.commit(reservation)
            logger.info("llama-server ready for %s on 127.0.0.1:%s", model_id, port)

    def _wait_ready(self, server: subprocess.Popen[bytes], port: int) -> None:
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            if server.poll() is not None:
                raise LLMUnavailable("llama-server 启动后退出，请查看 logs/llama-server.log。")
            try:
                with httpx.Client(timeout=2) as client:
                    response = client.get(f"http://127.0.0.1:{port}/health")
                if response.status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.5)
        raise LLMUnavailable("llama-server 启动超时。")

    def _stop_server(self) -> None:
        server = self._server
        self._server = None
        self._server_port = None
        self._server_model = None
        if server is not None:
            try:
                server.terminate()
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
        if self.runtime:
            self.runtime.note_unloaded("llm")

    def unload(self) -> None:
        with self._lock:
            self._stop_server()

    @property
    def loaded_model_id(self) -> str | None:
        return self._server_model

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.config.llm_api_key:
            headers["Authorization"] = f"Bearer {self.config.llm_api_key}"
        return headers

    # ------------------------------------------------------------------ demo
    def _demo_chat(
        self,
        *,
        messages: list[dict[str, Any]],
        model: str,
        stream: bool,
        max_tokens: int,
    ) -> dict[str, Any] | Iterator[dict[str, Any]]:
        user = next(
            (str(item.get("content") or "") for item in reversed(messages) if item.get("role") == "user"),
            "",
        )
        content = (
            "这是 AIBox 的演示语言模型。真实 GGUF / OpenAI 兼容模型配置后，"
            "这里会返回模型的真实回答。\n\n"
            f"你刚才说：{user[:500]}"
        )
        created = int(time.time())
        chunk_id = "chatcmpl-" + uuid.uuid4().hex[:12]
        if not stream:
            return {
                "id": chunk_id,
                "object": "chat.completion",
                "created": created,
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": content},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": max(1, len(user) // 4),
                    "completion_tokens": max(1, len(content) // 4),
                    "total_tokens": max(2, (len(user) + len(content)) // 4),
                },
            }

        def iterator() -> Iterator[dict[str, Any]]:
            pieces = [content[i : i + 12] for i in range(0, len(content), 12)]
            for index, piece in enumerate(pieces):
                yield {
                    "id": chunk_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "delta": (
                                {"role": "assistant", "content": piece}
                                if index == 0
                                else {"content": piece}
                            ),
                            "finish_reason": None,
                        }
                    ],
                }
            yield {
                "id": chunk_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            }

        return iterator()


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
