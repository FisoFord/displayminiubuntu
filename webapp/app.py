#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Panel web para el mini display: fondos, widgets y servicios del sistema."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import logging
import os
import secrets
import shutil
import signal
import threading
import time
import uuid
from logging.handlers import RotatingFileHandler
from pathlib import Path

from flask import (Flask, Response, jsonify, render_template, request,
                   send_from_directory)
from PIL import Image, ImageOps

import services
from collect import Collector
from config import PRESETS, default_config, normalize
from display import DisplayWorker
from engine import Engine
from render import render_frame

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("WEBAPP_DATA", BASE_DIR / "data")).resolve()
BACKGROUNDS_DIR = DATA_DIR / "backgrounds"
CONFIG_PATH = DATA_DIR / "config.json"
META_PATH = DATA_DIR / "backgrounds.json"
LOG_PATH = DATA_DIR / "webapp.log"
DEFAULTS_DIR = BASE_DIR / "defaults" / "backgrounds"
DEFAULTS_MANIFEST = BASE_DIR / "defaults" / "backgrounds.json"
VERSION = "2.0"
ALLOWED_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}

app = Flask(__name__, static_folder="static", template_folder="templates")
app.config["MAX_CONTENT_LENGTH"] = 40 * 1024 * 1024

_config_lock = threading.Lock()
_meta_lock = threading.Lock()

logger = logging.getLogger("webapp")

# ---------------------------------------------------------------------------
# Estado global (se rellena en main())
# ---------------------------------------------------------------------------

engine: Engine | None = None
display_worker: DisplayWorker | None = None
collector: Collector | None = None


# ---------------------------------------------------------------------------
# Persistencia
# ---------------------------------------------------------------------------

def load_config() -> dict:
    if CONFIG_PATH.is_file():
        try:
            with open(CONFIG_PATH, encoding="utf-8") as fh:
                return normalize(json.load(fh))
        except (OSError, json.JSONDecodeError):
            logger.warning("config.json invalido, se usan valores por defecto")
    config = default_config()
    save_config(config)
    return config


def save_config(config: dict):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_PATH.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(config, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, CONFIG_PATH)


def load_meta() -> list:
    if META_PATH.is_file():
        try:
            with open(META_PATH, encoding="utf-8") as fh:
                data = json.load(fh)
                if isinstance(data, list):
                    return data
        except (OSError, json.JSONDecodeError):
            pass
    return []


def save_meta(items: list):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = META_PATH.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(items, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, META_PATH)


def _sha1(path: Path) -> str:
    digest = hashlib.sha1()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def seed_default_backgrounds() -> list:
    """Copia los fondos incluidos en defaults/ si su contenido no existe ya."""
    if not DEFAULTS_DIR.is_dir():
        return []
    try:
        manifest = json.loads(DEFAULTS_MANIFEST.read_text(encoding="utf-8"))
        if not isinstance(manifest, list):
            manifest = []
    except (OSError, json.JSONDecodeError):
        manifest = []
    if not manifest:
        manifest = [{"file": p.name, "name": p.name}
                    for p in sorted(DEFAULTS_DIR.iterdir()) if p.is_file()]

    BACKGROUNDS_DIR.mkdir(parents=True, exist_ok=True)
    existing = {}
    for path in BACKGROUNDS_DIR.iterdir():
        if path.is_file():
            try:
                existing[_sha1(path)] = path.name
            except OSError:
                continue

    defaults = []
    dirty = False
    with _meta_lock:
        items = load_meta()
        known = {item.get("file") for item in items}
        for entry in manifest:
            if not isinstance(entry, dict):
                continue
            filename = Path(str(entry.get("file", ""))).name
            source = DEFAULTS_DIR / filename
            if not filename or not source.is_file():
                continue
            digest = _sha1(source)
            if digest in existing:
                name = existing[digest]
                if name not in known:
                    items.append({
                        "file": name,
                        "name": entry.get("name") or filename,
                        "size": (BACKGROUNDS_DIR / name).stat().st_size,
                        "added": time.time(),
                    })
                    known.add(name)
                    dirty = True
                defaults.append(name)
                continue

            target = BACKGROUNDS_DIR / filename
            if target.exists():
                target = BACKGROUNDS_DIR / f"{target.stem}-{digest[:6]}{target.suffix}"
            try:
                shutil.copy2(source, target)
            except OSError as exc:
                logger.warning("No se pudo copiar el fondo %s: %s", filename, exc)
                continue
            existing[digest] = target.name
            if target.name not in known:
                items.append({
                    "file": target.name,
                    "name": entry.get("name") or filename,
                    "size": target.stat().st_size,
                    "added": time.time(),
                })
                known.add(target.name)
                dirty = True
            defaults.append(target.name)

        if dirty:
            save_meta(items)
            logger.info("Fondos por defecto incorporados (%s)", len(defaults))
    return defaults


