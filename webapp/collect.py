# SPDX-License-Identifier: GPL-3.0-or-later
"""Recolector de metricas del sistema (CPU, RAM, red, disco, sensores)."""

from __future__ import annotations

import collections
import os
import platform
import socket
import threading
import time
from datetime import datetime

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None

HISTORY_LEN = 120


def human_bytes(value: float) -> str:
    value = float(value or 0)
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if abs(value) < 1024 or unit == "PB":
            if unit == "B":
                return f"{int(value)} B"
            return f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{value:.1f} PB"


def human_rate(value: float) -> str:
    return human_bytes(value) + "/s"


def human_uptime(seconds: float) -> str:
    seconds = int(seconds or 0)
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def _os_pretty_name() -> str:
    try:
        with open("/etc/os-release", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("PRETTY_NAME="):
                    return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return f"{platform.system()} {platform.release()}"


class Collector(threading.Thread):
    """Muestrea el sistema cada segundo y guarda historial para las graficas."""

    def __init__(self, interval: float = 1.0):
        super().__init__(daemon=True, name="collector")
        self.interval = interval
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._snapshot = {}
        self._history = {k: collections.deque(maxlen=HISTORY_LEN)
                         for k in ("cpu", "ram", "net_down", "net_up", "temp", "load")}
        self._last_net = None
        self._last_net_ts = None
        self.hostname = socket.gethostname()
        self.os_name = _os_pretty_name()
        self.kernel = platform.release()
        self.cpu_count = os.cpu_count() or 1
        if psutil is not None:
            try:
                psutil.cpu_percent(interval=None)
            except Exception:
                pass
            try:
                self.cpu_count = psutil.cpu_count(logical=True) or self.cpu_count
            except Exception:
                pass
        self._boot = psutil.boot_time() if psutil is not None else time.time()

    # -- sensores -----------------------------------------------------------
    def _cpu_temp(self):
        if psutil is None or not hasattr(psutil, "sensors_temperatures"):
            return None
        try:
            sensors = psutil.sensors_temperatures() or {}
        except Exception:
            return None
        candidates = ("coretemp", "k10temp", "cpu_thermal", "zenpower", "acpitz")
        for name in candidates:
            for entry in sensors.get(name, []):
                if entry.current and 0 < entry.current < 125:
                    return float(entry.current)
        for entries in sensors.values():
            for entry in entries:
                if entry.current and 0 < entry.current < 125:
                    return float(entry.current)
        return None

    def _net_rates(self):
        if psutil is None:
            return 0.0, 0.0
        try:
            counters = psutil.net_io_counters()
        except Exception:
            return 0.0, 0.0
        now = time.monotonic()
        if self._last_net is None:
            self._last_net = counters
            self._last_net_ts = now
            return 0.0, 0.0
        elapsed = max(now - self._last_net_ts, 0.001)
        down = max(counters.bytes_recv - self._last_net.bytes_recv, 0) / elapsed
        up = max(counters.bytes_sent - self._last_net.bytes_sent, 0) / elapsed
        self._last_net = counters
        self._last_net_ts = now
        return down, up

    def _disk_usage(self):
        if psutil is None:
            return 0.0, 0, 0
        try:
            root = os.path.abspath(os.sep)
            usage = psutil.disk_usage(root)
            return usage.percent, usage.used, usage.total
        except Exception:
            return 0.0, 0, 0

    def _services_summary(self):
        try:
            from services import summary
            return summary()
        except Exception:
            return {"running": 0, "failed": 0, "total": 0, "docker_running": 0, "docker_total": 0}

    # -- muestreo -----------------------------------------------------------
    def sample(self) -> dict:
        now = datetime.now()
        cpu_percent = ram_percent = swap_percent = 0.0
        ram_used = ram_total = 0
        processes = 0
        freq = None
        load = (0.0, 0.0, 0.0)
        if psutil is not None:
            try:
                cpu_percent = float(psutil.cpu_percent(interval=None))
            except Exception:
                pass
            try:
                vm = psutil.virtual_memory()
                ram_percent, ram_used, ram_total = float(vm.percent), vm.used, vm.total
            except Exception:
                pass
            try:
                swap_percent = float(psutil.swap_memory().percent)
            except Exception:
                pass
            try:
                processes = len(psutil.pids())
            except Exception:
                pass
            try:
                freq_obj = psutil.cpu_freq()
                freq = float(freq_obj.current) if freq_obj else None
            except Exception:
                pass
            try:
                load = tuple(os.getloadavg()) if hasattr(os, "getloadavg") else (0.0, 0.0, 0.0)
            except Exception:
                pass

        disk_percent, disk_used, disk_total = self._disk_usage()
        net_down, net_up = self._net_rates()
        temp = self._cpu_temp()
        services = self._services_summary()

        snapshot = {
            "ts": time.time(),
            "time": now.strftime("%H:%M"),
            "time_long": now.strftime("%H:%M:%S"),
            "date": now.strftime("%d/%m/%Y"),
            "weekday": ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"][now.weekday()],
            "hostname": self.hostname,
            "os": self.os_name,
            "kernel": self.kernel,
            "uptime": max(time.time() - self._boot, 0),
            "uptime_str": human_uptime(time.time() - self._boot),
            "cpu": {
                "percent": cpu_percent,
                "count": self.cpu_count,
                "freq": freq,
                "temp": temp,
                "load": load[0],
            },
            "ram": {
                "percent": ram_percent,
                "used": ram_used,
                "total": ram_total,
                "used_str": human_bytes(ram_used),
                "total_str": human_bytes(ram_total),
                "swap_percent": swap_percent,
            },
            "disk": {
                "percent": disk_percent,
                "used": disk_used,
                "total": disk_total,
                "used_str": human_bytes(disk_used),
                "total_str": human_bytes(disk_total),
            },
            "net": {
                "down": net_down,
                "up": net_up,
                "down_str": human_rate(net_down),
                "up_str": human_rate(net_up),
            },
            "processes": processes,
            "services": services,
        }

        with self._lock:
            self._history["cpu"].append(cpu_percent)
            self._history["ram"].append(ram_percent)
            self._history["net_down"].append(net_down)
            self._history["net_up"].append(net_up)
            self._history["temp"].append(temp or 0.0)
            self._history["load"].append(load[0])
            snapshot["history"] = {k: list(v) for k, v in self._history.items()}
            self._snapshot = snapshot
        return snapshot

    def run(self):
        while not self._stop.is_set():
            try:
                self.sample()
            except Exception:
                pass
            self._stop.wait(self.interval)

    def stop(self):
        self._stop.set()

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self._snapshot)
