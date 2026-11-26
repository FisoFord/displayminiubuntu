#!/usr/bin/env bash
#
# Instalador del panel web (editor de fondos/widgets + servicios) para el
# mini display Turing Smart Screen Rev A. Linux con systemd.
#
# Uso:
#   chmod +x install.sh
#   sudo ./install.sh                 # instala y arranca en el puerto 8080
#   sudo ./install.sh --actions       # permite start/stop/restart desde la web
#   sudo ./install.sh --port 9000
#   sudo ./install.sh --keep-monitor  # no detiene turing-smart-screen
#
set -euo pipefail

INSTALL_DIR="${INSTALL_DIR:-/opt/minidisplay-web}"
DATA_DIR="${DATA_DIR:-/var/lib/minidisplay-web}"
PORT="${PORT:-8080}"
HOST="${HOST:-0.0.0.0}"
ALLOW_ACTIONS=0
KEEP_MONITOR=0

log()  { printf '\033[1;32m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[!]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[x]\033[0m %s\n' "$*" >&2; exit 1; }

usage() {
    cat <<'EOF'
Uso: ./install.sh [opciones]

  --port N        Puerto HTTP (por defecto 8080)
  --data-dir DIR  Datos: imagenes, config y logs (por defecto /var/lib/minidisplay-web)
  --actions       Permite start/stop/restart de servicios desde la web (sudoers)
  --keep-monitor  No detiene el servicio turing-smart-screen si esta activo
  -h, --help      Muestra esta ayuda
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --port)         PORT="${2:?falta el numero de puerto}"; shift 2 ;;
        --data-dir)     DATA_DIR="${2:?falta el directorio}"; shift 2 ;;
        --actions)      ALLOW_ACTIONS=1; shift ;;
        --keep-monitor) KEEP_MONITOR=1; shift ;;
        -h|--help)      usage; exit 0 ;;
        *)              die "Opcion desconocida: $1 (usa --help)" ;;
    esac
done

export INSTALL_DIR DATA_DIR PORT HOST

if [ "$(id -u)" -ne 0 ]; then
    log "Se necesitan permisos de root: relanzando con sudo..."
    exec sudo -E bash "$0" "$@"
fi

RUN_USER="${SUDO_USER:-}"
if [ -z "$RUN_USER" ] || [ "$RUN_USER" = "root" ]; then
    RUN_USER="${RUN_USER_OVERRIDE:-$(logname 2>/dev/null || true)}"
fi
[ -n "$RUN_USER" ] && [ "$RUN_USER" != "root" ] \
    || die "No puedo determinar tu usuario. Usa: sudo RUN_USER_OVERRIDE=tuusuario ./install.sh"

[ "$(uname -s)" = "Linux" ] || die "Este instalador es solo para Linux."

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DRIVER="$SRC_DIR/../minidisplay.py"
[ -f "$DRIVER" ] || DRIVER="$SRC_DIR/minidisplay.py"
[ -f "$DRIVER" ] || die "No encuentro minidisplay.py junto al instalador."

log "Usuario: $RUN_USER"
log "Codigo : $INSTALL_DIR"
log "Datos  : $DATA_DIR"
log "Puerto : $PORT"

# ---------------------------------------------------------------------------
# Dependencias
# ---------------------------------------------------------------------------
log "Instalando dependencias del sistema..."
if command -v apt-get >/dev/null 2>&1; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y --no-install-recommends python3 python3-venv python3-pip
elif command -v dnf >/dev/null 2>&1; then
    dnf install -y python3 python3-pip
elif command -v pacman >/dev/null 2>&1; then
    pacman -Sy --noconfirm python python-pip
elif command -v zypper >/dev/null 2>&1; then
    zypper --non-interactive install python3 python3-pip
else
    warn "Gestor de paquetes no reconocido: asegurate de tener python3 >= 3.9 y venv."
fi

# ---------------------------------------------------------------------------
# Codigo
# ---------------------------------------------------------------------------
log "Copiando aplicacion..."
mkdir -p "$INSTALL_DIR/templates" "$INSTALL_DIR/static"
FILES=(app.py config.py collect.py render.py services.py engine.py display.py
       requirements.txt)
for file in "${FILES[@]}"; do
    [ -f "$SRC_DIR/$file" ] || die "Falta $file en $SRC_DIR"
    install -m 644 "$SRC_DIR/$file" "$INSTALL_DIR/$file"
done
install -m 644 "$DRIVER" "$INSTALL_DIR/minidisplay.py"
install -m 644 "$SRC_DIR/templates/index.html" "$INSTALL_DIR/templates/index.html"
install -m 644 "$SRC_DIR/static/app.js" "$INSTALL_DIR/static/app.js"
install -m 644 "$SRC_DIR/static/i18n.js" "$INSTALL_DIR/static/i18n.js"
install -m 644 "$SRC_DIR/static/style.css" "$INSTALL_DIR/static/style.css"

if [ -d "$SRC_DIR/defaults" ]; then
    mkdir -p "$INSTALL_DIR/defaults"
    cp -r "$SRC_DIR/defaults/." "$INSTALL_DIR/defaults/"
fi

log "Creando entorno virtual..."
python3 -m venv "$INSTALL_DIR/.venv"
"$INSTALL_DIR/.venv/bin/python" -m pip install --quiet --upgrade pip wheel
"$INSTALL_DIR/.venv/bin/python" -m pip install --quiet -r "$INSTALL_DIR/requirements.txt"

RUN_GROUP="$(id -gn "$RUN_USER")"
mkdir -p "$DATA_DIR/backgrounds"
chown -R "$RUN_USER":"$RUN_GROUP" "$INSTALL_DIR" "$DATA_DIR"

