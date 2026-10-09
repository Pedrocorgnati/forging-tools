#!/usr/bin/env bash
set -euo pipefail

# Installer for Forge Pick on Ubuntu/Debian
# 1) system deps: python3-tk, xdotool
# 2) desktop entry + icon + CLI alias (~/.local)

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing required command: $1" >&2
    exit 1
  }
}

require_cmd sudo
require_cmd apt-get
require_cmd python3

SCRIPT_DIR="$(cd "$(dirname "$(realpath "$0")")" && pwd)"

echo "Installing system packages (python3-tk, xdotool)..."
sudo apt-get update -y
sudo apt-get install -y python3-tk xdotool

echo ""
echo "Installing Ubuntu app (icon, menu entry, CLI)..."
python3 "$SCRIPT_DIR/desktop_entry.py"

echo ""
echo "All set."
echo "  Menu : procure 'Forge Pick' no lancador de aplicativos"
echo "  CLI  : forge-pick"
echo "  Run  : python3 $SCRIPT_DIR/app.py"
if ! command -v forge-pick >/dev/null 2>&1; then
  echo ""
  echo "Aviso: ~/.local/bin nao esta no PATH desta shell."
  echo "Inclua-o em ~/.profile e reabra a sessao, ou use o atalho do menu."
fi
