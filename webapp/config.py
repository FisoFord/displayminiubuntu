# SPDX-License-Identifier: GPL-3.0-or-later
"""Configuracion, valores por defecto y presets del panel web."""

from __future__ import annotations

import copy

CANVAS_W = 320
CANVAS_H = 480

WIDGET_TYPES = ("ring", "bar", "spark", "metric", "text", "clock", "services", "host")

METRIC_INFO = {
    "cpu":      {"label": "CPU", "unit": "%", "kind": "percent"},
    "ram":      {"label": "RAM", "unit": "%", "kind": "percent"},
    "swap":     {"label": "SWAP", "unit": "%", "kind": "percent"},
    "disk":     {"label": "DISCO", "unit": "%", "kind": "percent"},
    "temp":     {"label": "TEMP", "unit": "C", "kind": "temp"},
    "load":     {"label": "LOAD", "unit": "", "kind": "load"},
    "net_down": {"label": "BAJADA", "unit": "", "kind": "rate"},
    "net_up":   {"label": "SUBIDA", "unit": "", "kind": "rate"},
    "procs":    {"label": "PROCESOS", "unit": "", "kind": "count"},
    "freq":     {"label": "FRECUENCIA", "unit": "MHz", "kind": "freq"},
    "docker":   {"label": "CONTENEDORES", "unit": "", "kind": "count"},
    "failed":   {"label": "FALLOS", "unit": "", "kind": "count"},
    "uptime":   {"label": "UPTIME", "unit": "", "kind": "uptime"},
}

DEFAULT_CONFIG = {
    "version": 1,
    "design": "minimal",
    "display": {
        "enabled": True,
        "brightness": 25,
        "fps": 1,
    },
    "background": {
        "images": [],
        "rotate_seconds": 20,
        "opacity": 0.35,
        "blur": 1.5,
        "tint": "#070b14",
        "tint_strength": 0.55,
        "fit": "cover",
        "shade": 0.25,
        "base_color": "#05070d",
    },
    "widgets": [],
}


def _base_widget(wtype: str, wid: str, **kw):
    w = {
        "id": wid,
        "type": wtype,
        "x": 16, "y": 16, "w": 150, "h": 100,
        "panel": False,
        "panel_color": "#0b1220b3",
        "radius": 12,
        "font_size": 18,
        "color": "#22d3ee",
        "label_color": "#94a3b8",
        "value_color": "#f8fafc",
        "track_color": "#1e293b",
        "label": "",
        "metric": "cpu",
        "units": [],
        "source": "systemd",
        "text": "",
        "align": "left",
        "bold": True,
    }
    w.update(kw)
    return w


# ---------------------------------------------------------------------------
# Presets
# ---------------------------------------------------------------------------

def _preset_proxmox():
    return [
        _base_widget("clock", "clock", x=16, y=10, w=288, h=52, font_size=22),
        _base_widget("ring", "cpu", metric="cpu", x=16, y=70, w=132, h=132,
                     color="#22d3ee", font_size=24, label="CPU"),
        _base_widget("ring", "ram", metric="ram", x=172, y=70, w=132, h=132,
                     color="#a78bfa", font_size=24, label="RAM"),
        _base_widget("bar", "netdown", metric="net_down", x=16, y=210, w=288, h=62,
                     color="#34d399", font_size=16, label="RED BAJADA"),
        _base_widget("bar", "disk", metric="disk", x=16, y=278, w=288, h=62,
                     color="#f59e0b", font_size=16, label="DISCO"),
        _base_widget("services", "svc", x=16, y=348, w=288, h=118, font_size=13,
                     label="SERVICIOS", units=[]),
    ]


def _preset_minimal():
    return [
        _base_widget("clock", "clock", x=16, y=10, w=288, h=52, font_size=30),
        _base_widget("metric", "cpu", metric="cpu", x=16, y=68, w=288, h=104,
                     font_size=60, label="USO DE CPU", color="#22d3ee"),
        _base_widget("bar", "ram", metric="ram", x=16, y=178, w=288, h=44,
                     color="#a78bfa", font_size=18, label="MEMORIA"),
        _base_widget("bar", "netdown", metric="net_down", x=16, y=228, w=288, h=44,
                     color="#34d399", font_size=18, label="RED BAJADA"),
        _base_widget("bar", "temp", metric="temp", x=16, y=278, w=288, h=44,
                     color="#fb7185", font_size=18, label="TEMPERATURA"),
        _base_widget("services", "services", x=16, y=330, w=140, h=144,
                     font_size=19, label="SERVICIOS", source="systemd"),
        _base_widget("services", "docker", x=164, y=330, w=140, h=144,
                     font_size=19, label="CONTENEDORES", source="docker"),
    ]