# ---------------------------------------------------------------------------
# Autenticacion opcional
# ---------------------------------------------------------------------------

_AUTH_USER = os.environ.get("WEBAPP_USER", "")
_AUTH_PASS = os.environ.get("WEBAPP_PASSWORD", "")


@app.before_request
def _basic_auth():
    if not _AUTH_USER:
        return None
    auth = request.authorization
    ok_user = auth and secrets.compare_digest(auth.username or "", _AUTH_USER)
    ok_pass = auth and secrets.compare_digest(auth.password or "", _AUTH_PASS)
    if ok_user and ok_pass:
        return None
    return Response("Autenticacion requerida", 401,
                    {"WWW-Authenticate": 'Basic realm="MiniDisplay"'})


@app.after_request
def _no_cache_api(response):
    if request.path.startswith("/api/") or request.path.startswith("/media/"):
        response.headers["Cache-Control"] = "no-store"
    return response


# ---------------------------------------------------------------------------
# Pagina
# ---------------------------------------------------------------------------

@app.get("/")
def index():
    return render_template("index.html", version=VERSION)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@app.get("/api/config")
def api_get_config():
    return jsonify(engine.get_config())


@app.put("/api/config")
def api_put_config():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "JSON invalido"}), 400
    config = normalize(payload)
    with _config_lock:
        save_config(config)
    engine.set_config(config)
    return jsonify(config)


@app.get("/api/presets")
def api_presets():
    return jsonify({key: {"label": value["label"]} for key, value in PRESETS.items()})


@app.post("/api/presets/<name>")
def api_apply_preset(name):
    preset = PRESETS.get(name)
    if not preset:
        return jsonify({"error": "preset desconocido"}), 404
    config = normalize(engine.get_config())
    config["widgets"] = preset["widgets"]()
    config["design"] = name
    with _config_lock:
        save_config(config)
    engine.set_config(config)
    return jsonify(config)


@app.get("/api/presets/<name>/preview.png")
def api_preset_preview(name):
    """Miniatura de un diseno con los datos y el fondo actuales."""
    preset = PRESETS.get(name)
    if not preset:
        return jsonify({"error": "preset desconocido"}), 404
    config = normalize(engine.get_config())
    config["widgets"] = preset["widgets"]()
    config["design"] = name
    stats = engine.state().get("stats") or {}
    if not stats and collector is not None:
        stats = collector.snapshot()
    image, _ = render_frame(config, stats, BACKGROUNDS_DIR)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", compress_level=2)
    return Response(buffer.getvalue(), mimetype="image/png")


# ---------------------------------------------------------------------------
# Frames
# ---------------------------------------------------------------------------

@app.get("/api/preview.png")
def api_preview():
    png = engine.frame_png()
    if png is None:
        return Response(status=503)
    return Response(png, mimetype="image/png")


@app.get("/api/state")
def api_state():
    return jsonify(engine.state())


@app.post("/api/display/push")
def api_push():
    engine.request_render()
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Fondos
# ---------------------------------------------------------------------------

def _public_meta(item: dict) -> dict:
    return {
        "file": item["file"],
        "name": item.get("name", item["file"]),
        "url": f"/media/{item['file']}",
        "size": item.get("size", 0),
    }


