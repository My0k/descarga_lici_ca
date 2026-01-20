#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$ROOT_DIR/venv"

if [ ! -d "$VENV_DIR" ]; then
  echo "[INFO] Creando entorno virtual en \"$VENV_DIR\""
  echo "[INFO] Buscando python..."
  if command -v python3 >/dev/null 2>&1; then
    PYTHON=python3
  elif command -v python >/dev/null 2>&1; then
    PYTHON=python
  else
    echo "[ERROR] No se encontro python en el PATH."
    exit 1
  fi

  echo "[INFO] Version de Python:"
  "$PYTHON" --version

  echo "[DEBUG] Ejecutando: $PYTHON -m venv \"$VENV_DIR\""
  "$PYTHON" -m venv "$VENV_DIR"
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

if [ -f "$ROOT_DIR/requirements.txt" ]; then
  echo "[INFO] Instalando dependencias desde requirements.txt..."
  python -m pip install --upgrade pip
  python -m pip install -r "$ROOT_DIR/requirements.txt"
else
  echo "[WARN] No se encontro requirements.txt, se omite la instalacion de dependencias."
fi

echo "[INFO] Asegurando instalacion de PyQt5..."
python -m pip install --upgrade PyQt5 PyQt5-Qt5 PyQt5-sip || true

echo "[INFO] Lanzando aplicacion de produccion: front_produccion.py"
python "$ROOT_DIR/front_produccion.py"

echo "[INFO] Proceso finalizado. Pulse Enter para cerrar."
read -r _
