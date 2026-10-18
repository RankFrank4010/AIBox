"""CUDA runtime discovery and optional NVIDIA pip library loading.

CTranslate2 can enumerate CUDA devices through the driver even when cuBLAS /
cuDNN are absent. This module separates those two facts so AIBox never claims
that GPU inference is ready when it is not.
"""

from __future__ import annotations

import ctypes
import os
import platform
import sys
from functools import lru_cache
from pathlib import Path

_REGISTERED = False


def _nvidia_lib_dirs() -> list[Path]:
    if platform.system() == "Windows":
        root = Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
        subdirs = ("cublas", "cudnn", "cuda_runtime", "cuda_nvrtc")
        return [root / name / "bin" for name in subdirs if (root / name / "bin").is_dir()]
    root = Path(sys.prefix) / "lib"
    candidates: list[Path] = []
    for python_dir in root.glob("python*"):
        nvidia = python_dir / "site-packages" / "nvidia"
        if nvidia.is_dir():
            for name in ("cublas", "cudnn", "cuda_runtime", "cuda_nvrtc"):
                directory = nvidia / name / "lib"
                if directory.is_dir():
                    candidates.append(directory)
    return candidates


def register_nvidia_libs() -> None:
    """Make pip-installed NVIDIA libraries visible to the process loader."""
    global _REGISTERED
    if _REGISTERED:
        return
    _REGISTERED = True
    directories = _nvidia_lib_dirs()
    if not directories:
        return
    if platform.system() == "Windows":
        for directory in directories:
            try:
                os.add_dll_directory(str(directory))
            except (AttributeError, OSError):
                pass
            current = os.environ.get("PATH", "")
            if str(directory) not in current.split(os.pathsep):
                os.environ["PATH"] = f"{directory}{os.pathsep}{current}"
    else:
        for directory in directories:
            current = os.environ.get("LD_LIBRARY_PATH", "")
            if str(directory) not in current.split(os.pathsep):
                os.environ["LD_LIBRARY_PATH"] = (
                    f"{directory}{os.pathsep}{current}" if current else str(directory)
                )
        # Preload pip-packaged shared libraries so CTranslate2 can resolve symbols.
        for directory in directories:
            for library in sorted(directory.glob("*.so*")):
                try:
                    ctypes.CDLL(str(library), mode=ctypes.RTLD_GLOBAL)
                except OSError:
                    continue


def _try_load(names: tuple[str, ...], glob_patterns: tuple[str, ...] = ()) -> bool:
    if platform.system() == "Windows":
        for name in names:
            try:
                ctypes.WinDLL(name)
                return True
            except OSError:
                continue
        for directory in _nvidia_lib_dirs():
            for pattern in glob_patterns:
                for candidate in directory.glob(pattern):
                    try:
                        ctypes.WinDLL(str(candidate))
                        return True
                    except OSError:
                        continue
        return False
    for name in names:
        try:
            ctypes.CDLL(name, mode=ctypes.RTLD_GLOBAL)
            return True
        except OSError:
            continue
    for directory in _nvidia_lib_dirs():
        for pattern in glob_patterns:
            for candidate in directory.glob(pattern):
                try:
                    ctypes.CDLL(str(candidate), mode=ctypes.RTLD_GLOBAL)
                    return True
                except OSError:
                    continue
    return False


@lru_cache(maxsize=1)
def cuda_runtime_ready() -> bool:
    """Return True only when cuBLAS *and* cuDNN are loadable."""
    if platform.system() not in {"Windows", "Linux"}:
        return False
    if platform.system() == "Windows":
        cublas = _try_load(
            ("cublas64_12.dll", "cublas64_11.dll"),
            ("cublas64_12.dll", "cublas64_11.dll"),
        )
        cudnn = _try_load(
            ("cudnn_ops64_9.dll", "cudnn64_8.dll"),
            ("cudnn_ops64_9.dll", "cudnn64_8.dll"),
        )
        return cublas and cudnn
    cublas = _try_load(
        ("libcublas.so.12", "libcublas.so.11"),
        ("libcublas.so.12*", "libcublas.so.11*"),
    )
    cudnn = _try_load(
        ("libcudnn_ops.so.9", "libcudnn.so.8"),
        ("libcudnn_ops.so.9*", "libcudnn.so.8*"),
    )
    return cublas and cudnn


def cuda_runtime_hint() -> str:
    if cuda_runtime_ready():
        return "CUDA 运行时已就绪（cuBLAS + cuDNN）"
    return (
        "检测到 CUDA 设备，但缺少 cuBLAS / cuDNN 运行时。"
        "可安装 nvidia-cublas-cu12 与 nvidia-cudnn-cu12，或使用系统 CUDA 运行时。"
    )


def register_for_process() -> None:
    register_nvidia_libs()