@app.get("/api/backgrounds")
def api_backgrounds():
    with _meta_lock:
        items = load_meta()
    return jsonify({"items": [_public_meta(i) for i in items]})


def _store_upload(storage) -> dict:
    raw = storage.read()
    if not raw:
        raise ValueError("archivo vacio")
    if len(raw) > 30 * 1024 * 1024:
        raise ValueError("imagen demasiado grande (max 30 MB)")
    image = Image.open(io.BytesIO(raw))
    image.load()
    image = ImageOps.exif_transpose(image)
    has_alpha = image.mode in ("RGBA", "LA") or (
        image.mode == "P" and "transparency" in image.info)
    image.thumbnail((1920, 1920), Image.LANCZOS)
    BACKGROUNDS_DIR.mkdir(parents=True, exist_ok=True)
    name = uuid.uuid4().hex[:12]
    if has_alpha:
        filename = name + ".png"
        image.convert("RGBA").save(BACKGROUNDS_DIR / filename, "PNG", optimize=True)
    else:
        filename = name + ".jpg"
        image.convert("RGB").save(BACKGROUNDS_DIR / filename, "JPEG",
                                  quality=90, optimize=True)
    return {
        "file": filename,
        "name": Path(storage.filename or "imagen").name[:80] or "imagen",
        "size": (BACKGROUNDS_DIR / filename).stat().st_size,
        "added": time.time(),
    }


@app.post("/api/backgrounds")
def api_upload_backgrounds():
    files = request.files.getlist("files") or request.files.getlist("file")
    if not files:
        return jsonify({"error": "no se recibio ningun archivo"}), 400
    if len(files) > 20:
        return jsonify({"error": "maximo 20 imagenes por subida"}), 400

    stored, errors = [], []
    for storage in files:
        if not storage or not storage.filename:
            continue
        ext = Path(storage.filename).suffix.lower()
        if ext and ext not in ALLOWED_EXT:
            errors.append(f"{storage.filename}: formato no soportado")
            continue
        try:
            item = _store_upload(storage)
        except Exception as exc:
            errors.append(f"{storage.filename}: {exc}")
            continue
        stored.append(item)

    if stored:
        with _meta_lock:
            items = load_meta()
            items.extend(stored)
            save_meta(items)
        config = normalize(engine.get_config())
        config["background"]["images"] = (config["background"]["images"] + [i["file"] for i in stored])[:64]
        with _config_lock:
            save_config(config)
        engine.set_config(config)

    return jsonify({"items": [_public_meta(i) for i in stored], "errors": errors})


@app.delete("/api/backgrounds/<path:filename>")
def api_delete_background(filename):
    safe = Path(filename).name
    if safe != filename:
        return jsonify({"error": "nombre no valido"}), 400
    target = BACKGROUNDS_DIR / safe
    with _meta_lock:
        items = [i for i in load_meta() if i["file"] != safe]
        save_meta(items)
    try:
        target.unlink()
    except OSError:
        pass
    config = normalize(engine.get_config())
    config["background"]["images"] = [i for i in config["background"]["images"] if i != safe]
    with _config_lock:
        save_config(config)
    engine.set_config(config)
    return jsonify({"ok": True})


@app.get("/media/<path:filename>")
def media(filename):
    return send_from_directory(BACKGROUNDS_DIR, filename, max_age=3600)


# ---------------------------------------------------------------------------
# Servicios
# ---------------------------------------------------------------------------

@app.get("/api/services")
def api_services():
    force = request.args.get("force") in ("1", "true")
    return jsonify(services.get_services(force=force))


@app.post("/api/services/action")
def api_service_action():
    payload = request.get_json(silent=True) or {}
    scope = str(payload.get("scope", ""))
    name = str(payload.get("name", ""))
    act = str(payload.get("action", ""))
    if act not in services.ACTIONS:
        return jsonify({"ok": False, "message": "accion no permitida"}), 400
    if not services.actions_allowed():
        return jsonify({
            "ok": False,
            "message": "Sin permiso para ejecutar acciones. Activa sudoers con "
                       "webapp/install.sh --actions y reinicia el servicio.",
        }), 403
    ok, message = services.action(scope, name, act)
    services.get_services(force=True)
    return jsonify({"ok": ok, "message": message})


