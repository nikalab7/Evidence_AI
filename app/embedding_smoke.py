"""Private startup check for the production query embedding model."""

from __future__ import annotations

import os
import platform
import sys
import time
from collections.abc import Callable
from typing import Any


MODEL_NAME = "BAAI/bge-small-en-v1.5"
EXPECTED_DIMENSIONS = 384
SMOKE_QUERY = "What is the purpose of an evidence-based investigation?"


def _linux_status_memory_bytes(label: str) -> int | None:
    try:
        with open("/proc/self/status", encoding="ascii") as status:
            for line in status:
                if line.startswith(f"{label}:"):
                    return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        return None
    return None


def _windows_working_set_bytes(*, peak: bool) -> int | None:
    try:
        import ctypes
        from ctypes import wintypes

        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
                ("PrivateUsage", ctypes.c_size_t),
            ]

        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel32.GetCurrentProcess.argtypes = []
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE, ctypes.POINTER(ProcessMemoryCounters), wintypes.DWORD,
        ]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        process = kernel32.GetCurrentProcess()
        ok = psapi.GetProcessMemoryInfo(process, ctypes.byref(counters), counters.cb)
        if not ok:
            return None
        return int(counters.PeakWorkingSetSize if peak else counters.WorkingSetSize)
    except (AttributeError, OSError, TypeError, ctypes.ArgumentError):
        return None


def process_rss_bytes() -> int | None:
    """Return current resident memory in bytes where the OS exposes it."""
    if sys.platform.startswith("linux"):
        return _linux_status_memory_bytes("VmRSS")
    if sys.platform == "win32":
        return _windows_working_set_bytes(peak=False)
    try:
        import resource

        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return int(peak if sys.platform == "darwin" else peak * 1024)
    except (ImportError, AttributeError, OSError, ValueError):
        return None


def process_peak_rss_bytes() -> int | None:
    """Return the process high-water resident memory in bytes where available."""
    if sys.platform.startswith("linux"):
        return _linux_status_memory_bytes("VmHWM")
    if sys.platform == "win32":
        return _windows_working_set_bytes(peak=True)
    try:
        import resource

        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return int(peak if sys.platform == "darwin" else peak * 1024)
    except (ImportError, AttributeError, OSError, ValueError):
        return None


def run_embedding_smoke_test(
    *,
    model_factory: Callable[..., Any] | None = None,
    rss_reader: Callable[[], int | None] = process_rss_bytes,
    peak_rss_reader: Callable[[], int | None] = process_peak_rss_bytes,
    clock: Callable[[], float] = time.perf_counter,
) -> tuple[Any, dict[str, Any]]:
    """Load one model and embed one query, returning the model and safe metrics."""
    model_name = os.getenv("FASTEMBED_MODEL", MODEL_NAME)
    threads = int(os.getenv("FASTEMBED_THREADS", "1"))
    if threads < 1:
        raise ValueError("FASTEMBED_THREADS must be at least 1")

    if model_factory is None:
        from fastembed import TextEmbedding

        model_factory = TextEmbedding

    started = clock()
    rss_before = rss_reader()
    model = model_factory(model_name=model_name, threads=threads)
    model_ready = clock()
    rss_after_model = rss_reader()
    vectors = list(model.query_embed([SMOKE_QUERY]))
    embedded = clock()

    if len(vectors) != 1:
        raise ValueError(f"Expected one query vector, got {len(vectors)}")
    dimensions = len(vectors[0])
    if dimensions != EXPECTED_DIMENSIONS:
        raise ValueError(f"Expected {EXPECTED_DIMENSIONS} dimensions, got {dimensions}")

    rss_after_embedding = rss_reader()
    peak_rss = peak_rss_reader()
    report = {
        "status": "passed",
        "model": model_name,
        "dimensions": dimensions,
        "threads": threads,
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "render_cpu_count": os.getenv("RENDER_CPU_COUNT"),
        "model_initialization_seconds": round(model_ready - started, 4),
        "first_query_embedding_seconds": round(embedded - model_ready, 4),
        "smoke_startup_seconds": round(embedded - started, 4),
        "rss_before_bytes": rss_before,
        "rss_after_model_bytes": rss_after_model,
        "rss_after_embedding_bytes": rss_after_embedding,
        "rss_delta_bytes": (rss_after_embedding - rss_before
                            if rss_before is not None and rss_after_embedding is not None else None),
        "peak_rss_bytes": peak_rss,
    }
    return model, report
