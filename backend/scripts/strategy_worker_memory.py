"""Benchmark-only process peak working set; not a simultaneous tree RSS sum."""
import json
import os
from pathlib import Path


def peak_working_set():
    if os.name != "nt":
        import resource
        import sys
        value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return value if sys.platform == "darwin" else value * 1024
    import ctypes
    from ctypes import wintypes
    class Counters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD),
                    *[(name, ctypes.c_size_t) for name in (
                        "peak", "working", "peak_paged", "paged", "peak_nonpaged",
                        "nonpaged", "pagefile", "peak_pagefile")]]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
        raise ctypes.WinError(ctypes.get_last_error())
    return counters.peak


def memory_worker(*args):
    from app.backtest.colocated import _worker
    try:
        _worker(*args)
    finally:
        path = Path(os.environ["STRATEGY_AUDIT_MEMORY"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "worker_peak_working_set_bytes": peak_working_set(),
            "scope": "worker process lifetime; not combined with parent peak",
        }), encoding="utf-8")
