#!/usr/bin/env bash
#
# Instalador para Linux del mini display USB "Turing Smart Screen Rev A"
# (VID 1a86:5722, serie USB35INCHIPSV2, 320x480).  Equivale al UsbMonitor.exe /
# AIDA64 de Windows, pero usando el proyecto open-source
# turing-smart-screen-python.
#
# Uso:
#   chmod +x install.sh
#   ./install.sh                 # instala y deja el servicio activo
#   ./install.sh --no-service    # solo instala, sin systemd
#   ./install.sh --keep-brltty   # no desactiva brltty (lectores Braille)
#   INSTALL_DIR=/opt/mi-screen ./install.sh
#   REF=main ./install.sh        # ultima version en vez de la 3.10.0
#
set -euo pipefail

INSTALL_DIR="${INSTALL_DIR:-/opt/turing-smart-screen}"
REPO_URL="${REPO_URL:-https://github.com/mathoudebine/turing-smart-screen-python.git}"
REF="${REF:-3.10.0}"
KEEP_BRLTTY=0
NO_SERVICE=0
FRESH=0

# Necesario para que los valores sobrevivan al relanzado con sudo
export INSTALL_DIR REPO_URL REF

log()  { printf '\033[1;32m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[!]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[x]\033[0m %s\n' "$*" >&2; exit 1; }

usage() {
    cat <<'EOF'
Uso: ./install.sh [opciones]

  --no-service    Instala pero no crea ni arranca el servicio systemd
  --keep-brltty   No desactiva brltty (lectores Braille)
  -h, --help      Muestra esta ayuda

Variables de entorno:
  INSTALL_DIR   Directorio de instalacion (por defecto /opt/turing-smart-screen)
  REF           Rama o etiqueta del proyecto (por defecto 3.10.0; "main" = ultima)
  REPO_URL      Repositorio git alternativo
EOF
}

for arg in "$@"; do
    case "$arg" in
        --keep-brltty) KEEP_BRLTTY=1 ;;
        --no-service)  NO_SERVICE=1 ;;
        -h|--help)     usage; exit 0 ;;
        *)             die "Opcion desconocida: $arg (usa --help)" ;;
    esac
done

# ---------------------------------------------------------------------------
# 1. Permisos y usuario
# ---------------------------------------------------------------------------
if [ "$(id -u)" -ne 0 ]; then
    log "Se necesitan permisos de root: relanzando con sudo..."
    exec sudo -E bash "$0" "$@"
fi

RUN_USER="${SUDO_USER:-}"
if [ -z "$RUN_USER" ] || [ "$RUN_USER" = "root" ]; then
    RUN_USER="${RUN_USER_OVERRIDE:-$(logname 2>/dev/null || true)}"
fi
[ -n "$RUN_USER" ] && [ "$RUN_USER" != "root" ] \
    || die "No puedo determinar tu usuario. Ejecuta: sudo RUN_USER_OVERRIDE=tuusuario ./install.sh"

[ "$(uname -s)" = "Linux" ] || die "Este instalador es solo para Linux."

log "Usuario: $RUN_USER   Directorio: $INSTALL_DIR"

# ---------------------------------------------------------------------------
# 2. Dependencias del sistema
# ---------------------------------------------------------------------------
log "Instalando dependencias del sistema..."
if command -v apt-get >/dev/null 2>&1; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y --no-install-recommends \
        python3 python3-venv python3-pip python3-tk git ca-certificates
elif command -v dnf >/dev/null 2>&1; then
    dnf install -y python3 python3-pip python3-tkinter git
elif command -v pacman >/dev/null 2>&1; then
    pacman -Sy --noconfirm python python-pip tk git
elif command -v zypper >/dev/null 2>&1; then
    zypper --non-interactive install python3 python3-pip python3-tk git
else
    warn "Gestor de paquetes no reconocido. Asegurate de tener: python3 >= 3.9, venv, pip, tk y git."
fi

