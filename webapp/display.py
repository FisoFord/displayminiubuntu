# SPDX-License-Identifier: GPL-3.0-or-later
"""Hilo que envia los frames al panel USB sin bloquear la web."""

from __future__ import annotations

import os
import queue
import sys
import threading
import time
from pathlib import Path

try:
    from minidisplay import DisplayError, MiniDisplay
except ImportError:  # ejecutando desde el repositorio
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from minidisplay import DisplayError, MiniDisplay


class DisplayWorker(threading.Thread):
    def __init__(self, get_config, logger):
        super().__init__(daemon=True, name="display")
        self.get_config = get_config
        self.log = logger
        self.port = os.environ.get("DISPLAY_PORT", "AUTO")
        self.queue = queue.Queue(maxsize=1)
        self._stop = threading.Event()
        self._lcd = None
        self._brightness = None
        self._status_lock = threading.Lock()
        self._status = {
            "connected": False,
            "port": None,
            "last_push": None,
            "last_error": None,
            "frames": 0,
            "push_ms": None,
        }

    # -- estado -------------------------------------------------------------
    def status(self) -> dict:
        with self._status_lock:
            return dict(self._status)

    def _update(self, **kw):
        with self._status_lock:
            self._status.update(kw)

    # -- cola ---------------------------------------------------------------
    def submit(self, image):
        try:
            self.queue.put_nowait(image)
        except queue.Full:
            try:
                self.queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self.queue.put_nowait(image)
            except queue.Full:
                pass

    # -- conexion -----------------------------------------------------------
    def _ensure(self):
        if self._lcd is not None:
            return True
        try:
            lcd = MiniDisplay(port=self.port, verbose=False)
            lcd.open()
            lcd.hello()
            lcd.set_orientation("portrait")
            self._lcd = lcd
            self._brightness = None
            self._update(connected=True, port=lcd.device, last_error=None)
            self.log.info("Panel conectado en %s", lcd.device)
            return True
        except DisplayError as exc:
            if self._status.get("last_error") != str(exc).splitlines()[0]:
                self.log.warning("Panel no disponible: %s", str(exc).splitlines()[0])
            self._update(connected=False, last_error=str(exc).splitlines()[0])
            return False
        except Exception as exc:  # pragma: no cover
            self._update(connected=False, last_error=str(exc))
            return False

    def _close(self):
        if self._lcd is not None:
            try:
                self._lcd.close()
            except Exception:
                pass
        self._lcd = None
        self._brightness = None
        self._update(connected=False)

    # -- bucle --------------------------------------------------------------
    def run(self):
        while not self._stop.is_set():
            try:
                image = self.queue.get(timeout=0.5)
            except queue.Empty:
                continue

            cfg = self.get_config() or {}
            if not cfg.get("display", {}).get("enabled", True):
                continue
            if not self._ensure():
                self._stop.wait(3)
                continue

            brightness = int(cfg.get("display", {}).get("brightness", 25))
            try:
                if brightness != self._brightness:
                    self._lcd.set_brightness(brightness)
                    self._brightness = brightness
                started = time.perf_counter()
                self._lcd.show(image)
                elapsed = (time.perf_counter() - started) * 1000
                self._update(last_push=time.time(), frames=self._status["frames"] + 1,
                             push_ms=round(elapsed, 1), connected=True, last_error=None)
            except Exception as exc:
                self.log.warning("Fallo al enviar frame: %s", exc)
                self._update(last_error=str(exc)[:200], connected=False)
                self._close()
                self._stop.wait(2)

    def stop(self):
        self._stop.set()
