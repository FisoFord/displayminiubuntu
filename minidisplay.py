#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
minidisplay.py - Driver minimo y autonomo para el mini display USB
"Turing Smart Screen Rev A" (3.5", 320x480, VID 1a86 / PID 5722,
numero de serie USB35INCHIPSV2).

Funciona en Linux, Windows y macOS. Solo necesita:
    pip install pyserial pillow

Ejemplos:
    python3 minidisplay.py --info
    python3 minidisplay.py --test
    python3 minidisplay.py --image foto.png --orientation landscape
    python3 minidisplay.py --clear
    python3 minidisplay.py --brightness 15
    python3 minidisplay.py --off
    python3 minidisplay.py --on
"""

import argparse
import datetime as _dt
import sys
import time
from typing import Optional

try:
    import serial
    from serial.tools import list_ports
except ImportError:  # pragma: no cover
    sys.exit("Falta pyserial. Instala con: pip install pyserial pillow")

# ---------------------------------------------------------------------------
# Protocolo (Turing Smart Screen revision A)
# ---------------------------------------------------------------------------

VID = 0x1A86
PID = 0x5722
SERIAL_NUMBER = "USB35INCHIPSV2"
BAUD = 115200


class Command:
    HELLO = 69
    RESET = 101
    CLEAR = 102
    TO_BLACK = 103
    SCREEN_OFF = 108
    SCREEN_ON = 109
    SET_BRIGHTNESS = 110
    SET_ORIENTATION = 121
    DISPLAY_BITMAP = 197


# Orientaciones tal y como las espera el firmware
ORIENTATIONS = {
    "portrait": 0,
    "reverse-portrait": 1,
    "landscape": 2,
    "reverse-landscape": 3,
}


class DisplayError(RuntimeError):
    """El display no esta disponible (no conectado, ocupado o sin permisos)."""


def find_device() -> Optional[str]:
    """Devuelve el puerto serie del display o None si no esta conectado."""
    for port in list_ports.comports():
        if port.serial_number == SERIAL_NUMBER:
            return port.device
        if port.vid == VID and port.pid == PID:
            return port.device
    return None


def _pack_point(x: int, y: int, ex: int, ey: int, cmd: int) -> bytes:
    """Empaqueta una orden de 6 bytes con el formato del firmware."""
    return bytes((
        (x >> 2) & 0xFF,
        (((x & 3) << 6) + (y >> 4)) & 0xFF,
        (((y & 15) << 4) + (ex >> 6)) & 0xFF,
        (((ex & 63) << 2) + (ey >> 8)) & 0xFF,
        ey & 0xFF,
        cmd,
    ))


def _to_rgb565_le(image) -> bytes:
    """Convierte una imagen PIL a RGB565 little-endian (formato del panel)."""
    image = image.convert("RGB")
    try:
        import numpy as np
        rgb = np.asarray(image).astype(np.uint16)
        value = ((rgb[:, :, 0] >> 3) << 11) | ((rgb[:, :, 1] >> 2) << 5) | (rgb[:, :, 2] >> 3)
        return value.astype("<u2").tobytes()
    except ImportError:
        data = image.tobytes()
        out = bytearray((len(data) // 3) * 2)
        j = 0
        for i in range(0, len(data), 3):
            r, g, b = data[i], data[i + 1], data[i + 2]
            v = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
            out[j] = v & 0xFF
            out[j + 1] = (v >> 8) & 0xFF
            j += 2
        return bytes(out)


class MiniDisplay:
    """Driver del panel. Ancho/alto siempre en orientacion vertical (320x480)."""

    def __init__(self, port: str = "AUTO", width: int = 320, height: int = 480,
                 verbose: bool = True):
        self.port = port
        self.device: Optional[str] = None
        self.display_width = width
        self.display_height = height
        self.orientation = 0
        self.serial: Optional[serial.Serial] = None
        self.verbose = verbose
        self.sub_revision = "turing-3.5"

    # -- utilidades ---------------------------------------------------------
    def log(self, msg: str):
        if self.verbose:
            print(msg, file=sys.stderr)

    def _write(self, data: bytes):
        assert self.serial is not None
        self.serial.write(data)

    # -- ciclo de vida ------------------------------------------------------
    def open(self):
        last_error = ""
        for attempt in range(1, 6):
            # Se resuelve en cada intento: tras un reset el puerto puede cambiar
            port = self.port
            if port.upper() == "AUTO":
                port = find_device()
                if not port:
                    last_error = "no encuentro el display conectado"
                    self.log(f"{last_error}; reintento {attempt}/5")
                    time.sleep(1)
                    continue
            try:
                # rtscts=True igual que el software de referencia; si el adaptador
                # no soporta flow control, reintentamos sin el.
                try:
                    self.serial = serial.Serial(port, BAUD, timeout=1, rtscts=True)
                except (ValueError, serial.SerialException):
                    self.serial = serial.Serial(port, BAUD, timeout=1)
                self.device = port
                self.log(f"Conectado a {port}")
                return self
            except serial.SerialException as exc:
                last_error = str(exc)
                self.log(f"No se pudo abrir {port} ({exc}); reintento {attempt}/5")
                time.sleep(1)

        raise DisplayError(
            f"No se pudo abrir el display: {last_error}\n"
            "  Linux : comprueba 'ls /dev/ttyACM*' y que tu usuario este en el grupo dialout.\n"
            "  Windows: comprueba que aparece como 'USB Serial Device (COMx)'.\n"
            "  Usa --port para indicarlo a mano."
        )

    def close(self):
        if self.serial is not None and self.serial.is_open:
            self.serial.close()

    def __enter__(self):
        return self.open()

    def __exit__(self, *exc):
        self.close()

    # -- comandos -----------------------------------------------------------
    def hello(self) -> str:
        """Pregunta al panel su sub-revision (los Turing 3.5 no responden)."""
        assert self.serial is not None
        self.serial.timeout = 0.3
        self._write(bytes([Command.HELLO] * 6))
        answer = self.serial.read(6)
        self.serial.reset_input_buffer()
        self.serial.timeout = 1
        if answer == bytearray([1] * 6):
            self.sub_revision = "usbmonitor-3.5"
        elif answer == bytearray([2] * 6):
            self.sub_revision = "usbmonitor-5"
        elif answer == bytearray([3] * 6):
            self.sub_revision = "usbmonitor-7"
        else:
            self.sub_revision = "turing-3.5"
        return self.sub_revision

    def _command(self, cmd: int, x: int = 0, y: int = 0, ex: int = 0, ey: int = 0):
        self._write(_pack_point(x, y, ex, ey, cmd))

    def reset(self, wait: float = 5.0):
        self.log("Reset del panel (el puerto puede desaparecer unos segundos)...")
        self._command(Command.RESET)
        self.close()
        time.sleep(wait)
        self.open()
        self.hello()

    def set_brightness(self, level: int):
        """0 = apagado, 100 = maximo. Ojo: el panel se calienta; usa <= 50."""
        level = max(0, min(100, int(level)))
        value = int(255 - (level / 100) * 255)
        self._command(Command.SET_BRIGHTNESS, value)

    def set_orientation(self, name: str):
        if name not in ORIENTATIONS:
            raise ValueError(f"Orientacion desconocida: {name}")
        value = ORIENTATIONS[name]
        self.orientation = value
        width, height = self.get_size()
        buf = bytearray(16)
        buf[0:5] = _pack_point(0, 0, 0, 0, 0)[0:5]
        buf[5] = Command.SET_ORIENTATION
        buf[6] = (value + 100) & 0xFF
        buf[7] = (width >> 8) & 0xFF
        buf[8] = width & 0xFF
        buf[9] = (height >> 8) & 0xFF
        buf[10] = height & 0xFF
        self._write(bytes(buf))

    def clear(self):
        # El firmware solo limpia bien en vertical
        current = self.orientation
        self.set_orientation("portrait")
        self._command(Command.CLEAR)
        self.set_orientation_internal(current)

    def set_orientation_internal(self, value: int):
        name = [k for k, v in ORIENTATIONS.items() if v == value][0]
        self.set_orientation(name)

    def screen_off(self):
        self._command(Command.SCREEN_OFF)

    def screen_on(self):
        self._command(Command.SCREEN_ON)

    def get_size(self):
        if self.orientation in (0, 1):
            return self.display_width, self.display_height
        return self.display_height, self.display_width

    # -- imagen -------------------------------------------------------------
    def show(self, image, x: int = 0, y: int = 0):
        """Muestra una imagen PIL a partir de (x, y)."""
        from PIL import Image

        width, height = self.get_size()
        if image.mode != "RGB":
            image = image.convert("RGB")

        image_width, image_height = image.size
        if x + image_width > width:
            image_width = width - x
        if y + image_height > height:
            image_height = height - y
        if (image_width, image_height) != image.size:
            image = image.crop((0, 0, image_width, image_height))

        assert image_width > 0 and image_height > 0, "Imagen fuera de la pantalla"

        x1, y1 = x + image_width - 1, y + image_height - 1
        data = _to_rgb565_le(image)
        self._command(Command.DISPLAY_BITMAP, x, y, x1, y1)

        # El panel espera los bytes en bloques del ancho de pantalla * 8
        chunk_size = width * 8
        for i in range(0, len(data), chunk_size):
            self._write(data[i:i + chunk_size])


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _fit_image(path: str, size):
    from PIL import Image
    image = Image.open(path)
    image.thumbnail(size, Image.LANCZOS)
    canvas = Image.new("RGB", size, (0, 0, 0))
    canvas.paste(image, ((size[0] - image.size[0]) // 2,
                         (size[1] - image.size[1]) // 2))
    return canvas


def _test_pattern(size):
    from PIL import Image, ImageDraw, ImageFont
    width, height = size
    image = Image.new("RGB", size, (8, 10, 20))
    draw = ImageDraw.Draw(image)

    # Barras de color
    bars = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (0, 255, 255),
            (255, 0, 255), (255, 255, 0), (255, 255, 255), (0, 0, 0)]
    bar_w = width // len(bars)
    for i, color in enumerate(bars):
        draw.rectangle([i * bar_w, 0, (i + 1) * bar_w - 1, 40], fill=color)

    # Degradado
    for x in range(width):
        shade = int(255 * x / max(1, width - 1))
        draw.line([(x, 41), (x, 90)], fill=(shade, shade, shade))

    # Marco
    draw.rectangle([1, 1, width - 2, height - 2], outline=(0, 200, 255), width=2)

    def font(px):
        for name in ("DejaVuSans-Bold.ttf", "arialbd.ttf", "Arial Bold.ttf"):
            try:
                return ImageFont.truetype(name, px)
            except OSError:
                continue
        return ImageFont.load_default()

    draw.text((width // 2, 130), "MINI DISPLAY", font=font(28),
              fill=(255, 255, 255), anchor="mm")
    draw.text((width // 2, 168), "Turing Rev A  |  320x480", font=font(14),
              fill=(0, 220, 255), anchor="mm")
    draw.text((width // 2, 210), _dt.datetime.now().strftime("%Y-%m-%d  %H:%M:%S"),
              font=font(16), fill=(200, 200, 200), anchor="mm")

    # Esquinas para comprobar que no esta invertida
    for (cx, cy, anchor, color) in (
            (4, 230, "la", (255, 60, 60)),
            (width - 4, 230, "ra", (60, 255, 60)),
            (4, height - 4, "ld", (255, 255, 60)),
            (width - 4, height - 4, "rd", (60, 60, 255))):
        draw.text((cx, cy), "ABC", font=font(16), fill=color, anchor=anchor)

    draw.text((width // 2, height - 24), "si ves esto, Linux ya controla el panel",
              font=font(13), fill=(0, 255, 150), anchor="mm")
    return image


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Driver minimo para Turing Smart Screen Rev A (3.5\" 320x480)")
    parser.add_argument("--port", default="AUTO",
                        help="Puerto serie (AUTO, COM3, /dev/ttyACM0...)")
    parser.add_argument("--orientation", default="portrait", choices=ORIENTATIONS.keys())
    parser.add_argument("--brightness", type=int, default=None,
                        help="Brillo 0-100 (recomendado <= 50)")
    parser.add_argument("--image", help="Imagen a mostrar (se ajusta a la pantalla)")
    parser.add_argument("--test", action="store_true", help="Patron de prueba")
    parser.add_argument("--clear", action="store_true", help="Limpiar pantalla")
    parser.add_argument("--off", action="store_true", help="Apagar la pantalla")
    parser.add_argument("--on", action="store_true", help="Encender la pantalla")
    parser.add_argument("--reset", action="store_true", help="Reset del panel (tarda ~5 s)")
    parser.add_argument("--info", action="store_true", help="Mostrar informacion del panel")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    if not any((args.image, args.test, args.clear, args.off, args.on, args.reset, args.info)):
        parser.print_help()
        return 0

    try:
        with MiniDisplay(port=args.port, verbose=args.verbose) as lcd:
            sub = lcd.hello()
            if args.info:
                print(f"Puerto    : {lcd.device}")
                print(f"Modelo    : Turing Smart Screen Rev A (o clon)")
                print(f"Sub-rev.  : {sub}")
                print(f"Resolucion: {lcd.display_width}x{lcd.display_height} (vertical)")
                return 0

            if args.reset:
                lcd.reset()
            if args.brightness is not None:
                lcd.set_brightness(args.brightness)
            lcd.set_orientation(args.orientation)

            if args.off:
                lcd.screen_off()
            if args.on:
                lcd.screen_on()
            if args.clear:
                lcd.clear()
            if args.test:
                lcd.show(_test_pattern(lcd.get_size()))
            if args.image:
                lcd.show(_fit_image(args.image, lcd.get_size()))
    except DisplayError as exc:
        print(f"\n[error] {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
