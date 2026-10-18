"""Best-effort hardware and runtime discovery across Windows, macOS and Linux."""

from __future__ import annotations

import ctypes
import importlib.metadata
import importlib.util
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from .catalog import recommend_model_id
from .cuda_runtime import cuda_runtime_hint, cuda_runtime_ready, register_for_process

_CACHE_LOCK = threading.Lock()
_CACHE: dict[str, Any] | None = None
_CACHE_AT = 0.0
_CACHE_TTL = 20.0


def _run(command: list[str], timeout: float = 6.0) -> str:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        return completed.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _powershell(script: str, timeout: float = 8.0) -> str:
    return _run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ],
        timeout=timeout,
    )


def _package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _cpu_name() -> str:
    system = platform.system()
    if system == "Windows":
        try:
            import winreg

            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
            )
            value, _ = winreg.QueryValueEx(key, "ProcessorNameString")
            winreg.CloseKey(key)
            if value:
                return str(value).strip()
        except OSError:
            pass
    if system == "Darwin":
        name = _run(["sysctl", "-n", "machdep.cpu.brand_string"])
        if name:
            return name
        name = _run(["sysctl", "-n", "hw.model"])
        if name:
            return f"Apple Silicon ({name})"
    try:
        info = Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="ignore")
        for line in info.splitlines():
            if line.lower().startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or platform.machine() or "Unknown CPU"


def _total_memory_gb() -> float | None:
    try:
        import psutil

        return round(psutil.virtual_memory().total / (1024**3), 1)
    except Exception:
        pass
    try:
        if platform.system() == "Windows":
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            memory = MEMORYSTATUSEX()
            memory.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)):
                return round(memory.ullTotalPhys / (1024**3), 1)
        else:
            page_size = os.sysconf("SC_PAGE_SIZE")
            pages = os.sysconf("SC_PHYS_PAGES")
            return round(page_size * pages / (1024**3), 1)
    except Exception:
        pass
    return None


def _detect_nvidia() -> list[dict[str, Any]]:
    raw = _run(
        [
            "nvidia-smi",
            "--query-gpu=name,memory.total,memory.used,driver_version,compute_cap",
            "--format=csv,noheader,nounits",
        ],
        timeout=8.0,
    )
    gpus: list[dict[str, Any]] = []
    if not raw:
        return gpus
    for line in raw.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 3:
            continue
        try:
            vram = round(float(parts[1]) / 1024, 1)
        except ValueError:
            vram = None
        try:
            used = round(float(parts[2]) / 1024, 1)
        except (ValueError, IndexError):
            used = None
        gpus.append(
            {
                "name": parts[0],
                "vendor": "NVIDIA",
                "vram_gb": vram,
                "vram_used_gb": used,
                "driver": parts[3] if len(parts) > 3 and parts[3] not in {"", "N/A"} else None,
                "compute_capability": (
                    parts[4] if len(parts) > 4 and parts[4] not in {"", "N/A"} else None
                ),
                "backend": "CUDA",
            }
        )
    return gpus


def _windows_display_adapters() -> list[dict[str, Any]]:
    script = (
        "Get-CimInstance Win32_VideoController | "
        "Select-Object Name,AdapterRAM,DriverVersion,VideoProcessor | ConvertTo-Json -Compress"
    )
    raw = _powershell(script)
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict):
        data = [data]
    results: list[dict[str, Any]] = []
    ignored = ("virtual", "basic display", "remote", "gameviewer", "sudomaker")
    for entry in data:
        name = str(entry.get("Name") or "").strip()
        if not name or any(token in name.lower() for token in ignored):
            continue
        adapter_ram = entry.get("AdapterRAM") or 0
        try:
            vram = round(int(adapter_ram) / (1024**3), 1) if int(adapter_ram) > 0 else None
        except (TypeError, ValueError):
            vram = None
        lower = name.lower()
        if "nvidia" in lower or "geforce" in lower or "quadro" in lower or "rtx" in lower:
            vendor = "NVIDIA"
            backend = "CUDA"
        elif "amd" in lower or "radeon" in lower:
            vendor = "AMD"
            backend = "DirectML / ROCm"
        elif "intel" in lower or "arc" in lower:
            vendor = "Intel"
            backend = "DirectML / oneAPI"
        elif "apple" in lower:
            vendor = "Apple"
            backend = "Metal"
        else:
            vendor = "Unknown"
            backend = "DirectML"
        results.append(
            {
                "name": name,
                "vendor": vendor,
                "vram_gb": vram,
                "vram_used_gb": None,
                "driver": entry.get("DriverVersion"),
                "compute_capability": None,
                "backend": backend,
            }
        )
    return results