# ---------------------------------------------------------------------------
# Acceso al panel USB (udev + grupo)
# ---------------------------------------------------------------------------
if getent group dialout >/dev/null 2>&1; then TTY_GROUP=dialout
elif getent group uucp >/dev/null 2>&1; then TTY_GROUP=uucp
else TTY_GROUP="$(id -gn "$RUN_USER")"; fi

RULES=/etc/udev/rules.d/99-turing-smart-screen.rules
if [ ! -f "$RULES" ]; then
    log "Instalando regla udev para el panel..."
    cat > "$RULES" <<EOF
# Turing Smart Screen / UsbPCMonitor 3.5" (CH340 CDC-ACM, 1a86:5722)
SUBSYSTEM=="tty", ATTRS{idVendor}=="1a86", ATTRS{idProduct}=="5722", \\
    SYMLINK+="turing-screen", GROUP="$TTY_GROUP", MODE="0660", TAG+="uaccess"
EOF
    udevadm control --reload-rules || true
    udevadm trigger --subsystem-match=tty || true
fi
usermod -aG "$TTY_GROUP" "$RUN_USER" || true

# ---------------------------------------------------------------------------
# Un solo dueno del puerto serie
# ---------------------------------------------------------------------------
if [ "$KEEP_MONITOR" -eq 0 ] && systemctl cat turing-smart-screen.service >/dev/null 2>&1; then
    if systemctl is-active --quiet turing-smart-screen.service 2>/dev/null; then
        warn "turing-smart-screen esta activo y usa el mismo puerto. Deteniendolo."
        systemctl disable --now turing-smart-screen.service || true
    fi
fi

# ---------------------------------------------------------------------------
# Variables de entorno
# ---------------------------------------------------------------------------
cat > /etc/default/minidisplay-web <<EOF
# Panel web MiniDisplay
WEBAPP_HOST=$HOST
WEBAPP_PORT=$PORT
WEBAPP_DATA=$DATA_DIR
# Autenticacion basica opcional:
#WEBAPP_USER=admin
#WEBAPP_PASSWORD=cambiar-esta-clave
EOF
chmod 640 /etc/default/minidisplay-web
chown root:root /etc/default/minidisplay-web

# ---------------------------------------------------------------------------
# Permisos opcionales para acciones
# ---------------------------------------------------------------------------
if [ "$ALLOW_ACTIONS" -eq 1 ]; then
    SYSTEMCTL="$(command -v systemctl || echo /usr/bin/systemctl)"
    DOCKER="$(command -v docker || true)"
    SUDOERS=/etc/sudoers.d/minidisplay-web
    COMMANDS=()
    for act in start stop restart enable disable; do
        COMMANDS+=("$SYSTEMCTL $act *")
    done
    if [ -n "$DOCKER" ]; then
        for act in start stop restart; do
            COMMANDS+=("$DOCKER $act *")
        done
    fi
    {
        echo "# Acciones del panel web MiniDisplay"
        printf '%s ALL=(root) NOPASSWD: ' "$RUN_USER"
        first=1
        for cmd in "${COMMANDS[@]}"; do
            if [ "$first" -eq 1 ]; then printf '%s' "$cmd"; first=0
            else printf ', %s' "$cmd"; fi
        done
        echo
    } > "$SUDOERS"
    chmod 440 "$SUDOERS"
    if ! visudo -cf "$SUDOERS" >/dev/null 2>&1; then
        rm -f "$SUDOERS"
        warn "No se pudo validar sudoers; las acciones quedaran deshabilitadas."
    else
        log "Acciones habilitadas para $RUN_USER (sudoers)."
    fi
fi

# ---------------------------------------------------------------------------
# Servicio systemd
# ---------------------------------------------------------------------------
log "Creando servicio systemd..."
cat > /etc/systemd/system/minidisplay-web.service <<EOF
[Unit]
Description=MiniDisplay Web panel
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=0

[Service]
Type=simple
User=$RUN_USER
WorkingDirectory=$INSTALL_DIR
EnvironmentFile=-/etc/default/minidisplay-web
Environment=PYTHONUNBUFFERED=1
ExecStart=$INSTALL_DIR/.venv/bin/python $INSTALL_DIR/app.py
Restart=always
RestartSec=5
TimeoutStopSec=15

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now minidisplay-web.service
sleep 2
if ! systemctl is-active --quiet minidisplay-web.service; then
    warn "El servicio no arranco. Revisa: journalctl -u minidisplay-web -n 50"
fi

# ---------------------------------------------------------------------------
# Resumen
# ---------------------------------------------------------------------------
IP=$(hostname -I 2>/dev/null | awk '{print $1}')
cat <<EOF

Panel web instalado y arrancado.

  URL       : http://${IP:-IP_DEL_SERVIDOR}:$PORT
  Codigo    : $INSTALL_DIR
  Datos     : $DATA_DIR  (imagenes, config.json, webapp.log)
  Config    : /etc/default/minidisplay-web
  Servicio  : minidisplay-web

Comandos:
  systemctl status minidisplay-web
  systemctl restart minidisplay-web
  journalctl -u minidisplay-web -f
  tail -f $DATA_DIR/webapp.log

Si usas firewall:
  sudo ufw allow $PORT/tcp

Notas:
  - El panel USB y este servicio no pueden compartir puerto: si tenias
    turing-smart-screen activo se ha detenido.
  - Cierra y vuelve a abrir la sesion para tomar el grupo $TTY_GROUP
    (o ejecuta: newgrp $TTY_GROUP).
  - Acciones de servicios: deshabilitadas salvo que hayas usado --actions.
EOF
