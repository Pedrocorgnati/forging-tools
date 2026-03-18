#!/usr/bin/env bash
set -euo pipefail

# Installer for Forge Pick on Ubuntu/Debian
# Installs system dependencies: python3-tk and xdotool

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing required command: $1" >&2
    exit 1
  }
}

require_cmd sudo
require_cmd apt-get
require_cmd python3

echo "Installing system packages (python3-tk, xdotool)..."
sudo apt-get update -y
sudo apt-get install -y python3-tk xdotool

echo ""
echo "All set! Run the app with:"
echo "  python3 $(dirname "$(realpath "$0")")/app.py"