def _detect_macos_gpu() -> list[dict[str, Any]]:
    raw = _run(["system_profiler", "SPDisplaysDataType", "-json"], timeout=12.0)
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    entries = data.get("SPDisplaysDataType") or []
    results: list[dict[str, Any]] = []
    for entry in entries:
        name = str(entry.get("sppci_model") or entry.get("_name") or "").strip()
        if not name:
            continue
        metal = entry.get("spdisplays_metal") or entry.get("spdisplays_metal_support")
        results.append(
            {
                "name": name,
                "vendor": "Apple" if "apple" in name.lower() else "Unknown",
                "vram_gb": None,
                "vram_used_gb": None,
                "driver": None,
                "compute_capability": None,
                "backend": "Metal",
                "metal": metal if isinstance(metal, str) else None,
            }
        )
    return results


def _detect_linux_gpu() -> list[dict[str, Any]]:
    raw = _run(["lspci"], timeout=5.0)
    results: list[dict[str, Any]] = []
    for line in raw.splitlines():
        if not re.search(r"VGA|3D controller|Display", line, re.IGNORECASE):
            continue
        name = line.split(": ", 1)[-1].strip()
        lower = name.lower()
        if "nvidia" in lower:
            vendor, backend = "NVIDIA", "CUDA"
        elif "amd" in lower or "ati" in lower:
            vendor, backend = "AMD", "ROCm"
        elif "intel" in lower:
            vendor, backend = "Intel", "oneAPI"
        else:
            vendor, backend = "Unknown", "Vulkan"
        results.append(
            {
                "name": name,
                "vendor": vendor,
                "vram_gb": None,
                "vram_used_gb": None,
                "driver": None,
                "compute_capability": None,
                "backend": backend,
            }
        )
    return results


def _detect_npus() -> list[dict[str, Any]]:
    system = platform.system()
    npus: list[dict[str, Any]] = []
    if system == "Windows":
        script = (
            "Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue | "
            "Where-Object { $_.FriendlyName -match '(\\bNPU\\b|Neural|AI Boost|Hexagon|VPU|Ryzen AI|AI Engine)' } | "
            "Select-Object FriendlyName,Status,Class | ConvertTo-Json -Compress"
        )
        raw = _powershell(script, timeout=10.0)
        if raw:
            try:
                data = json.loads(raw)
                if isinstance(data, dict):
                    data = [data]
                for entry in data:
                    name = str(entry.get("FriendlyName") or "").strip()
                    if not name:
                        continue
                    lower = name.lower()
                    if "intel" in lower:
                        vendor = "Intel"
                    elif "amd" in lower or "ryzen" in lower:
                        vendor = "AMD"
                    elif "qualcomm" in lower or "hexagon" in lower or "snapdragon" in lower:
                        vendor = "Qualcomm"
                    else:
                        vendor = "Unknown"
                    npus.append(
                        {
                            "name": name,
                            "vendor": vendor,
                            "status": str(entry.get("Status") or "Unknown"),
                            "runtime": "Windows ML / OpenVINO / QNN",
                        }
                    )
            except json.JSONDecodeError:
                pass
    elif system == "Darwin":
        if platform.machine().lower() in {"arm64", "aarch64"}:
            npus.append(
                {
                    "name": "Apple Neural Engine",
                    "vendor": "Apple",
                    "status": "OK",
                    "runtime": "Core ML / Metal Performance Shaders",
                }
            )
    else:
        accelerators = list(Path("/dev").glob("accel*"))
        if accelerators:
            npus.append(
                {
                    "name": "Linux accel device",
                    "vendor": "Unknown",
                    "status": "OK",
                    "runtime": "OpenVINO / Linux accel",
                    "path": str(accelerators[0]),
                }
            )
        lspci = _run(["lspci"], timeout=5.0)
        for line in lspci.splitlines():
            if re.search(r"neural|npu|vpu", line, re.IGNORECASE):
                npus.append(
                    {
                        "name": line.split(": ", 1)[-1].strip(),
                        "vendor": "Unknown",
                        "status": "OK",
                        "runtime": "OpenVINO / vendor runtime",
                    }
                )
    return npus


def _ctranslate2_cuda_count() -> int:
    if importlib.util.find_spec("ctranslate2") is None:
        return 0
    try:
        import ctranslate2

        return int(ctranslate2.get_cuda_device_count())
    except Exception:
        return 0