def _preset_neon():
    return [
        _base_widget("clock", "clock", x=16, y=8, w=288, h=48, font_size=20),
        _base_widget("ring", "cpu", metric="cpu", x=16, y=64, w=132, h=132,
                     color="#22d3ee", font_size=24, label="CPU"),
        _base_widget("ring", "temp", metric="temp", x=172, y=64, w=132, h=132,
                     color="#fb7185", font_size=22, label="TEMP"),
        _base_widget("spark", "net", metric="net_down", x=16, y=204, w=288, h=78,
                     color="#34d399", font_size=13, label="RED BAJADA"),
        _base_widget("spark", "cpuh", metric="cpu", x=16, y=290, w=288, h=78,
                     color="#a78bfa", font_size=13, label="HISTORIAL CPU"),
        _base_widget("bar", "disk", metric="disk", x=16, y=376, w=288, h=48,
                     color="#f59e0b", font_size=14, label="DISCO"),
        _base_widget("text", "host", x=16, y=432, w=288, h=38, font_size=13,
                     text="{hostname}  ·  {uptime}", align="center",
                     color="#94a3b8"),
    ]


def _preset_classic():
    return [
        _base_widget("text", "title", x=16, y=12, w=288, h=40, font_size=18,
                     text="{hostname}", color="#f8fafc"),
        _base_widget("bar", "cpu", metric="cpu", x=16, y=70, w=288, h=54,
                     color="#22d3ee", font_size=15, label="CPU"),
        _base_widget("bar", "ram", metric="ram", x=16, y=132, w=288, h=54,
                     color="#a78bfa", font_size=15, label="RAM"),
        _base_widget("bar", "disk", metric="disk", x=16, y=194, w=288, h=54,
                     color="#f59e0b", font_size=15, label="DISCO"),
        _base_widget("spark", "net", metric="net_down", x=16, y=260, w=288, h=86,
                     color="#34d399", font_size=13, label="RED BAJADA"),
        _base_widget("text", "rows", x=16, y=356, w=288, h=104, font_size=14,
                     text="CPU   {cpu}\nRAM   {ram_used} / {ram_total}\nRED   {net_down}  ↓   {net_up} ↑\nUPTIME {uptime}",
                     color="#e2e8f0"),
    ]


PRESETS = {
    "proxmox": {"label": "Proxmox", "widgets": _preset_proxmox},
    "minimal": {"label": "Minimal", "widgets": _preset_minimal},
    "neon": {"label": "Neón", "widgets": _preset_neon},
    "classic": {"label": "Clásico", "widgets": _preset_classic},
}


def _signature(widgets):
    return tuple(
        (w.get("type"), w.get("metric"), w.get("label"), w.get("text"),
         w.get("source"), w.get("x"), w.get("y"), w.get("w"), w.get("h"))
        for w in widgets or []
    )


_PRESET_SIGNATURES = {name: _signature(preset["widgets"]())
                      for name, preset in PRESETS.items()}


def detect_design(widgets) -> str:
    """Nombre del diseno que coincide con los widgets, o 'custom'."""
    signature = _signature(widgets)
    for name, preset_signature in _PRESET_SIGNATURES.items():
        if preset_signature == signature:
            return name
    return "custom"


def default_config() -> dict:
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["widgets"] = _preset_minimal()
    return cfg


# ---------------------------------------------------------------------------
# Normalizacion
# ---------------------------------------------------------------------------

def _num(value, low, high, default):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return default
    if value != value:  # NaN
        return default
    return max(low, min(high, value))


def _clamp_int(value, low, high, default):
    return int(round(_num(value, low, high, default)))


def _color(value, default):
    if not isinstance(value, str):
        return default
    value = value.strip()
    if len(value) in (4, 7, 9) and value.startswith("#"):
        try:
            int(value[1:], 16)
            return value.lower()
        except ValueError:
            return default
    return default


