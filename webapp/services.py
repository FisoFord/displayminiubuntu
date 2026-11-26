# SPDX-License-Identifier: GPL-3.0-or-later
"""Integracion con systemd y Docker para la vista tipo Proxmox."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time

_LOCK = threading.Lock()
_CACHE = {"ts": 0.0, "data": None}
_CACHE_TTL = 6.0
_CPU_PREV = {}  # unit -> (monotonic, cpu_ns)
_ACTIONS_CACHE = {"ts": 0.0, "allowed": False}
_UNIT_RE = re.compile(r"^[A-Za-z0-9@._:\\-]+$")
_DOCKER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\\-]*$")
ACTIONS = ("start", "stop", "restart", "enable", "disable")


def _run(cmd, timeout=12):
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return proc.returncode, (proc.stdout or "").strip(), (proc.stderr or "").strip()
    except FileNotFoundError:
        return 127, "", f"no se encontro {cmd[0]}"
    except subprocess.TimeoutExpired:
        return 124, "", "tiempo de espera agotado"
    except Exception as exc:  # pragma: no cover
        return 1, "", str(exc)


def has_systemd() -> bool:
    return os.name == "posix" and shutil.which("systemctl") is not None \
        and os.path.isdir("/run/systemd/system")


def has_docker() -> bool:
    return shutil.which("docker") is not None


def actions_allowed() -> bool:
    now = time.monotonic()
    if now - _ACTIONS_CACHE["ts"] < 30:
        return _ACTIONS_CACHE["allowed"]
    if os.environ.get("WEBAPP_ACTIONS", "1") in ("0", "false", "no"):
        allowed = False
    elif hasattr(os, "geteuid") and os.geteuid() == 0:
        allowed = True
    else:
        code, _, _ = _run(["sudo", "-n", "true"], timeout=5)
        allowed = code == 0
    _ACTIONS_CACHE.update({"ts": now, "allowed": allowed})
    return allowed


# ---------------------------------------------------------------------------
# systemd
# ---------------------------------------------------------------------------

def _list_units():
    code, out, err = _run(["systemctl", "list-units", "--type=service", "--all",
                           "--no-pager", "--no-legend", "--plain"])
    if code != 0:
        return [], err or "systemctl no disponible"
    units = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 4)
        if len(parts) < 4:
            continue
        unit, load, active, sub = parts[0], parts[1], parts[2], parts[3]
        description = parts[4] if len(parts) > 4 else ""
        if not unit.endswith(".service"):
            continue
        units.append({
            "unit": unit,
            "load": load,
            "active": active,
            "sub": sub,
            "description": description,
        })
    return units, ""


def _show_units(names):
    """systemctl show para varios units a la vez (bloques separados por linea vacia)."""
    info = {}
    for start in range(0, len(names), 40):
        chunk = names[start:start + 40]
        code, out, _ = _run(["systemctl", "show", "--no-pager",
                             "-p", "Id", "-p", "ActiveState", "-p", "SubState",
                             "-p", "MainPID", "-p", "MemoryCurrent",
                             "-p", "CPUUsageNSec", "-p", "ActiveEnterTimestamp"]
                            + chunk, timeout=15)
        if code != 0:
            continue
        for block in re.split(r"\n\s*\n", out):
            props = {}
            for line in block.splitlines():
                if "=" in line:
                    key, value = line.split("=", 1)
                    props[key.strip()] = value.strip()
            unit = props.get("Id")
            if unit:
                info[unit] = props
    return info


def _parse_ns(value):
    try:
        number = int(value)
        return number if number >= 0 else None
    except (TypeError, ValueError):
        return None


def _systemd_payload():
    units, error = _list_units()
    if not units:
        return [], error
    interesting = [u["unit"] for u in units
                   if u["active"] in ("active", "failed", "activating", "deactivating")]
    details = _show_units(interesting)
    now = time.monotonic()
    result = []
    for unit in units:
        props = details.get(unit["unit"], {})
        mem = _parse_ns(props.get("MemoryCurrent"))
        cpu_ns = _parse_ns(props.get("CPUUsageNSec"))
        cpu_percent = None
        if cpu_ns is not None:
            prev = _CPU_PREV.get(unit["unit"])
            if prev and now > prev[0]:
                elapsed = now - prev[0]
                if elapsed >= 1:
                    cpu_percent = max((cpu_ns - prev[1]) / 1e9 / elapsed * 100.0, 0.0)
            _CPU_PREV[unit["unit"]] = (now, cpu_ns)
        main_pid = props.get("MainPID")
        result.append({
            "unit": unit["unit"],
            "description": unit["description"],
            "active": props.get("ActiveState", unit["active"]),
            "sub": props.get("SubState", unit["sub"]),
            "main_pid": int(main_pid) if main_pid and main_pid.isdigit() else None,
            "memory": mem,
            "cpu": round(cpu_percent, 1) if cpu_percent is not None else None,
            "since": props.get("ActiveEnterTimestamp") or "",
        })
    order = {"failed": 0, "activating": 1, "active": 2, "deactivating": 3, "inactive": 4}
    result.sort(key=lambda r: (order.get(r["active"], 5), r["unit"]))
    return result, ""


# ---------------------------------------------------------------------------
# Docker
# ---------------------------------------------------------------------------

def _docker_cmd(args):
    code, out, err = _run(["docker"] + args, timeout=15)
    if code == 0:
        return code, out, err
    if shutil.which("sudo"):
        code2, out2, err2 = _run(["sudo", "-n", "docker"] + args, timeout=15)
        if code2 == 0:
            return code2, out2, err2
    return code, out, err


def _docker_payload():
    if not has_docker():
        return [], "docker no instalado"
    code, out, err = _docker_cmd(["ps", "-a", "--format", "{{json .}}"])
    if code != 0:
        return [], err or "no se pudo consultar docker (permisos)"
    containers = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        containers.append({
            "name": item.get("Names", ""),
            "image": item.get("Image", ""),
            "state": (item.get("State") or "").lower(),
            "status": item.get("Status", ""),
            "ports": item.get("Ports", ""),
        })
    containers.sort(key=lambda c: (c["state"] != "running", c["name"]))
    return containers, ""


# ---------------------------------------------------------------------------
# API publica
# ---------------------------------------------------------------------------

def get_services(force: bool = False) -> dict:
    with _LOCK:
        now = time.monotonic()
        if not force and _CACHE["data"] and now - _CACHE["ts"] < _CACHE_TTL:
            return _CACHE["data"]
        systemd_units, systemd_error = ([], "systemd no disponible")
        if has_systemd():
            systemd_units, systemd_error = _systemd_payload()
        docker_containers, docker_error = ([], "")
        try:
            docker_containers, docker_error = _docker_payload()
        except Exception as exc:
            docker_error = str(exc)
        data = {
            "systemd": systemd_units,
            "systemd_error": systemd_error,
            "docker": docker_containers,
            "docker_error": docker_error,
            "actions_allowed": actions_allowed(),
            "generated": time.time(),
        }
        _CACHE.update({"ts": now, "data": data})
        return data


def summary() -> dict:
    data = get_services()
    units = data.get("systemd", [])
    running = sum(1 for u in units if u["active"] == "active")
    failed = sum(1 for u in units if u["active"] == "failed")
    containers = data.get("docker", [])
    return {
        "running": running,
        "failed": failed,
        "total": len(units),
        "docker_running": sum(1 for c in containers if c["state"] == "running"),
        "docker_total": len(containers),
    }


def selected_units(names):
    """Devuelve el estado de los units pedidos, respetando el orden."""
    data = get_services()
    index = {u["unit"]: u for u in data.get("systemd", [])}
    return [index[n] for n in names if n in index]


def action(scope: str, name: str, act: str):
    if act not in ACTIONS:
        return False, f"Accion no permitida: {act}"
    if scope == "systemd":
        if not _UNIT_RE.match(name or ""):
            return False, "Nombre de unidad no valido"
        cmd = ["systemctl", act, name]
    elif scope == "docker":
        if not _DOCKER_RE.match(name or ""):
            return False, "Nombre de contenedor no valido"
        cmd = ["docker", act, name]
    else:
        return False, "Scope no valido"

    if os.geteuid() != 0:
        cmd = ["sudo", "-n"] + cmd
    code, out, err = _run(cmd, timeout=25)
    with _LOCK:
        _CACHE["ts"] = 0.0
    if code == 0:
        return True, (out or f"{act} {name}: ok").splitlines()[-1][:200]
    return False, (err or out or f"fallo al ejecutar {act} {name}")[:300]


def sudoers_commands() -> list:
    """Comandos que el instalador puede autorizar con sudoers."""
    systemctl = shutil.which("systemctl") or "/usr/bin/systemctl"
    docker = shutil.which("docker")
    commands = []
    for act in ACTIONS:
        commands.append(f"{systemctl} {act} *")
    if docker:
        for act in ACTIONS:
            commands.append(f"{docker} {act} *")
    return commands