def _engine_info() -> dict[str, Any]:
    register_for_process()
    faster_whisper = _package_version("faster-whisper")
    ctranslate2 = _package_version("ctranslate2")
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    cuda_devices = _ctranslate2_cuda_count()
    cuda_ready = cuda_devices > 0 and cuda_runtime_ready()
    if cuda_ready:
        cuda_status = "ready"
    elif cuda_devices > 0:
        cuda_status = "runtime-missing"
    elif _nvidia_present():
        cuda_status = "detected"
    else:
        cuda_status = "unavailable"
    return {
        "asr": {
            "id": "faster-whisper",
            "name": "faster-whisper",
            "installed": faster_whisper is not None,
            "version": faster_whisper,
            "runtime": f"CTranslate2 {ctranslate2}" if ctranslate2 else None,
            "cuda_devices": cuda_devices,
            "cuda_ready": cuda_ready,
            "devices": ["cuda", "cpu"] if cuda_ready else ["cpu"],
            "compute_types": ["int8", "int8_float16", "float16", "float32"],
            "status": "ready" if faster_whisper else "not-installed",
        },
        "media": {
            "ffmpeg": ffmpeg,
            "ffprobe": ffprobe,
            "ready": bool(ffmpeg),
        },
        "accelerators": {
            "cuda": {
                "status": cuda_status,
                "device_count": cuda_devices,
                "runtime_ready": cuda_ready,
                "note": cuda_runtime_hint() if cuda_devices else None,
            },
            "metal": {"status": "partial", "note": "Apple Silicon 统一内存；Whisper 走 CPU 引擎"},
            "npu": {
                "status": "detected",
                "note": "NPU 已识别，ASR 加速适配在路线图中（OpenVINO / QNN）",
            },
        },
    }


