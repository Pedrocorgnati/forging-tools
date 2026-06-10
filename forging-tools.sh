#!/bin/bash
# Launcher for Forging Tools
cd "$(dirname "$(readlink -f "$0")")"
# Prefere o venv do projeto (PySide6/WebEngine vivem nele); fallback p/ python3 do sistema.
if [ -x ".venv/bin/python" ]; then
  exec .venv/bin/python main.py "$@"
fi
exec python3 main.py "$@"
