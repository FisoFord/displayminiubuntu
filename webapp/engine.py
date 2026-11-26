# SPDX-License-Identifier: GPL-3.0-or-later
"""Motor de render: mantiene el frame actual y lo envia al panel."""

from __future__ import annotations

import io
import threading
import time

from render import render_frame


class Engine(threading.Thread):
    def __init__(self, config: dict, backgrounds_dir, collector, display, logger):
        super().__init__(daemon=True, name="engine")
        self._config = config
        self.backgrounds_dir = backgrounds_dir
        self.collector = collector
        self.display = display
        self.log = logger
        self._cond = threading.Condition()
        self._stop = threading.Event()
        self._dirty = True
        self._rev = 0
        self._latest = {
            "png": None,
            "rects": {},
            "stats": {},
            "ts": 0.0,
            "rev": 0,
        }

    # -- configuracion ------------------------------------------------------
    def get_config(self) -> dict:
        with self._cond:
            return self._config

    def set_config(self, config: dict):
        with self._cond:
            self._config = config
            self._rev += 1
            self._dirty = True
            self._cond.notify_all()

    def request_render(self):
        with self._cond:
            self._dirty = True
            self._cond.notify_all()

    # -- frames -------------------------------------------------------------
    def frame_png(self, timeout: float = 5.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._cond:
                if self._latest["png"] is not None:
                    return self._latest["png"]
                self._cond.wait(0.2)
        return None

    def state(self) -> dict:
        with self._cond:
            return {
                "rev": self._latest["rev"],
                "preview_ts": self._latest["ts"],
                "rects": dict(self._latest["rects"]),
                "stats": dict(self._latest["stats"]),
                "display": self.display.status() if self.display else None,
            }

    def latest_image(self):
        with self._cond:
            return self._latest.get("image")

    # -- bucle --------------------------------------------------------------
    def run(self):
        while not self._stop.is_set():
            with self._cond:
                config = self._config
                rev = self._rev
            fps = float(config.get("display", {}).get("fps") or 1)
            interval = 1.0 / max(fps, 0.3)

            started = time.perf_counter()
            try:
                stats = self.collector.snapshot()
                if not stats:
                    stats = self.collector.sample()
                image, rects = render_frame(config, stats, self.backgrounds_dir)
                buffer = io.BytesIO()
                image.save(buffer, format="PNG", compress_level=2)
                png = buffer.getvalue()
                with self._cond:
                    self._latest = {
                        "png": png,
                        "image": image,
                        "rects": rects,
                        "stats": stats,
                        "ts": time.time(),
                        "rev": rev,
                    }
                    self._cond.notify_all()
                if self.display is not None and config.get("display", {}).get("enabled", True):
                    self.display.submit(image)
            except Exception as exc:  # pragma: no cover
                self.log.exception("Error renderizando frame: %s", exc)

            elapsed = time.perf_counter() - started
            remaining = max(0.05, interval - elapsed)
            with self._cond:
                if not self._dirty:
                    self._cond.wait(remaining)
                self._dirty = False

    def stop(self):
        self._stop.set()
        with self._cond:
            self._cond.notify_all()
