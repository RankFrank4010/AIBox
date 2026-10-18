"""Community model adapter registry.

AIBox ships native adapters for faster-whisper and IndexTTS. Additional models
can be connected with a declarative manifest instead of patching AIBox itself:

* ``openai-http`` - any server exposing OpenAI-compatible ASR/TTS endpoints.
* ``command`` - any local CLI; AIBox passes audio/text paths and reads the result.

Command adapters execute local processes and are therefore disabled until the
operator explicitly sets ``AIBOX_ALLOW_ADAPTER_COMMANDS=1``. Remote HTTP
endpoints require ``AIBOX_ALLOW_REMOTE_ADAPTERS=1``; loopback/LAN endpoints are
allowed by default.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import re
import shlex
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .catalog import (
    ModelSpec,
    register_community_models,
)
from .config import AppConfig

logger = logging.getLogger("aibox.community")

ADAPTER_TYPES = {"openai-http", "command"}
ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")
KINDS = {"asr", "tts"}


class AdapterError(ValueError):
    pass


@dataclass
class CommunityAdapter:
    id: str
    name: str
    kind: str
    adapter: dict[str, Any]
    model: ModelSpec
    description: str = ""
    homepage: str = ""
    docs: str = ""
    install: str = ""
    builtin: bool = False
    enabled: bool = False
    template: bool = False
    status: str = "disabled"
    error: str | None = None
    source_path: str | None = None

    def to_dict(self, include_model: bool = True) -> dict[str, Any]:
        payload = {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "adapter_type": self.adapter.get("type"),
            "adapter": _redact_adapter(self.adapter),
            "description": self.description,
            "homepage": self.homepage,
            "docs": self.docs,
            "install": self.install,
            "builtin": self.builtin,
            "enabled": self.enabled,
            "template": self.template,
            "status": self.status,
            "error": self.error,
            "source_path": self.source_path,
        }
        if include_model:
            payload["model"] = self.model.to_dict()
        return payload


class CommunityRegistry:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.builtin_path = (
            Path(__file__).resolve().parent / "adapters_builtin" / "templates.json"
        )
        self.adapters: dict[str, CommunityAdapter] = {}
        self.templates: dict[str, dict[str, Any]] = {}
        self.errors: list[dict[str, str]] = []
        self.reload()

    # ------------------------------------------------------------------ loading
    def reload(self) -> None:
        self.adapters = {}
        self.templates = {}
        self.errors = []
        self._load_builtin_templates()
        self._load_user_adapters()
        self._apply_registration()

    def _load_builtin_templates(self) -> None:
        if not self.builtin_path.is_file():
            return
        try:
            payload = json.loads(self.builtin_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            self.errors.append({"file": str(self.builtin_path), "error": str(exc)})
            return
        entries = payload.get("templates") if isinstance(payload, dict) else None
        if not isinstance(entries, list):
            return
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            try:
                template = self._normalise_template(entry)
                self.templates[template["id"]] = template
            except AdapterError as exc:
                self.errors.append({"file": "builtin", "error": str(exc)})

    def _load_user_adapters(self) -> None:
        directory = self.config.adapters_dir
        if not directory.is_dir():
            return
        for path in sorted(directory.iterdir()):
            if path.suffix.lower() not in {".json", ".yaml", ".yml"}:
                continue
            try:
                data = _read_manifest(path)
                adapter = self._build_adapter(data, path, builtin=False)
                if adapter.id in self.adapters:
                    raise AdapterError(f"重复的适配器 ID：{adapter.id}")
                self.adapters[adapter.id] = adapter
            except Exception as exc:  # noqa: BLE001 - bad manifests must not stop the app
                self.errors.append({"file": str(path), "error": str(exc)})

    def _apply_registration(self) -> None:
        disabled = set(self.config.settings().get("community_disabled_adapters") or [])
        ready_models: list[ModelSpec] = []
        for adapter in self.adapters.values():
            adapter.enabled = adapter.id not in disabled
            try:
                ready, status, error = self._readiness(adapter)
            except Exception as exc:  # noqa: BLE001 - bad manifest must not stop the app
                ready, status, error = False, "invalid", str(exc)
            adapter.status = status if adapter.enabled else "disabled"
            adapter.error = error
            if adapter.enabled and ready:
                ready_models.append(adapter.model)
        try:
            register_community_models(ready_models)
        except ValueError as exc:
            self.errors.append({"file": "registry", "error": str(exc)})
            logger.warning("community model registration failed: %s", exc)
            register_community_models([])

    def _readiness(self, adapter: CommunityAdapter) -> tuple[bool, str, str | None]:
        config = adapter.adapter
        if config.get("type") == "command":
            if not self.config.allow_adapter_commands:
                return (
                    False,
                    "needs-command-gate",
                    "命令适配器默认禁用；设置 AIBOX_ALLOW_ADAPTER_COMMANDS=1 后重启。",
                )
            command = config.get("command")
            if not command:
                return False, "invalid", "command 不能为空。"
            try:
                parts = [str(part) for part in command] if isinstance(command, list) else shlex.split(str(command))
            except ValueError as exc:
                return False, "invalid", f"command 解析失败：{exc}"
            if not parts:
                return False, "invalid", "command 不能为空。"
            first = parts[0]
            first = str(first)
            if "/" in first or "\\" in first:
                if not Path(first).expanduser().is_file():
                    return False, "invalid", f"找不到命令：{first}"
            elif not shutil.which(first):
                return False, "invalid", f"PATH 中找不到命令：{first}"
            return True, "ready", None
        if config.get("type") == "openai-http":
            base_url = str(config.get("base_url") or "").strip()
            if not base_url:
                return False, "invalid", "base_url 不能为空。"
            parsed = urlparse(base_url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                return False, "invalid", "base_url 必须是 http(s) URL。"
            if not self.config.allow_remote_adapters and not _is_local_host(parsed.hostname):
                return (
                    False,
                    "needs-remote-gate",
                    "远程 HTTP 适配器需要 AIBOX_ALLOW_REMOTE_ADAPTERS=1；"
                    "默认只允许 localhost / 局域网地址。",
                )
            return True, "ready", None
        return False, "invalid", "adapter.type 必须是 openai-http 或 command。"

    # ------------------------------------------------------------------ parse
    def _normalise_template(self, entry: dict[str, Any]) -> dict[str, Any]:
        return self._normalise_common(entry, template=True)

    def _normalise_common(
        self, data: dict[str, Any], *, template: bool
    ) -> dict[str, Any]:
        if not isinstance(data, dict):
            raise AdapterError("manifest 必须是对象")
        schema = data.get("schema_version", 1)
        if schema not in (1, "1"):
            raise AdapterError(f"不支持的 schema_version：{schema}")
        adapter_id = str(data.get("id") or "").strip()
        if not ID_RE.match(adapter_id):
            raise AdapterError("id 必须是小写字母/数字开头，且仅含 a-z 0-9 . _ -（2-64 字符）")
        if adapter_id in {model.id for model in _builtin_models()}:
            raise AdapterError(f"ID 与内置模型冲突：{adapter_id}")
        kind = str(data.get("kind") or "").lower()
        if kind not in KINDS:
            raise AdapterError("kind 必须是 asr 或 tts")
        return {
            "id": adapter_id,
            "name": str(data.get("name") or adapter_id),
            "kind": kind,
            "description": str(data.get("description") or ""),
            "languages": str(data.get("languages") or "未声明"),
            "parameters": str(data.get("parameters") or "—"),
            "memory_gb": _float(data.get("memory_gb"), 0.0),
            "size_bytes": int(data.get("size_bytes") or 0),
            "size_label": str(data.get("size_label") or "外部引擎"),
            "license": str(data.get("license") or "见上游项目"),
            "source": str(data.get("source") or "社区适配器"),
            "homepage": str(data.get("homepage") or ""),
            "tags": [str(tag) for tag in data.get("tags") or []],
            "aliases": [str(alias) for alias in data.get("aliases") or []],
            "install": str(data.get("install") or ""),
            "docs": str(data.get("docs") or ""),
            "template": template,
            "adapter_example": data.get("adapter_example") or data.get("adapter"),
        }

    def _build_adapter(
        self, data: dict[str, Any], path: Path, *, builtin: bool
    ) -> CommunityAdapter:
        normal = self._normalise_common(data, template=False)
        adapter_config = data.get("adapter")
        if not isinstance(adapter_config, dict):
            raise AdapterError("adapter 必须是对象")
        adapter_type = str(adapter_config.get("type") or "").lower()
        if adapter_type not in ADAPTER_TYPES:
            raise AdapterError(
                "adapter.type 必须是 openai-http 或 command；"
                "template 模板请通过“使用模板”导入。"
            )
        adapter_config = dict(adapter_config)
        adapter_config["type"] = adapter_type
        if adapter_type == "openai-http":
            base_url = str(adapter_config.get("base_url") or "").strip()
            parsed = urlparse(base_url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise AdapterError("openai-http.base_url 必须是 http(s) URL")
            adapter_config["base_url"] = base_url.rstrip("/")
            adapter_config["timeout_seconds"] = min(
                3600, max(5, int(adapter_config.get("timeout_seconds") or 300))
            )
        else:
            command = adapter_config.get("command")
            if not isinstance(command, (str, list)) or not command:
                raise AdapterError("command.command 必须是非空字符串或数组")
            adapter_config["timeout_seconds"] = min(
                3600, max(5, int(adapter_config.get("timeout_seconds") or 600))
            )
        spec = ModelSpec(
            id=normal["id"],
            name=normal["name"],
            repo=str(data.get("repo") or ""),
            parameters=normal["parameters"],
            size_bytes=normal["size_bytes"],
            size_label=normal["size_label"],
            speed=_float(data.get("speed"), 3.0),
            accuracy=_float(data.get("accuracy"), 3.0),
            languages=normal["languages"],
            memory_gb=normal["memory_gb"],
            description=normal["description"],
            best_for=str(data.get("best_for") or "社区适配模型"),
            tags=tuple(normal["tags"]),
            license=normal["license"],
            source=normal["source"],
            kind=normal["kind"],
            engine=adapter_type,
            format="External",
            external=True,
            community=True,
            adapter_id=normal["id"],
            aliases=tuple(normal["aliases"]),
            homepage=normal["homepage"],
            install_docs=normal["install"],
        )
        return CommunityAdapter(
            id=normal["id"],
            name=normal["name"],
            kind=normal["kind"],
            adapter=adapter_config,
            model=spec,
            description=normal["description"],
            homepage=normal["homepage"],
            docs=normal["docs"],
            install=normal["install"],
            builtin=builtin,
            source_path=str(path),
        )

    # -------------------------------------------------------------------- API
    def adapter_for(self, model_id: str) -> CommunityAdapter | None:
        adapter = self.adapters.get(model_id)
        if adapter and adapter.enabled and adapter.status == "ready":
            return adapter
        return None

    def list_public(self) -> dict[str, Any]:
        adapters = [adapter.to_dict() for adapter in self.adapters.values()]
        templates = [self.template_public(item) for item in self.templates.values()]
        return {
            "templates": templates,
            "adapters": sorted(adapters, key=lambda item: item["id"]),
            "summary": {
                "templates": len(templates),
                "adapters": len(adapters),
                "enabled": sum(1 for item in adapters if item["enabled"]),
                "ready": sum(1 for item in adapters if item["status"] == "ready"),
            },
            "security": {
                "allow_commands": self.config.allow_adapter_commands,
                "allow_remote": self.config.allow_remote_adapters,
                "adapters_dir": str(self.config.adapters_dir),
            },
            "errors": self.errors,
        }

    def template_public(self, template: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": template["id"],
            "name": template["name"],
            "kind": template["kind"],
            "description": template["description"],
            "languages": template["languages"],
            "parameters": template["parameters"],
            "memory_gb": template["memory_gb"],
            "license": template["license"],
            "source": template["source"],
            "homepage": template["homepage"],
            "tags": template["tags"],
            "install": template["install"],
            "docs": template["docs"],
            "adapter_example": _redact_adapter(template.get("adapter_example") or {}),
            "template": True,
        }

    def template_manifest(self, template_id: str) -> dict[str, Any]:
        template = self.templates.get(template_id)
        if template is None:
            raise AdapterError("模板不存在")
        example = template.get("adapter_example")
        if not isinstance(example, dict):
            example = {}
        return {
            "schema_version": 1,
            "id": template["id"],
            "name": template["name"],
            "kind": template["kind"],
            "description": template["description"],
            "languages": template["languages"],
            "parameters": template["parameters"],
            "memory_gb": template["memory_gb"],
            "license": template["license"],
            "source": template["source"],
            "homepage": template["homepage"],
            "tags": template["tags"],
            "aliases": template.get("aliases") or [],
            "install": template["install"],
            "docs": template["docs"],
            "adapter": example,
        }

    def import_manifest(self, manifest: str | dict[str, Any]) -> CommunityAdapter:
        data = _parse_manifest(manifest)
        adapter = self._build_adapter(data, self.config.adapters_dir / "import.json", builtin=False)
        if adapter.id in self.adapters:
            raise AdapterError(f"适配器 {adapter.id} 已存在；请先删除或改名。")
        target = self.config.adapters_dir / f"{adapter.id}.json"
        if target.exists():
            raise AdapterError(f"文件已存在：{target.name}")
        target.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        # Imported adapters start disabled. This is deliberate: command adapters
        # execute local processes and HTTP adapters may reach other services.
        settings = self.config.settings()
        disabled = set(settings.get("community_disabled_adapters") or [])
        disabled.add(adapter.id)
        self.config.update_settings({"community_disabled_adapters": sorted(disabled)})
        self.reload()
        return self.adapters[adapter.id]

    def set_enabled(self, adapter_id: str, enabled: bool) -> CommunityAdapter:
        adapter = self.adapters.get(adapter_id)
        if adapter is None:
            raise AdapterError("适配器不存在")
        settings = self.config.settings()
        disabled = set(settings.get("community_disabled_adapters") or [])
        if enabled:
            disabled.discard(adapter_id)
        else:
            disabled.add(adapter_id)
        self.config.update_settings({"community_disabled_adapters": sorted(disabled)})
        self.reload()
        return self.adapters[adapter_id]

    def delete(self, adapter_id: str) -> bool:
        adapter = self.adapters.get(adapter_id)
        if adapter is None:
            return False
        path = Path(adapter.source_path or "")
        if not path.is_file() or path.parent.resolve() != self.config.adapters_dir.resolve():
            raise AdapterError("只能删除导入到数据目录的适配器")
        path.unlink()
        settings = self.config.settings()
        disabled = set(settings.get("community_disabled_adapters") or [])
        disabled.discard(adapter_id)
        self.config.update_settings({"community_disabled_adapters": sorted(disabled)})
        self.reload()
        return True


def _builtin_models() -> tuple[ModelSpec, ...]:
    from .catalog import IMAGE_MODELS, TTS_MODELS, WHISPER_MODELS

    return WHISPER_MODELS + TTS_MODELS + IMAGE_MODELS


def _read_manifest(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        data = json.loads(text)
    else:
        try:
            import yaml
        except ImportError as exc:
            raise AdapterError("读取 YAML 需要安装 pyyaml") from exc
        data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise AdapterError("manifest 必须是对象")
    return data


def _parse_manifest(manifest: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(manifest, dict):
        return manifest
    text = manifest.strip()
    if not text:
        raise AdapterError("manifest 为空")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        try:
            import yaml
        except ImportError as exc:
            raise AdapterError("JSON 无效，且未安装 pyyaml 无法解析 YAML") from exc
        try:
            data = yaml.safe_load(text)
        except Exception as exc:  # noqa: BLE001
            raise AdapterError(f"无法解析 manifest：{exc}") from exc
    if not isinstance(data, dict):
        raise AdapterError("manifest 必须是对象")
    return data


def _float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _is_local_host(hostname: str) -> bool:
    host = hostname.strip().lower().strip("[]")
    if host in {"localhost", "host.docker.internal"}:
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        # A DNS name is treated as remote unless explicitly allowed.
        return False
    if address.is_link_local:
        return False
    return address.is_loopback or address.is_private


def _redact_adapter(adapter: dict[str, Any]) -> dict[str, Any]:
    data = dict(adapter)
    for key in ("api_key", "token", "password"):
        if key in data:
            data[key] = "***"
    return data