PY=python3
command -v $PY >/dev/null 2>&1 || die "No encuentro python3."
$PY - <<'EOF' || die "Necesitas Python 3.9 o superior."
import sys
raise SystemExit(0 if sys.version_info >= (3, 9) else 1)
EOF

# ---------------------------------------------------------------------------
# 3. Codigo del proyecto + entorno virtual
# ---------------------------------------------------------------------------
if [ -d "$INSTALL_DIR/.git" ]; then
    log "Actualizando codigo existente en $INSTALL_DIR..."
    git -C "$INSTALL_DIR" fetch --depth 1 origin "$REF"
    git -C "$INSTALL_DIR" checkout -q FETCH_HEAD
elif [ -e "$INSTALL_DIR" ] && [ -n "$(ls -A "$INSTALL_DIR" 2>/dev/null)" ]; then
    die "$INSTALL_DIR ya existe y no es un repositorio git. Muevelo o usa INSTALL_DIR=..."
else
    log "Descargando turing-smart-screen-python (~150 MB con temas)..."
    mkdir -p "$(dirname "$INSTALL_DIR")"
    git clone --depth 1 --branch "$REF" "$REPO_URL" "$INSTALL_DIR"
    FRESH=1
fi

log "Creando entorno virtual e instalando dependencias Python..."
$PY -m venv "$INSTALL_DIR/.venv"
"$INSTALL_DIR/.venv/bin/python" -m pip install --quiet --upgrade pip wheel
"$INSTALL_DIR/.venv/bin/python" -m pip install --quiet -r "$INSTALL_DIR/requirements.txt"

# ---------------------------------------------------------------------------
# 4. Configuracion por defecto (solo en instalacion nueva)
# ---------------------------------------------------------------------------
if [ "$FRESH" -eq 1 ] && [ -f "$INSTALL_DIR/config.yaml" ]; then
    log "Aplicando configuracion para la revision A..."
    "$INSTALL_DIR/.venv/bin/python" - "$INSTALL_DIR/config.yaml" <<'EOF'
import sys
from ruamel.yaml import YAML

path = sys.argv[1]
yaml = YAML()
yaml.preserve_quotes = True
with open(path, encoding="utf-8") as f:
    cfg = yaml.load(f)

cfg["config"]["COM_PORT"] = "AUTO"
cfg["config"]["THEME"] = "3.5inchTheme2"
cfg["display"]["REVISION"] = "A"
cfg["display"]["BRIGHTNESS"] = 20
# En la revision A el reset puede hacer desaparecer el puerto al arrancar
cfg["display"]["RESET_ON_STARTUP"] = False

with open(path, "w", encoding="utf-8") as f:
    yaml.dump(cfg, f)
EOF
fi

# El programa escribe log.log en su directorio: debe poder hacerlo el usuario
# del servicio, no solo root.
RUN_GROUP="$(id -gn "$RUN_USER")"
chown -R "$RUN_USER":"$RUN_GROUP" "$INSTALL_DIR"

# ---------------------------------------------------------------------------
# 5. Reglas udev: acceso sin root + nombre estable /dev/turing-screen
# ---------------------------------------------------------------------------
log "Instalando regla udev..."
# Debian/Ubuntu/Fedora usan dialout; Arch/Manjaro usan uucp.
if getent group dialout >/dev/null 2>&1; then
    TTY_GROUP=dialout
elif getent group uucp >/dev/null 2>&1; then
    TTY_GROUP=uucp
else
    TTY_GROUP="$(id -gn "$RUN_USER")"
fi

RULES_DIR=/etc/udev/rules.d
mkdir -p "$RULES_DIR"
cat > "$RULES_DIR/99-turing-smart-screen.rules" <<EOF
# Turing Smart Screen / UsbPCMonitor 3.5" (CH340 CDC-ACM, 1a86:5722)
# Permite abrir el puerto sin root y crea /dev/turing-screen
SUBSYSTEM=="tty", ATTRS{idVendor}=="1a86", ATTRS{idProduct}=="5722", \\
    SYMLINK+="turing-screen", GROUP="$TTY_GROUP", MODE="0660", TAG+="uaccess"
