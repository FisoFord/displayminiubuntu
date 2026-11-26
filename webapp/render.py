# SPDX-License-Identifier: GPL-3.0-or-later
"""Render del panel: fondo con marca de agua + widgets sobre 320x480."""

from __future__ import annotations

import math
import os
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from config import CANVAS_H, CANVAS_W, METRIC_INFO
from collect import human_rate, human_uptime

# ---------------------------------------------------------------------------
# Fuentes y colores
# ---------------------------------------------------------------------------

_FONT_FILES = {
    True: [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/seguisb.ttf",
        "DejaVuSans-Bold.ttf",
        "arialbd.ttf",
    ],
    False: [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
        "DejaVuSans.ttf",
        "arial.ttf",
    ],
}
_FONT_CACHE = {}
_FONT_PATH = {}


def _font_path(bold: bool):
    if bold in _FONT_PATH:
        return _FONT_PATH[bold]
    for candidate in _FONT_FILES[bold]:
        try:
            ImageFont.truetype(candidate, 10)
            _FONT_PATH[bold] = candidate
            return candidate
        except OSError:
            continue
    _FONT_PATH[bold] = None
    return None


def font(size: int, bold: bool = False):
    size = max(int(size), 6)
    key = (size, bold)
    if key not in _FONT_CACHE:
        path = _font_path(bold)
        try:
            _FONT_CACHE[key] = ImageFont.truetype(path, size) if path else ImageFont.load_default()
        except OSError:
            _FONT_CACHE[key] = ImageFont.load_default()
    return _FONT_CACHE[key]


def rgba(color: str, alpha: int | None = None):
    value = (color or "#ffffff").lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    try:
        r, g, b = int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)
        a = int(value[6:8], 16) if len(value) >= 8 else 255
    except (ValueError, IndexError):
        r, g, b, a = 255, 255, 255, 255
    if alpha is not None:
        a = max(0, min(255, int(alpha)))
    return (r, g, b, a)


def _fit_font(draw, text: str, size: int, max_width: int, bold: bool, min_size: int = 8):
    size = max(int(size), min_size)
    while size > min_size:
        f = font(size, bold)
        if draw.textlength(text, font=f) <= max_width:
            return f
        size -= 1
    return font(min_size, bold)


def _short(text: str, limit: int = 40) -> str:
    text = str(text or "")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _ellipsize(draw, text: str, font_obj, max_width: int) -> str:
    """Recorta un texto por ancho real de fuente, no por numero de caracteres."""
    text = str(text or "")
    if max_width <= 4:
        return ""
    if draw.textlength(text, font=font_obj) <= max_width:
        return text
    while text and draw.textlength(text + "…", font=font_obj) > max_width:
        text = text[:-1]
    return (text + "…") if text else ""


def _text(draw, xy, text, font_obj, fill, anchor=None):
    """Texto limpio, sin contorno ni sombra."""
    kwargs = {"font": font_obj, "fill": fill}
    if anchor:
        kwargs["anchor"] = anchor
    draw.text(xy, text, **kwargs)


# ---------------------------------------------------------------------------
# Metricas
# ---------------------------------------------------------------------------

def _rate_parts(value: float):
    value = float(value or 0)
    units = ("B/s", "KB/s", "MB/s", "GB/s", "TB/s")
    idx = 0
    while value >= 1024 and idx < len(units) - 1:
        value /= 1024.0
        idx += 1
    if idx == 0:
        return f"{int(value)}", units[idx]
    return f"{value:.1f}", units[idx]