def _nvidia_present() -> bool:
    return bool(_run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"], timeout=5.0))


def _os_label() -> tuple[str, str]:
    system = platform.system()
    if system == "Windows":
        release = platform.release()
        label = "Windows 11" if release == "10" and _windows_build() >= 22000 else f"Windows {release}"
        return "windows", label
    if system == "Darwin":
        return "macos", f"macOS {platform.mac_ver()[0] or platform.release()}"
    return "linux", platform.platform()


def _windows_build() -> int:
    try:
        return int(platform.version().split(".")[-1])
    except ValueError:
        return 0


def _build_accelerators(
    cpus: dict[str, Any],
    gpus: list[dict[str, Any]],
    npus: list[dict[str, Any]],
    memory_gb: float | None,
    engines: dict[str, Any],
) -> list[dict[str, Any]]:
    accelerators: list[dict[str, Any]] = [
        {
            "id": "cpu",
            "kind": "cpu",
            "name": cpus["name"],
            "vendor": cpus.get("vendor") or "CPU",
            "memory_gb": memory_gb,
            "backend": "CTranslate2 CPU",
            "status": "ready",
            "for_asr": True,
            "detail": f"{cpus['cores']} 线程 · int8 量化推理",
        }
    ]
    cuda_ready = bool(engines.get("accelerators", {}).get("cuda", {}).get("status") == "ready")
    for index, gpu in enumerate(gpus):
        is_nvidia = gpu.get("vendor") == "NVIDIA"
        backend = gpu.get("backend") or "GPU"
        for_asr = is_nvidia and cuda_ready
        if is_nvidia and not cuda_ready:
            detail = "已检测到显卡 · CUDA 运行时未就绪"
        elif gpu.get("vendor") == "Apple":
            detail = "统一内存 · ASR 暂用 CPU 引擎"
        else:
            detail = f"{backend} · ASR 加速适配中" if not for_asr else f"{backend} · 已就绪"
        accelerators.append(
            {
                "id": f"gpu-{index}",
                "kind": "gpu",
                "name": gpu["name"],
                "vendor": gpu.get("vendor") or "GPU",
                "memory_gb": gpu.get("vram_gb"),
                "backend": backend,
                "status": "ready" if for_asr else "detected",
                "for_asr": for_asr,
                "detail": detail,
            }
        )
    for index, npu in enumerate(npus):
        accelerators.append(
            {
                "id": f"npu-{index}",
                "kind": "npu",
                "name": npu["name"],
                "vendor": npu.get("vendor") or "NPU",
                "memory_gb": None,
                "backend": npu.get("runtime") or "NPU",
                "status": "detected",
                "for_asr": False,
                "detail": "驱动已识别 · ASR 加速适配中",
            }
        )
    return accelerators


def _vendor_from_cpu(name: str) -> str:
    lower = name.lower()
    if "intel" in lower:
        return "Intel"
    if "amd" in lower:
        return "AMD"
    if "apple" in lower:
        return "Apple"
    if "qualcomm" in lower or "snapdragon" in lower:
        return "Qualcomm"
    return "Unknown"


def collect_hardware(force: bool = False) -> dict[str, Any]:
    """Collect a UI-ready hardware snapshot. Results are cached briefly."""
    global _CACHE, _CACHE_AT
    with _CACHE_LOCK:
        if _CACHE is not None and not force and time.time() - _CACHE_AT < _CACHE_TTL:
            return _CACHE

        system = platform.system()
        cpu_name = re.sub(r"\s+", " ", _cpu_name()).strip()
        cores = os.cpu_count() or 1
        memory_gb = _total_memory_gb()
        nvidia = _detect_nvidia()
        if system == "Windows":
            other_gpus = _windows_display_adapters()
        elif system == "Darwin":
            other_gpus = _detect_macos_gpu()
        else:
            other_gpus = _detect_linux_gpu()

        gpus = list(nvidia)
        known_names = {gpu["name"].lower() for gpu in gpus}
        for gpu in other_gpus:
            if gpu["name"].lower() not in known_names:
                gpus.append(gpu)

        npus = _detect_npus()
        engines = _engine_info()
        platform_id, os_label = _os_label()
        cpus = {
            "name": cpu_name,
            "vendor": _vendor_from_cpu(cpu_name),
            "cores": cores,
            "physical_cores": _physical_cores(),
            "architecture": platform.machine(),
        }
        accelerators = _build_accelerators(cpus, gpus, npus, memory_gb, engines)

        cuda_gpu = next((gpu for gpu in gpus if gpu.get("vendor") == "NVIDIA"), None)
        gpu_memory = cuda_gpu.get("vram_gb") if cuda_gpu else None
        recommended = recommend_model_id(
            gpu_memory_gb=gpu_memory,
            system_memory_gb=memory_gb,
            has_cuda=engines["accelerators"]["cuda"]["status"] == "ready",
        )
        if cuda_gpu and engines["accelerators"]["cuda"]["status"] == "ready":
            reason = (
                f"检测到 {cuda_gpu['name']}（{gpu_memory:g} GB 显存），"
                "优先使用 GPU 推理。"
                if gpu_memory
                else f"检测到 {cuda_gpu['name']}，优先使用 GPU 推理。"
            )
        elif cuda_gpu:
            reason = (
                f"检测到 {cuda_gpu['name']}，但 CUDA 运行时未就绪，"
                f"按 {memory_gb:g} GB 内存推荐 CPU 推理。"
                if memory_gb
                else f"检测到 {cuda_gpu['name']}，但 CUDA 运行时未就绪，推荐轻量 CPU 模型。"
            )
        elif memory_gb:
            reason = f"未检测到可用 CUDA 设备，按 {memory_gb:g} GB 内存推荐 CPU 推理。"
        else:
            reason = "按通用设备推荐轻量模型。"

        payload = {
            "platform": {
                "id": platform_id,
                "label": os_label,
                "version": platform.version(),
                "release": platform.release(),
                "arch": platform.machine(),
                "hostname": socket.gethostname(),
                "python": platform.python_version(),
                "surfaces": {
                    "webui": True,
                    "desktop": platform_id in {"windows", "macos"},
                    "server": platform_id == "linux",
                    "android": "planned",
                    "ios": "planned",
                },
                "desktop_note": (
                    "本地 Fluent UI 桌面壳（Tauri + WebView）"
                    if platform_id in {"windows", "macos"}
                    else "Linux 仅提供 Fluent WebUI（浏览器 / PWA）"
                ),
            },
            "cpu": cpus,
            "memory_gb": memory_gb,
            "gpus": gpus,
            "npus": npus,
            "accelerators": accelerators,
            "engines": engines,
            "recommendation": {"model_id": recommended, "reason": reason},
            "gpu_memory_gb": gpu_memory,
            "has_cuda": engines["accelerators"]["cuda"]["status"] == "ready",
        }
        _CACHE = payload
        _CACHE_AT = time.time()
        return payload


def _physical_cores() -> int:
    try:
        import psutil

        return psutil.cpu_count(logical=False) or os.cpu_count() or 1
    except Exception:
        return os.cpu_count() or 1


def invalidate_hardware_cache() -> None:
    global _CACHE, _CACHE_AT
    with _CACHE_LOCK:
        _CACHE = None
        _CACHE_AT = 0.0
