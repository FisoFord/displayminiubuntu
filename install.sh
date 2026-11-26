#!/usr/bin/env bash
#
# Instalador rápido de MiniDisplay Web para Ubuntu/Debian.
#
#   sudo ./install.sh                 # puerto 8080, acciones habilitadas
#   sudo ./install.sh --port 9000
#   sudo ./install.sh --no-actions    # solo lectura
#
# También se puede ejecutar sin tener el repo descargado:
#   curl -fsSL https://raw.githubusercontent.com/FisoFord/displayminiubuntu/main/install.sh | sudo bash
#
set -euo pipefail

PORT="${PORT:-8080}"
ACTIONS=1
REPO_URL="https://github.com/FisoFord/displayminiubuntu.git"

log()  { printf '\033[1;32m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[!]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[x]\033[0m %s\n' "$*" >&2; exit 1; }

usage() {
    cat <<'EOF'
Uso: ./install.sh [opciones]

  --port N        Puerto HTTP del panel (por defecto 8080)
  --no-actions    No permite start/stop/restart desde la web
  -h, --help      Muestra esta ayuda

Ejemplo sin descargar el repo:
  curl -fsSL https://raw.githubusercontent.com/FisoFord/displayminiubuntu/main/install.sh | sudo bash
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --port)       PORT="${2:?falta el número de puerto}"; shift 2 ;;
        --no-actions) ACTIONS=0; shift ;;
        -h|--help)    usage; exit 0 ;;
        *)            die "Opción desconocida: $1 (usa --help)" ;;
    esac
done

case "$PORT" in
    ''|*[!0-9]*) die "El puerto debe ser un número (ej. 8080)" ;;
esac

# Si el script está dentro del repositorio, usamos esa copia. Si se ha
# descargado suelto (curl), clonamos el repositorio en un directorio temporal.
SOURCE_DIR=""
if [ -n "${BASH_SOURCE[0]:-}" ]; then
    SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || true)"
fi

CLEANUP=""
if [ -n "$SOURCE_DIR" ] && [ -f "$SOURCE_DIR/webapp/install.sh" ] && [ -f "$SOURCE_DIR/minidisplay.py" ]; then
    APP_DIR="$SOURCE_DIR/webapp"
    log "Usando los archivos locales de $SOURCE_DIR"
else
    log "Descargando el proyecto..."
    if ! command -v git >/dev/null 2>&1; then
        if command -v apt-get >/dev/null 2>&1; then
            export DEBIAN_FRONTEND=noninteractive
            apt-get update -qq
            apt-get install -y -qq git
        else
            die "Necesito git para descargar el proyecto. Instálalo y vuelve a ejecutar."
        fi
    fi
    CLEANUP="$(mktemp -d)"
    trap 'rm -rf "$CLEANUP"' EXIT
    git clone --depth 1 "$REPO_URL" "$CLEANUP/repo"
    APP_DIR="$CLEANUP/repo/webapp"
fi

[ -f "$APP_DIR/install.sh" ] || die "No encuentro $APP_DIR/install.sh"

ARGS=(--port "$PORT")
[ "$ACTIONS" -eq 1 ] && ARGS+=(--actions)

log "Instalando MiniDisplay Web en el puerto $PORT..."
if [ "$(id -u)" -ne 0 ]; then
    sudo -E bash "$APP_DIR/install.sh" "${ARGS[@]}"
else
    bash "$APP_DIR/install.sh" "${ARGS[@]}"
fi

IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
printf '\n\033[1;32mListo.\033[0m Abre: http://%s:%s\n' "${IP:-IP_DEL_SERVIDOR}" "$PORT"