def normalize(cfg) -> dict:
    """Devuelve una configuracion valida, rellenando y recortando valores."""
    out = copy.deepcopy(DEFAULT_CONFIG)
    if not isinstance(cfg, dict):
        return default_config()

    disp = cfg.get("display") if isinstance(cfg.get("display"), dict) else {}
    out["display"]["enabled"] = bool(disp.get("enabled", out["display"]["enabled"]))
    out["display"]["brightness"] = _clamp_int(disp.get("brightness"), 0, 100,
                                              out["display"]["brightness"])
    out["display"]["fps"] = _num(disp.get("fps"), 0.3, 5, out["display"]["fps"])

    bg = cfg.get("background") if isinstance(cfg.get("background"), dict) else {}
    images = bg.get("images", [])
    if isinstance(images, str):
        images = [images]
    out["background"]["images"] = [i for i in images if isinstance(i, str)][:64]
    out["background"]["rotate_seconds"] = _clamp_int(bg.get("rotate_seconds"), 0, 86400, 20)
    out["background"]["opacity"] = _num(bg.get("opacity"), 0, 1, out["background"]["opacity"])
    out["background"]["blur"] = _num(bg.get("blur"), 0, 30, out["background"]["blur"])
    out["background"]["tint"] = _color(bg.get("tint"), out["background"]["tint"])
    out["background"]["tint_strength"] = _num(bg.get("tint_strength"), 0, 1,
                                             out["background"]["tint_strength"])
    out["background"]["fit"] = bg.get("fit") if bg.get("fit") in ("cover", "contain", "stretch") else "cover"
    out["background"]["shade"] = _num(bg.get("shade"), 0, 1, out["background"]["shade"])
    out["background"]["base_color"] = _color(bg.get("base_color"), out["background"]["base_color"])

    raw_widgets = cfg.get("widgets", [])
    widgets = []
    if isinstance(raw_widgets, list):
        for index, raw in enumerate(raw_widgets[:40]):
            if not isinstance(raw, dict):
                continue
            wtype = raw.get("type")
            if wtype not in WIDGET_TYPES:
                continue
            wid = str(raw.get("id") or f"{wtype}-{index}")[:40]
            w = _base_widget(wtype, wid)
            w.update({k: raw[k] for k in raw if k in w})
            w["id"] = wid
            w["type"] = wtype
            w["x"] = _clamp_int(raw.get("x"), -CANVAS_W + 32, CANVAS_W - 16, w["x"])
            w["y"] = _clamp_int(raw.get("y"), -CANVAS_H + 32, CANVAS_H - 16, w["y"])
            w["w"] = _clamp_int(raw.get("w"), 40, CANVAS_W, w["w"])
            w["h"] = _clamp_int(raw.get("h"), 24, CANVAS_H, w["h"])
            w["font_size"] = _clamp_int(raw.get("font_size"), 8, 80, w["font_size"])
            w["radius"] = _clamp_int(raw.get("radius"), 0, 40, w["radius"])
            w["panel"] = bool(raw.get("panel", w["panel"]))
            w["bold"] = bool(raw.get("bold", w["bold"]))
            w["panel_color"] = _color(raw.get("panel_color"), w["panel_color"])
            w["color"] = _color(raw.get("color"), w["color"])
            w["label_color"] = _color(raw.get("label_color"), w["label_color"])
            w["value_color"] = _color(raw.get("value_color"), w["value_color"])
            w["track_color"] = _color(raw.get("track_color"), w["track_color"])
            if wtype in ("ring", "bar", "spark", "metric"):
                if raw.get("metric") in METRIC_INFO:
                    w["metric"] = raw["metric"]
            if wtype == "text":
                w["text"] = str(raw.get("text", ""))[:500]
                w["align"] = raw.get("align") if raw.get("align") in ("left", "center", "right") else "left"
            if wtype == "services":
                units = raw.get("units", [])
                w["units"] = [str(u)[:120] for u in units if isinstance(u, str)][:30] \
                    if isinstance(units, list) else []
                w["source"] = raw.get("source") if raw.get("source") in ("systemd", "docker") else "systemd"
            w["label"] = str(raw.get("label") or METRIC_INFO.get(w.get("metric"), {}).get("label", ""))[:40] \
                if wtype in ("ring", "bar", "spark") else str(raw.get("label", ""))[:80]
            widgets.append(w)
    out["widgets"] = widgets

    requested = cfg.get("design")
    detected = detect_design(widgets)
    out["design"] = requested if (requested in PRESETS and detected == requested) else detected
    return out