EOF
udevadm control --reload-rules || true
udevadm trigger --subsystem-match=tty || true

usermod -aG "$TTY_GROUP" "$RUN_USER" || true
log "Añadido $RUN_USER al grupo $TTY_GROUP (hace falta reiniciar sesion)."

# ---------------------------------------------------------------------------
# 6. brltty: se queda con los chips CH340 y bloquea el display
# ---------------------------------------------------------------------------
if [ "$KEEP_BRLTTY" -eq 0 ] && \
   { [ -f /usr/lib/udev/rules.d/85-brltty.rules ] || [ -f /lib/udev/rules.d/85-brltty.rules ]; }; then
    warn "brltty detectado: se queda con los chips CH340 y el display no funcionaria."
    warn "Desactivando sus servicios (reversible, ver final del script)."
    # Ubuntu moderno usa brltty-udev.service; Debian/otros usan brltty.service
    # y el template brltty@.service en versiones antiguas.
    for unit in brltty-udev.service brltty.service brltty@.service; do
        if systemctl cat "$unit" >/dev/null 2>&1; then
            systemctl disable --now "$unit" >/dev/null 2>&1 || true
            systemctl mask "$unit" >/dev/null 2>&1 || true
        fi
    done
    pkill -x brltty >/dev/null 2>&1 || true
    udevadm control --reload-rules || true
fi

# ---------------------------------------------------------------------------
# 7. Servicio systemd
# ---------------------------------------------------------------------------
if [ "$NO_SERVICE" -eq 0 ]; then
    log "Creando servicio systemd..."
    cat > /etc/systemd/system/turing-smart-screen.service <<EOF
[Unit]
Description=Turing Smart Screen system monitor
After=network-online.target
Wants=network-online.target
# Si la pantalla tarda en enumerar al arrancar, reintenta sin limite
StartLimitIntervalSec=0

[Service]
Type=simple
User=$RUN_USER
WorkingDirectory=$INSTALL_DIR
Environment=PYTHONUNBUFFERED=1
# Permite el sensor de ping de algunos temas sin ejecutar como root
AmbientCapabilities=CAP_NET_RAW
CapabilityBoundingSet=CAP_NET_RAW
ExecStart=$INSTALL_DIR/.venv/bin/python $INSTALL_DIR/main.py
# "always" y no "on-failure": el programa sale con codigo 0 si no
# encuentra el puerto al arrancar y queremos que lo reintente.
Restart=always
RestartSec=10
TimeoutStopSec=15

[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload
    systemctl enable --now turing-smart-screen.service
    log "Servicio activo. Estado: systemctl status turing-smart-screen"
else
    warn "Servicio no instalado (--no-service). Arranca a mano: cd $INSTALL_DIR && .venv/bin/python main.py"
fi

# ---------------------------------------------------------------------------
# 8. Resumen
# ---------------------------------------------------------------------------
cat <<EOF

Instalacion terminada.

  Codigo    : $INSTALL_DIR
  Log       : $INSTALL_DIR/log.log
  Puerto    : /dev/turing-screen  (o /dev/ttyACM0)
  Config    : $INSTALL_DIR/config.yaml
  Temas     : $INSTALL_DIR/res/themes

Comandos utiles:
  systemctl status turing-smart-screen     # estado
  systemctl restart turing-smart-screen    # reiniciar
  journalctl -u turing-smart-screen -f     # logs en vivo
  cd $INSTALL_DIR && .venv/bin/python configure.py   # asistente (necesita entorno grafico)

IMPORTANTE: si acabas de entrar en el grupo $TTY_GROUP, cierra sesion y vuelve
a entrar (o ejecuta: newgrp $TTY_GROUP) para poder abrir el puerto sin sudo.

Brillo: el panel de 3.5" se calienta. Manten BRIGHTNESS <= 50.

Si desactivamos brltty y lo necesitas para un lector Braille:
  sudo systemctl unmask brltty-udev.service brltty.service
  sudo systemctl enable --now brltty-udev.service
EOF
