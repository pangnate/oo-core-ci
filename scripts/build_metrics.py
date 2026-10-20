"""Lightweight runner resource samples; no extra packages or child processes."""
from __future__ import annotations

import ctypes
import os
from pathlib import Path
import shutil
import threading
import time


def build_jobs() -> int:
    cores = os.cpu_count() or 1
    return max(1, min(int(os.environ.get("X2T_BUILD_JOBS", cores)), cores))


def system_counters() -> tuple[int, int, int]:
    """Return aggregate CPU ticks, idle ticks and available physical bytes."""
    if os.name == "nt":
        from ctypes import wintypes

        class MemoryStatus(ctypes.Structure):
            _fields_ = [("length", wintypes.DWORD), ("load", wintypes.DWORD),
                        *[(name, ctypes.c_ulonglong) for name in (
                            "physical", "available", "pagefile", "available_pagefile",
                            "virtual", "available_virtual", "extended")]]

        idle, kernel, user = wintypes.FILETIME(), wintypes.FILETIME(), wintypes.FILETIME()
        if not ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
            raise ctypes.WinError()
        memory = MemoryStatus()
        memory.length = ctypes.sizeof(memory)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)):
            raise ctypes.WinError()
        def ticks(value):
            return (value.dwHighDateTime << 32) | value.dwLowDateTime
        return ticks(kernel) + ticks(user), ticks(idle), memory.available
    values = [int(value) for value in Path("/proc/stat").read_text().splitlines()[0].split()[1:9]]
    memory = dict(line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines())
    return sum(values), values[3] + values[4], int(memory["MemAvailable"].split()[0]) * 1024


class ResourceMonitor:
    def __init__(self, workspace: Path, interval: float = 15):
        self.workspace = workspace
        self.interval = interval
        self.samples: list[dict] = []
        self.stop_event = threading.Event()
        self.previous = None
        self.started = time.monotonic()
        self.thread = threading.Thread(target=self._loop, daemon=True)

    def sample(self) -> None:
        sample = {"seconds": round(time.monotonic() - self.started, 2)}
        try:
            total, idle, available = system_counters()
            if self.previous:
                elapsed = total - self.previous[0]
                if elapsed > 0:
                    sample["cpuBusyPercent"] = round(100 * (1 - (idle - self.previous[1]) / elapsed), 1)
            self.previous = total, idle
            sample.update(availableMemoryMiB=round(available / 2**20),
                          freeDiskGiB=round(shutil.disk_usage(self.workspace).free / 2**30, 2))
        except (OSError, ValueError, KeyError) as error:
            sample["error"] = str(error)
        self.samples.append(sample)

    def _loop(self) -> None:
        while not self.stop_event.wait(self.interval):
            self.sample()

    def start(self) -> None:
        self.sample()
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.thread.join()
        self.sample()