def metric_data(stats: dict, metric: str) -> dict:
    """Devuelve valor normalizado, maximo, texto, unidad y etiqueta."""
    info = METRIC_INFO.get(metric, METRIC_INFO["cpu"])
    label = info["label"]
    history = (stats.get("history") or {}).get(metric) or []

    if metric == "cpu":
        value = float(stats.get("cpu", {}).get("percent") or 0)
        return {"value": value, "max": 100.0, "text": f"{value:.0f}", "unit": "%",
                "label": label, "sub": f"{stats.get('cpu', {}).get('count', '?')} hilos"}
    if metric == "ram":
        ram = stats.get("ram", {})
        value = float(ram.get("percent") or 0)
        return {"value": value, "max": 100.0, "text": f"{value:.0f}", "unit": "%",
                "label": label, "sub": f"{ram.get('used_str', '?')} / {ram.get('total_str', '?')}"}
    if metric == "swap":
        value = float(stats.get("ram", {}).get("swap_percent") or 0)
        return {"value": value, "max": 100.0, "text": f"{value:.0f}", "unit": "%",
                "label": label, "sub": ""}
    if metric == "disk":
        disk = stats.get("disk", {})
        value = float(disk.get("percent") or 0)
        busy = disk.get("busy")
        text = f"{value:.0f}%"
        if busy is not None:
            text += f" · {busy:.0f}%act"
        free = max(0, min(100, int(round(100.0 - value))))
        if free < 10:
            free_color = "#fb7185"
        elif free <= 30:
            free_color = "#fbbf24"
        else:
            free_color = "#34d399"
        parts = []
        if disk.get("read_str"):
            parts.append(f"R {disk['read_str']}")
        if disk.get("write_str"):
            parts.append(f"W {disk['write_str']}")
        if disk.get("latency") is not None:
            parts.append(f"{disk['latency']:.0f} ms")
        sub = " · ".join(parts) if parts else "sin datos E/S"
        type_label = disk.get("type_label") or "ALMACENAMIENTO"
        return {"value": value, "max": 100.0, "text": text, "unit": "",
                "label": type_label, "free": free, "free_color": free_color, "sub": sub}
    if metric == "temp":
        temp = stats.get("cpu", {}).get("temp")
        value = float(temp or 0)
        return {"value": value, "max": 100.0,
                "text": f"{temp:.0f}" if temp is not None else "--",
                "unit": "°C", "label": label,
                "sub": "sensor CPU" if temp is not None else "sin sensor"}
    if metric == "load":
        value = float(stats.get("cpu", {}).get("load") or 0)
        top = max(float(stats.get("cpu", {}).get("count") or 1) * 1.5, value * 1.2, 1.0)
        return {"value": value, "max": top, "text": f"{value:.2f}", "unit": "",
                "label": label, "sub": "1 minuto"}
    if metric in ("net_down", "net_up"):
        value = float(stats.get("net", {}).get(metric.split("_")[1]) or 0)
        number, unit = _rate_parts(value)
        peak = max(history) if history else 0
        top = max(peak * 1.3, 64 * 1024)
        return {"value": value, "max": top, "text": number, "unit": unit,
                "label": label, "sub": "pico " + human_rate(peak) if peak else "sin trafico"}
    if metric == "procs":
        value = float(stats.get("processes") or 0)
        return {"value": value, "max": max(value * 1.4, 100), "text": f"{int(value)}",
                "unit": "", "label": label, "sub": "procesos"}
    if metric == "freq":
        value = float(stats.get("cpu", {}).get("freq") or 0)
        return {"value": value, "max": max(value * 1.2, 1000), "text": f"{value:.0f}",
                "unit": "MHz", "label": label, "sub": ""}
    if metric == "docker":
        svc = stats.get("services", {})
        value = float(svc.get("docker_running") or 0)
        total = float(svc.get("docker_total") or 0)
        return {"value": value, "max": max(total, 1), "text": f"{int(value)}/{int(total)}",
                "unit": "", "label": label, "sub": "en ejecucion"}
    if metric == "failed":
        svc = stats.get("services", {})
        value = float(svc.get("failed") or 0)
        return {"value": value, "max": max(value * 2, 5), "text": f"{int(value)}",
                "unit": "", "label": label, "sub": "servicios con fallo"}
    if metric == "uptime":
        seconds = float(stats.get("uptime") or 0)
        return {"value": seconds, "max": 86400, "text": human_uptime(seconds), "unit": "",
                "label": label, "sub": "encendido"}
    if metric == "gpu":
        gpu = stats.get("gpu") or {}
        available = gpu.get("percent") is not None
        value = float(gpu.get("percent") or 0)
        return {"value": value, "max": 100.0,
                "text": f"{value:.0f}" if available else "--",
                "unit": "%" if available else "",
                "label": label, "sub": gpu.get("name") or "sin GPU"}
    if metric == "gpu_temp":
        gpu = stats.get("gpu") or {}
        temp = gpu.get("temp")
        return {"value": float(temp or 0), "max": 100.0,
                "text": f"{temp:.0f}" if temp is not None else "--",
                "unit": "°C", "label": label, "sub": gpu.get("name") or "sin GPU"}
    if metric == "gpu_mem":
        gpu = stats.get("gpu") or {}
        percent = gpu.get("memory_percent")
        return {"value": float(percent or 0), "max": 100.0,
                "text": f"{percent:.0f}" if percent is not None else "--",
                "unit": "%" if percent is not None else "",
                "label": label,
                "sub": (gpu.get("memory_used_str") + " / " + gpu.get("memory_total_str")
                        if gpu.get("memory_used_str") and gpu.get("memory_total_str")
                        else "sin GPU")}
    return metric_data(stats, "cpu")