# ---------------------------------------------------------------------------
# Diagnostico
# ---------------------------------------------------------------------------

@app.get("/api/health")
def api_health():
    return jsonify({
        "ok": True,
        "version": VERSION,
        "host": os.uname().nodename if hasattr(os, "uname") else "",
        "device": display_worker.status() if display_worker else None,
        "actions_allowed": services.actions_allowed(),
        "systemd": services.has_systemd(),
        "docker": services.has_docker(),
        "backgrounds": len(load_meta()),
        "data_dir": str(DATA_DIR),
    })


@app.get("/api/logs")
def api_logs():
    try:
        lines = max(10, min(int(request.args.get("lines", 120)), 1000))
    except ValueError:
        lines = 120
    try:
        with open(LOG_PATH, encoding="utf-8", errors="replace") as fh:
            content = fh.readlines()[-lines:]
    except OSError:
        return jsonify({"lines": []})
    return jsonify({"lines": [line.rstrip() for line in content]})


@app.errorhandler(413)
def too_large(_error):
    return jsonify({"error": "archivo demasiado grande"}), 413


# ---------------------------------------------------------------------------
# Arranque
# ---------------------------------------------------------------------------

def setup_logging():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    file_handler = RotatingFileHandler(LOG_PATH, maxBytes=2_000_000, backupCount=2,
                                       encoding="utf-8")
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)


def main() -> int:
    global engine, display_worker, collector
    global DATA_DIR, BACKGROUNDS_DIR, CONFIG_PATH, META_PATH, LOG_PATH

    parser = argparse.ArgumentParser(description="Panel web del mini display USB")
    parser.add_argument("--host", default=os.environ.get("WEBAPP_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("WEBAPP_PORT", "8080")))
    parser.add_argument("--data-dir", default=str(DATA_DIR))
    parser.add_argument("--no-display", action="store_true",
                        default=os.environ.get("WEBAPP_NO_DISPLAY", "").lower() in ("1", "true", "yes"),
                        help="No enviar frames al panel (solo web/pruebas)")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    DATA_DIR = Path(args.data_dir).resolve()
    BACKGROUNDS_DIR = DATA_DIR / "backgrounds"
    CONFIG_PATH = DATA_DIR / "config.json"
    META_PATH = DATA_DIR / "backgrounds.json"
    LOG_PATH = DATA_DIR / "webapp.log"
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    BACKGROUNDS_DIR.mkdir(parents=True, exist_ok=True)

    setup_logging()
    logger.info("MiniDisplay Web %s", VERSION)
    logger.info("Datos en %s", DATA_DIR)

    default_images = seed_default_backgrounds()
    config = load_config()
    if default_images and not config["background"]["images"]:
        config["background"]["images"] = default_images
        save_config(config)
    collector = Collector()
    collector.start()

    engine = Engine(config, BACKGROUNDS_DIR, collector, None, logger)
    if not args.no_display:
        display_worker = DisplayWorker(engine.get_config, logger)
    engine.display = display_worker
    engine.start()
    if display_worker is not None:
        display_worker.start()

    logger.info("Escuchando en http://%s:%s", args.host, args.port)

    try:
        from waitress import create_server
        server = create_server(app, host=args.host, port=args.port, threads=8)

        def _shutdown(*_args):
            logger.info("Parando servidor...")
            threading.Thread(target=server.close, daemon=True).start()

        signal.signal(signal.SIGTERM, _shutdown)
        signal.signal(signal.SIGINT, _shutdown)
        server.run()
    except ImportError:
        logger.warning("waitress no instalado: usando el servidor de desarrollo")
        try:
            app.run(host=args.host, port=args.port, threaded=True,
                    debug=args.debug, use_reloader=False)
        except KeyboardInterrupt:
            pass
    finally:
        engine.stop()
        if display_worker is not None:
            display_worker.stop()
        collector.stop()
        logger.info("Detenido")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
