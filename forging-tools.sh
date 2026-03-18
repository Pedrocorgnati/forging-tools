#!/bin/bash
# Launcher for Forging Tools
cd "$(dirname "$(readlink -f "$0")")"
exec python3 main.py "$@"