def _pct(value: float, top: float) -> float:
    if not top or top <= 0:
        return 0.0
    return max(0.0, min(1.0, float(value) / float(top)))


# ---------------------------------------------------------------------------
# Fondo
# ---------------------------------------------------------------------------

_BG_CACHE = {}
_BG_CACHE_MAX = 8


def _gradient_base(base_color: str, tint: str):
    top = rgba(base_color)[:3]
    bottom = rgba(tint)[:3]
    img = Image.new("RGB", (CANVAS_W, CANVAS_H), top)
    draw = ImageDraw.Draw(img)
    for y in range(CANVAS_H):
        k = y / max(CANVAS_H - 1, 1)
        draw.line([(0, y), (CANVAS_W, y)], fill=(
            int(top[0] + (bottom[0] - top[0]) * k),
            int(top[1] + (bottom[1] - top[1]) * k),
            int(top[2] + (bottom[2] - top[2]) * k),
        ))
    return img


def _fit_image(photo: Image.Image, fit: str):
    target = (CANVAS_W, CANVAS_H)
    if fit == "stretch":
        return photo.resize(target, Image.LANCZOS)
    scale = max(target[0] / photo.width, target[1] / photo.height) if fit == "cover" \
        else min(target[0] / photo.width, target[1] / photo.height)
    new_size = (max(1, int(photo.width * scale + 0.5)), max(1, int(photo.height * scale + 0.5)))
    photo = photo.resize(new_size, Image.LANCZOS)
    canvas = Image.new("RGB", target, (0, 0, 0))
    canvas.paste(photo, ((target[0] - photo.width) // 2, (target[1] - photo.height) // 2))
    return canvas


def background_image(cfg: dict, backgrounds_dir: Path, index: int = 0):
    bg = cfg.get("background", {})
    images = [name for name in bg.get("images", [])
              if name and (backgrounds_dir / name).is_file()]
    name = images[index % len(images)] if images else None
    mtime = (backgrounds_dir / name).stat().st_mtime if name else 0

    key = (name, mtime, bg.get("fit"), bg.get("opacity"), bg.get("blur"),
           bg.get("tint"), bg.get("tint_strength"), bg.get("shade"), bg.get("base_color"))
    cached = _BG_CACHE.get(key)
    if cached is not None:
        return cached

    canvas = _gradient_base(bg.get("base_color", "#05070d"), bg.get("tint", "#070b14"))
    if name:
        try:
            photo = ImageOps.exif_transpose(Image.open(backgrounds_dir / name)).convert("RGB")
            photo = _fit_image(photo, bg.get("fit", "cover"))
            blur = float(bg.get("blur") or 0)
            if blur > 0.1:
                photo = photo.filter(ImageFilter.GaussianBlur(blur))
            tint_layer = Image.new("RGB", photo.size, rgba(bg.get("tint", "#000000"))[:3])
            photo = Image.blend(photo, tint_layer, max(0.0, min(1.0, float(bg.get("tint_strength") or 0))))
            canvas = Image.blend(canvas, photo, max(0.0, min(1.0, float(bg.get("opacity") or 0))))
        except Exception:
            pass

    shade = float(bg.get("shade") or 0)
    if shade > 0:
        overlay = Image.new("RGBA", (CANVAS_W, CANVAS_H), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        for y in range(CANVAS_H):
            alpha = int(shade * 255 * (y / max(CANVAS_H - 1, 1)) ** 1.4)
            draw.line([(0, y), (CANVAS_W, y)], fill=(0, 0, 0, alpha))
        canvas = Image.alpha_composite(canvas.convert("RGBA"), overlay).convert("RGB")

    if len(_BG_CACHE) > _BG_CACHE_MAX:
        _BG_CACHE.clear()
    _BG_CACHE[key] = canvas
    return canvas


# ---------------------------------------------------------------------------
# Widgets
# ---------------------------------------------------------------------------

def _panel(img: Image.Image, widget: dict):
    """Panel translucido (se dibuja en una capa aparte en render_frame)."""
    return


def _title_row(draw, widget: dict, x, y, w, label, value_text="", color=None):
    size = max(10, int(widget.get("font_size", 18) * 0.76))
    f = font(size, False)
    label = _short(label.upper(), 30)
    if value_text:
        vf = font(size, True)
        max_label = max(20, w - draw.textlength(value_text, font=vf) - 8)
        label = _ellipsize(draw, label, f, max_label)
    _text(draw, (x, y), label, f, rgba(widget.get("label_color", "#c7d7ea")))
    if value_text:
        _text(draw, (x + w, y), value_text, vf,
              rgba(color or widget.get("value_color", "#ffffff")), anchor="ra")


def _draw_ring(img, draw, widget, data, rects):
    x, y, w, h = widget["x"], widget["y"], widget["w"], widget["h"]
    label_h = 18 if widget.get("label") else 0
    size = min(w, h - label_h)
    stroke = max(5, int(size * 0.10))
    radius = max(stroke, size // 2 - stroke // 2 - 1)
    cx = x + w // 2
    cy = y + (h - label_h) // 2
    box = [cx - radius, cy - radius, cx + radius, cy + radius]
    draw.arc(box, 0, 360, fill=rgba(widget.get("track_color", "#1e293b")), width=stroke)
    pct = _pct(data["value"], data["max"])
    color = rgba(widget.get("color", "#22d3ee"))
    if pct > 0.001:
        draw.arc(box, -90, -90 + max(3.6, 360 * pct), fill=color, width=stroke)

    value_text = data["text"]
    vf = _fit_font(draw, value_text, int(size * 0.30), int(size * 0.80), True)
    _text(draw, (cx, cy - (6 if data["unit"] else 0)), value_text, vf,
          rgba(widget.get("value_color", "#ffffff")), anchor="mm")
    if data["unit"]:
        uf = font(max(8, int(size * 0.10)), False)
        _text(draw, (cx, cy + int(size * 0.10)), data["unit"], uf,
              rgba(widget.get("label_color", "#c7d7ea")), anchor="ma")
    if widget.get("label"):
        lf = font(max(8, int(widget.get("font_size", 18) * 0.72)), True)
        _text(draw, (cx, y + h - 2), _short(widget["label"].upper(), 18), lf,
              rgba(widget.get("label_color", "#c7d7ea")), anchor="md")
    rects[widget["id"]] = [x, y, w, h]


def _draw_bar(img, draw, widget, data, rects):
    x, y, w, h = widget["x"], widget["y"], widget["w"], widget["h"]
    pad = 4
    bar_h = max(9, int(h * 0.36))
    bar_y = y + h - bar_h - pad
    size = max(10, int(widget.get("font_size", 18) * 0.76))
    f = font(size, False)
    vf = font(size, True)
    value_text = f"{data['text']} {data['unit']}".strip()
    if widget.get("metric") == "disk":
        title_w = w - pad * 2
        value_w = draw.textlength(value_text, font=vf)
        max_label = max(20, title_w - value_w - 8)
        type_label = _short(str(data["label"]).upper(), 30)
        free = data.get("free")
        suffix = f" ({free}% libre)".upper() if free is not None else ""
        suffix_w = draw.textlength(suffix, font=f) if suffix else 0
        if suffix_w > max_label:
            suffix, suffix_w = "", 0
        type_label = _ellipsize(draw, type_label, f, max(0, max_label - suffix_w))
        type_w = draw.textlength(type_label, font=f)
        _text(draw, (x + pad, y + pad), type_label, f,
              rgba(widget.get("label_color", "#c7d7ea")))
        if suffix and suffix_w:
            _text(draw, (x + pad + type_w, y + pad), suffix, f,
                  rgba(data.get("free_color", "#34d399")))
        _text(draw, (x + w - pad, y + pad), value_text, vf,
              rgba(widget.get("color", "#f59e0b")), anchor="ra")
    else:
        label = widget.get("label") or data["label"]
        _title_row(draw, widget, x + pad, y + pad, w - pad * 2, label, value_text,
                   widget.get("color"))

    draw.rounded_rectangle([x + pad, bar_y, x + w - pad - 1, bar_y + bar_h], radius=bar_h // 2,
                           fill=rgba(widget.get("track_color", "#1e293b")))
    pct = _pct(data["value"], data["max"])
    fill_w = int((w - pad * 2) * pct)
    if fill_w >= 2:
        draw.rounded_rectangle([x + pad, bar_y, x + pad + fill_w, bar_y + bar_h],
                               radius=bar_h // 2, fill=rgba(widget.get("color", "#22d3ee")))
    if data.get("sub") and h >= 62:
        sf = font(max(8, int(widget.get("font_size", 18) * 0.62)), False)
        _text(draw, (x + pad, bar_y - 3), _short(data["sub"], 34), sf,
              rgba(widget.get("label_color", "#c7d7ea")), anchor="ld")
    rects[widget["id"]] = [x, y, w, h]


def _draw_spark(img, draw, widget, data, rects):
    x, y, w, h = widget["x"], widget["y"], widget["w"], widget["h"]
    pad = 5
    head = 18
    _title_row(draw, widget, x + pad, y + pad, w - pad * 2, widget.get("label") or data["label"],
               f"{data['text']} {data['unit']}".strip(), widget.get("color"))
    series = [float(v or 0) for v in (data.get("series") or [])]
    top = max(data["max"], max(series) if series else 0, 1e-6)
    area = [x + pad, y + head, w - pad * 2, h - head - pad]
    if area[2] < 4 or area[3] < 4:
        rects[widget["id"]] = [x, y, w, h]
        return
    if len(series) < 2:
        draw.line([area[0], area[1] + area[3] // 2, area[0] + area[2], area[1] + area[3] // 2],
                  fill=rgba(widget.get("track_color", "#1e293b")), width=1)
        rects[widget["id"]] = [x, y, w, h]
        return

    step = area[2] / (len(series) - 1)
    points = [(area[0] + i * step, area[1] + area[3] - _pct(v, top) * area[3])
              for i, v in enumerate(series)]
    layer = Image.new("RGBA", (area[2] + 1, area[3] + 1), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    polygon = points + [(area[0] + area[2], area[1] + area[3]), (area[0], area[1] + area[3])]
    ld.polygon(polygon, fill=rgba(widget.get("color", "#22d3ee"), 45))
    img.paste(layer, (int(area[0]), int(area[1])), layer)
    draw.line(points, fill=rgba(widget.get("color", "#22d3ee")), width=2, joint="curve")
    rects[widget["id"]] = [x, y, w, h]


def _draw_metric(img, draw, widget, data, rects):
    """Numero grande con etiqueta arriba y detalle abajo, sin solaparse."""
    x, y, w, h = widget["x"], widget["y"], widget["w"], widget["h"]
    pad = 6
    base_size = max(12, int(widget.get("font_size", 40)))
    label = (widget.get("label") or data["label"] or "").upper()
    sub = data.get("sub") or ""

    label_size = max(9, int(base_size * 0.34))
    sub_size = max(8, int(base_size * 0.30))
    label_h = label_size + 4 if label else 0
    sub_h = sub_size + 5 if sub else 0

    if label:
        _text(draw, (x + pad, y + pad), _short(label, 28),
              font(label_size, False), rgba(widget.get("label_color", "#c7d7ea")))

    top = y + pad + label_h
    bottom = y + h - pad - sub_h
    if bottom - top < 12:
        top, bottom = y + pad, y + h - pad
    center = (top + bottom) // 2

    text = data["text"]
    unit = data["unit"]
    unit_size = max(9, int(base_size * 0.36))
    unit_w = draw.textlength(" " + unit, font=font(unit_size, True)) if unit else 0
    avail_w = max(24, w - pad * 2 - unit_w)
    avail_h = max(10, bottom - top)

    # Se reduce el tamano hasta que quepa a lo ancho y a lo alto disponibles
    size = max(8, base_size)
    while size > 8:
        candidate = font(size, True)
        bbox = draw.textbbox((0, 0), text, font=candidate)
        if draw.textlength(text, font=candidate) <= avail_w and (bbox[3] - bbox[1]) <= avail_h:
            break
        size -= 1

    vf = font(size, True)
    _text(draw, (x + pad, center), text, vf,
          rgba(widget.get("value_color", "#ffffff")), anchor="lm")
    if unit:
        _text(draw, (x + pad + draw.textlength(text, font=vf) + 4, center), unit,
              font(unit_size, True), rgba(widget.get("color", "#22d3ee")), anchor="lm")
    if sub:
        _text(draw, (x + pad, y + h - pad), _short(sub, 40),
              font(sub_size, False), rgba(widget.get("label_color", "#c7d7ea")), anchor="ld")
    rects[widget["id"]] = [x, y, w, h]


def _draw_text(img, draw, widget, stats, rects):
    x, y, w, h = widget["x"], widget["y"], widget["w"], widget["h"]
    text = format_template(widget.get("text", ""), stats)
    lines = text.splitlines()[:20] or [""]
    bold = widget.get("bold", False)
    align = widget.get("align", "left")
    anchor_x = {"left": x, "center": x + w // 2, "right": x + w}[align]
    anchor = {"left": "la", "center": "ma", "right": "ra"}[align]
    color = rgba(widget.get("color", "#ffffff"))

    # Reduce el tamano hasta que el bloque quepa a lo ancho y a lo alto
    size = max(8, int(widget.get("font_size", 16)))
    while size > 8:
        candidate = font(size, bold)
        line_h = int(size * 1.35)
        widest = max(draw.textlength(line, font=candidate) for line in lines)
        if widest <= w and line_h * len(lines) <= h:
            break
        size -= 1

    f = font(size, bold)
    line_h = int(size * 1.35)
    for row, line in enumerate(lines):
        _text(draw, (anchor_x, y + row * line_h), line, f, color, anchor=anchor)
    rects[widget["id"]] = [x, y, w, h]


def _draw_clock(img, draw, widget, stats, rects):
    x, y, w, h = widget["x"], widget["y"], widget["w"], widget["h"]
    pad = 4
    fs = max(10, int(widget.get("font_size", 38)))
    # La fecha/hostname/GPU no crecen con la hora; se limita su alto para
    # que las tres lineas sigan cabiendo en el reloj.
    sf_size = max(8, min(int(fs * 0.42), int(h / (3 * 1.35))))
    sf = font(sf_size, False)

    max_right = int(w * 0.58)
    lines = [f"{stats.get('weekday', '')} {stats.get('date', '')}".strip(),
             stats.get("hostname", "")]
    gpu = stats.get("gpu") or {}
    if gpu.get("available"):
        if gpu.get("percent") is not None and gpu.get("temp") is not None:
            gpu_text = f"GPU {gpu['percent']:.0f}% · {gpu['temp']:.0f}°C"
        elif gpu.get("percent") is not None:
            gpu_text = f"GPU {gpu['percent']:.0f}%"
        elif gpu.get("temp") is not None:
            gpu_text = f"GPU {gpu['temp']:.0f}°C"
        else:
            gpu_text = "GPU n/d"
        lines.append(gpu_text)
    lines = [_ellipsize(draw, line, sf, max_right) for line in lines]
    right_w = max(draw.textlength(line, font=sf) for line in lines)

    time_text = stats.get("time", "--:--")
    vf = _fit_font(draw, time_text, fs, int(w - right_w - pad * 2 - 10), True)
    _text(draw, (x + pad, y + h // 2), time_text, vf,
          rgba(widget.get("value_color", "#ffffff")), anchor="lm")

    line_h = int(sf_size * 1.35)
    block_top = y + (h - line_h * len(lines)) // 2
    for index, line in enumerate(lines):
        _text(draw, (x + w - pad, block_top + index * line_h), line, sf,
              rgba(widget.get("label_color", "#c7d7ea")), anchor="ra")
    rects[widget["id"]] = [x, y, w, h]


def _draw_host(img, draw, widget, stats, rects):
    x, y, w, h = widget["x"], widget["y"], widget["w"], widget["h"]
    pad = 6
    lf = font(max(9, int(widget.get("font_size", 14) * 0.9)), True)
    _text(draw, (x + pad, y + pad), _short(stats.get("hostname", "host"), 26), lf,
          rgba(widget.get("value_color", "#ffffff")))
    sf = font(max(8, int(widget.get("font_size", 14) * 0.78)), False)
    rows = [
        _short(stats.get("os", ""), 32),
        f"uptime {stats.get('uptime_str', '?')}  ·  load {stats.get('cpu', {}).get('load', 0):.2f}",
        f"{stats.get('services', {}).get('running', 0)} servicios  ·  "
        f"{stats.get('services', {}).get('docker_running', 0)} contenedores",
    ]
    for i, row in enumerate(rows):
        _text(draw, (x + pad, y + pad + int(widget.get("font_size", 14) * 1.25) * (i + 1)),
              _short(row, 40), sf, rgba(widget.get("label_color", "#c7d7ea")))
    rects[widget["id"]] = [x, y, w, h]


def _service_rows(units, limit):
    try:
        import services as services_mod
        if units:
            return services_mod.selected_units(units)[:limit]
        data = services_mod.get_services()
        rows = [u for u in data.get("systemd", []) if u.get("active") in ("failed", "active")]
        rows.sort(key=lambda u: (u.get("active") != "failed", u["unit"]))
        return rows[:limit]
    except Exception:
        return []


def _container_rows(limit):
    try:
        import services as services_mod
        data = services_mod.get_services()
        rows = list(data.get("docker", []))
        rows.sort(key=lambda c: (c.get("state") != "running", c.get("name", "")))
        return rows[:limit]
    except Exception:
        return []


def _draw_services(img, draw, widget, rects):
    x, y, w, h = widget["x"], widget["y"], widget["w"], widget["h"]
    pad = 6
    source = widget.get("source", "systemd")
    title_h = 0
    if widget.get("label"):
        title_h = 16
        _title_row(draw, widget, x + pad, y + pad, w - pad * 2, widget["label"])

    rows_space = h - pad * 2 - title_h
    row_h = max(14, int(widget.get("font_size", 13) * 1.55))
    limit = max(1, rows_space // row_h)
    if source == "docker":
        rows = _container_rows(limit)
    else:
        rows = _service_rows(widget.get("units") or [], limit)

    f = font(max(8, int(widget.get("font_size", 13) * 0.9)), False)
    small = font(max(7, int(getattr(f, "size", 11) * 0.82)), False)

    if not rows:
        empty = "(sin datos)" if source == "docker" else "(sin unidades)"
        _text(draw, (x + pad, y + pad + title_h + row_h // 2), empty, small,
              rgba(widget.get("label_color", "#c7d7ea")), anchor="lm")
        rects[widget["id"]] = [x, y, w, h]
        return

    for i, item in enumerate(rows):
        cy = y + pad + title_h + i * row_h + row_h // 2
        if source == "docker":
            state = str(item.get("state", ""))
            running = state == "running"
            if running:
                state_color = "#34d399"
            elif state in ("paused", "restarting"):
                state_color = "#fbbf24"
            else:
                state_color = "#64748b"
            name = str(item.get("name", ""))
            # El punto de color ya indica el estado: sin etiqueta a la derecha
            right_text = ""
        else:
            active = item.get("active")
            state_color = {"active": "#34d399", "failed": "#fb7185",
                           "activating": "#fbbf24"}.get(active, "#64748b")
            name = str(item.get("unit", "")).replace(".service", "")
            right_text = "fallo" if active == "failed" else ""

        draw.ellipse([x + pad, cy - 3, x + pad + 6, cy + 3], fill=rgba(state_color))
        right_w = draw.textlength(right_text, font=small) + 4 if right_text else 0
        name = _ellipsize(draw, name, f, w - pad * 2 - 12 - right_w)
        _text(draw, (x + pad + 12, cy), name, f,
              rgba(widget.get("value_color", "#ffffff")), anchor="lm")
        if right_text:
            _text(draw, (x + w - pad, cy), right_text, small,
                  rgba(state_color), anchor="rm")
    rects[widget["id"]] = [x, y, w, h]


# ---------------------------------------------------------------------------
# Plantillas de texto
# ---------------------------------------------------------------------------

class _SafeDict(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def format_template(text: str, stats: dict) -> str:
    if "{" not in (text or ""):
        return text or ""
    cpu = stats.get("cpu", {})
    ram = stats.get("ram", {})
    net = stats.get("net", {})
    svc = stats.get("services", {})
    gpu = stats.get("gpu") or {}
    if gpu.get("percent") is not None and gpu.get("temp") is not None:
        gpu_text = f"{gpu['percent']:.0f}% · {gpu['temp']:.0f}°C"
    elif gpu.get("percent") is not None:
        gpu_text = f"{gpu['percent']:.0f}%"
    elif gpu.get("temp") is not None:
        gpu_text = f"{gpu['temp']:.0f}°C"
    elif gpu.get("available"):
        gpu_text = "n/d"
    else:
        gpu_text = "—"
    mapping = {
        "hostname": stats.get("hostname", ""),
        "os": stats.get("os", ""),
        "kernel": stats.get("kernel", ""),
        "uptime": stats.get("uptime_str", ""),
        "date": stats.get("date", ""),
        "time": stats.get("time", ""),
        "weekday": stats.get("weekday", ""),
        "cpu": f"{cpu.get('percent', 0):.0f}%",
        "cpu_num": f"{cpu.get('percent', 0):.0f}",
        "ram": f"{ram.get('percent', 0):.0f}%",
        "ram_used": ram.get("used_str", ""),
        "ram_total": ram.get("total_str", ""),
        "disk": f"{stats.get('disk', {}).get('percent', 0):.0f}%",
        "disk_used": stats.get("disk", {}).get("used_str", ""),
        "net_down": net.get("down_str", ""),
        "net_up": net.get("up_str", ""),
        "load": f"{cpu.get('load', 0):.2f}",
        "temp": f"{cpu.get('temp') or 0:.0f}°C",
        "procs": str(stats.get("processes", "")),
        "services_running": str(svc.get("running", 0)),
        "services_failed": str(svc.get("failed", 0)),
        "docker": str(svc.get("docker_running", 0)),
        "gpu": gpu_text,
        "gpu_line": ("GPU   " + gpu_text + "\n") if gpu.get("available") else "",
    }
    try:
        return text.format_map(_SafeDict(mapping))
    except (ValueError, IndexError):
        return text


# ---------------------------------------------------------------------------
# Frame
# ---------------------------------------------------------------------------

def render_frame(cfg: dict, stats: dict, backgrounds_dir: Path):
    index = 0
    rotate = int(cfg.get("background", {}).get("rotate_seconds") or 0)
    if rotate > 0 and cfg.get("background", {}).get("images"):
        index = int(time.time() // rotate)

    img = background_image(cfg, backgrounds_dir, index)

    # Paneles translucidos primero
    layer = Image.new("RGBA", (CANVAS_W, CANVAS_H), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    for widget in cfg.get("widgets", []):
        if widget.get("panel"):
            ld.rounded_rectangle(
                [widget["x"], widget["y"],
                 widget["x"] + widget["w"] - 1, widget["y"] + widget["h"] - 1],
                radius=widget.get("radius", 12),
                fill=rgba(widget.get("panel_color", "#0b1220b3")))
    img = Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")
    draw = ImageDraw.Draw(img)

    rects = {}
    gpu_available = bool((stats.get("gpu") or {}).get("available"))
    for widget in cfg.get("widgets", []):
        wtype = widget.get("type")
        if widget.get("metric") in ("gpu", "gpu_temp", "gpu_mem") and not gpu_available:
            continue
        try:
            if wtype == "ring":
                _draw_ring(img, draw, widget, metric_data(stats, widget.get("metric", "cpu")), rects)
            elif wtype == "bar":
                _draw_bar(img, draw, widget, metric_data(stats, widget.get("metric", "cpu")), rects)
            elif wtype == "spark":
                data = metric_data(stats, widget.get("metric", "cpu"))
                key = widget.get("metric", "cpu")
                data["series"] = (stats.get("history") or {}).get(key) or []
                _draw_spark(img, draw, widget, data, rects)
            elif wtype == "metric":
                _draw_metric(img, draw, widget, metric_data(stats, widget.get("metric", "cpu")), rects)
            elif wtype == "text":
                _draw_text(img, draw, widget, stats, rects)
            elif wtype == "clock":
                _draw_clock(img, draw, widget, stats, rects)
            elif wtype == "services":
                _draw_services(img, draw, widget, rects)
            elif wtype == "host":
                _draw_host(img, draw, widget, stats, rects)
        except Exception:
            # Un widget roto no debe tumbar el panel entero
            rects[widget.get("id", "?")] = [widget.get("x", 0), widget.get("y", 0),
                                            widget.get("w", 0), widget.get("h", 0)]
    return img, rects
