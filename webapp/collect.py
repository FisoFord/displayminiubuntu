# SPDX-License-Identifier: GPL-3.0-or-later
"""Recolector de metricas del sistema (CPU, RAM, red, disco, sensores)."""

from __future__ import annotations

import collections
import glob
import os
import platform
import shutil
import socket
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None

HISTORY_LEN = 120


def _float_or_none(value):
    try:
        number = float(str(value).strip())
        return number if number == number else None
    except (TypeError, ValueError):
        return None


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


def _read_int(path) -> int | None:
    try:
        return int(Path(path).read_text().strip())
    except (OSError, ValueError):
        return None


class GpuReader:
    """Lee uso, VRAM y temperatura de la GPU con las fuentes disponibles."""

    def __init__(self):
        self._ts = 0.0
        self._cache = None
        self._win_checked = False
        self._win_payload = None

    @staticmethod
    def _payload(name, percent=None, used=None, total=None, temp=None, source=None):
        memory_percent = (used / total * 100) if used and total else None
        return {
            "available": bool(name),
            "name": name,
            "percent": percent,
            "memory_percent": memory_percent,
            "memory_used": used,
            "memory_total": total,
            "memory_used_str": human_bytes(used) if used else None,
            "memory_total_str": human_bytes(total) if total else None,
            "temp": temp,
            "source": source,
        }

    def read(self):
        now = time.monotonic()
        if self._cache is not None and now - self._ts < 2.0:
            return self._cache
        data = (self._nvidia() or self._amd_sysfs()
                or self._intel_sysfs() or self._windows_name())
        if data is None:
            data = self._payload(None)
        self._cache = data
        self._ts = now
        return data

    def _nvidia(self):
        exe = shutil.which("nvidia-smi")
        if not exe:
            return None
        try:
            proc = subprocess.run(
                [exe, "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5)
        except Exception:
            return None
        lines = (proc.stdout or "").strip().splitlines()
        if proc.returncode != 0 or not lines:
            return None
        parts = [part.strip() for part in lines[0].split(",")]
        if len(parts) < 5:
            return None
        used = _float_or_none(parts[2])
        total = _float_or_none(parts[3])
        return self._payload(
            parts[0] or "NVIDIA GPU",
            _float_or_none(parts[1]),
            int(used * 1024 * 1024) if used else None,
            int(total * 1024 * 1024) if total else None,
            _float_or_none(parts[4]),
            "nvidia-smi",
        )

    def _amd_sysfs(self):
        if os.name == "nt":
            return None
        for busy in glob.glob("/sys/class/drm/card[0-9]*/device/gpu_busy_percent"):
            device = Path(busy).parent
            try:
                percent = float(Path(busy).read_text().strip())
            except (OSError, ValueError):
                percent = None
            used = _read_int(device / "mem_info_vram_used")
            total = _read_int(device / "mem_info_vram_total")
            temp = None
            for hw in (device / "hwmon").glob("hwmon*"):
                for name in ("temp1_input", "temp2_input"):
                    raw = _read_int(hw / name)
                    if raw and 0 < raw < 150000:
                        temp = raw / 1000.0
                        break
                if temp:
                    break
            return self._payload("AMD GPU", percent, used, total, temp, "sysfs")
        return None

    def _intel_sysfs(self):
        if os.name == "nt":
            return None
        for uevent in glob.glob("/sys/class/drm/card[0-9]*/device/uevent"):
            try:
                text = Path(uevent).read_text(errors="ignore")
            except OSError:
                continue
            if "i915" not in text and "xe" not in text:
                continue
            temp = None
            for hw in (Path(uevent).parent / "hwmon").glob("hwmon*"):
                raw = _read_int(hw / "temp1_input")
                if raw and 0 < raw < 150000:
                    temp = raw / 1000.0
                    break
            return self._payload("Intel GPU", None, None, None, temp, "sysfs")
        return None

    def _windows_name(self):
        if os.name != "nt":
            return None
        if self._win_checked:
            return self._win_payload
        self._win_checked = True
        try:
            proc = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "(Get-CimInstance Win32_VideoController | Select-Object -First 1 -ExpandProperty Name)"],
                capture_output=True, text=True, timeout=8)
            name = (proc.stdout or "").strip().splitlines()
            if name and name[0].strip():
                self._win_payload = self._payload(name[0].strip(), source="wmi")
        except Exception:
            pass
        return self._win_payload


class Collector(threading.Thread):
    """Muestrea el sistema cada segundo y guarda historial para las graficas."""

    def __init__(self, interval: float = 1.0):
        super().__init__(daemon=True, name="collector")
        self.interval = interval
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._snapshot = {}
        self._history = {k: collections.deque(maxlen=HISTORY_LEN)
                         for k in ("cpu", "ram", "net_down", "net_up", "temp", "load",
                                   "gpu", "gpu_temp")}
        self._last_net = None
        self._last_net_ts = None
        self._gpu = GpuReader()
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
            return None, None
        try:
            sensors = psutil.sensors_temperatures() or {}
        except Exception:
            return None, None
        candidates = ("coretemp", "k10temp", "cpu_thermal", "zenpower", "acpitz")
        for name in candidates:
            for entry in sensors.get(name, []):
                if entry.current and 0 < entry.current < 125:
                    return float(entry.current), name
        for name, entries in sensors.items():
            if any(token in name.lower() for token in ("gpu", "amdgpu", "nouveau", "nvidia", "radeon")):
                continue
            for entry in entries:
                if entry.current and 0 < entry.current < 125:
                    return float(entry.current), name
        return None, None

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
        temp, temp_source = self._cpu_temp()
        gpu = self._gpu.read()
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
            "gpu": gpu,
            "sensors": {
                "cpu_source": temp_source,
                "cpu_temp": temp,
                "gpu_source": gpu.get("source"),
                "gpu_temp": gpu.get("temp"),
            },
            "services": services,
        }

        with self._lock:
            self._history["cpu"].append(cpu_percent)
            self._history["ram"].append(ram_percent)
            self._history["net_down"].append(net_down)
            self._history["net_up"].append(net_up)
            self._history["temp"].append(temp or 0.0)
            self._history["load"].append(load[0])
            self._history["gpu"].append(gpu.get("percent") or 0.0)
            self._history["gpu_temp"].append(gpu.get("temp") or 0.0)
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
