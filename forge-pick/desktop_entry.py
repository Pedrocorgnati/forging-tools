#!/usr/bin/env python3
"""Integracao desktop do Forge Pick (Ubuntu/GNOME).

Mesmo padrao do forge-outreach / task-manager-desktop: instalacao idempotente,
content-compare antes de escrever, falhas nunca abortam o app.

Artefatos:
- icone PNG em ``~/.local/share/icons/forge-pick.png`` + hicolor;
- ``~/.local/share/applications/forge-pick.desktop``;
- alias CLI ``~/.local/bin/forge-pick``.
"""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
from pathlib import Path

_ICON_NAME = "forge-pick"
_DESKTOP_NAME = "forge-pick"
_APP_ROOT = Path(__file__).resolve().parent
_APP_PY = _APP_ROOT / "app.py"
_FORGE_ROOT = _APP_ROOT.parent.parent.parent
_ASSET_ICON = _APP_ROOT / "assets" / "forge-pick.png"
_ICON_SIZES = (512, 256, 128, 96, 64, 48, 32, 24, 22, 16)

ICON_PATH = Path.home() / ".local" / "share" / "icons" / f"{_ICON_NAME}.png"
HICOLOR_ROOT = Path.home() / ".local" / "share" / "icons" / "hicolor"
DESKTOP_PATH = (
    Path.home() / ".local" / "share" / "applications" / f"{_DESKTOP_NAME}.desktop"
)
BIN_PATH = Path.home() / ".local" / "bin" / "forge-pick"

_WRAPPER_SENTINEL = "# forge-pick-cli-wrapper v1"


def _exec_field(*args: str) -> str:
    """Monta o campo Exec conforme a Desktop Entry Spec."""
    return " ".join('"' + arg.replace("%", "%%") + '"' for arg in args)


def _resolve_exec_cmd() -> str:
    """Prefer the ASCII CLI wrapper so Exec never embeds the repo path.

    The source tree lives under ``.../Repositórios/...`` (non-ASCII). Putting
    that path in ``Exec=`` is what the alias avoids: ``~/.local/bin/forge-pick``
    is ASCII-only and is the same entrypoint as typing the command. Fallback
    to python+app.py only when the wrapper is not installed yet.
    """
    if BIN_PATH.is_file() and os.access(BIN_PATH, os.X_OK):
        return _exec_field(str(BIN_PATH))
    python = sys.executable or "/usr/bin/python3"
    return _exec_field(python, str(_APP_PY))


def _desktop_content(exec_cmd: str) -> str:
    return (
        "[Desktop Entry]\n"
        "Version=1.0\n"
        "Type=Application\n"
        "Name=Forge Pick\n"
        "GenericName=Project launcher\n"
        "Comment=Abre paths de projetos SystemForge (JSON, workspace, terminal, VS Code)\n"
        f"Exec={exec_cmd}\n"
        f"Path={_FORGE_ROOT}\n"
        f"Icon={ICON_PATH}\n"
        "Terminal=false\n"
        "Categories=Development;\n"
        "Keywords=forge;pick;project;systemforge;workspace;vscode;\n"
        "StartupNotify=true\n"
        "StartupWMClass=forge-pick\n"
        "DBusActivatable=false\n"
    )


def _bin_wrapper_content() -> str:
    python = sys.executable or "/usr/bin/python3"
    return (
        "#!/usr/bin/env bash\n"
        f"{_WRAPPER_SENTINEL}\n"
        f'exec "{python}" "{_APP_PY}" "$@"\n'
    )


def _write_if_changed(path: Path, data: bytes, mode: int) -> bool:
    path.parent.mkdir(parents=True, mode=0o755, exist_ok=True)
    if path.exists() and path.read_bytes() == data:
        return False
    path.write_bytes(data)
    path.chmod(mode)
    return True


def install_icon() -> bool:
    if not _ASSET_ICON.is_file():
        print(f"[desktop-entry] icone ausente: {_ASSET_ICON}", file=sys.stderr)
        return False
    master = _ASSET_ICON.read_bytes()
    wrote = _write_if_changed(ICON_PATH, master, 0o644)

    resized: dict[int, bytes] = {}
    try:
        from PIL import Image

        img = Image.open(_ASSET_ICON).convert("RGBA")
        for size in _ICON_SIZES:
            buf = io.BytesIO()
            img.resize((size, size), Image.Resampling.LANCZOS).save(
                buf, "PNG", optimize=True
            )
            resized[size] = buf.getvalue()
    except Exception:
        resized = {256: master, 128: master}

    for size, payload in resized.items():
        dest = HICOLOR_ROOT / f"{size}x{size}" / "apps" / f"{_ICON_NAME}.png"
        if _write_if_changed(dest, payload, 0o644):
            wrote = True
    return wrote


def install_desktop_entry(exec_cmd: str) -> bool:
    content = _desktop_content(exec_cmd).encode("utf-8")
    return _write_if_changed(DESKTOP_PATH, content, 0o644)


def install_cli_alias() -> bool:
    content = _bin_wrapper_content().encode("utf-8")
    if BIN_PATH.exists():
        try:
            existing = BIN_PATH.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return False
        if existing.encode("utf-8") == content:
            return False
        ours = _WRAPPER_SENTINEL in existing or str(_APP_PY) in existing
        if not ours:
            return False
    return _write_if_changed(BIN_PATH, content, 0o755)


def _refresh_desktop_caches() -> None:
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return
    commands = (
        ["xdg-desktop-menu", "forceupdate"],
        ["update-desktop-database", str(DESKTOP_PATH.parent)],
        ["gtk-update-icon-cache", "-f", "-t", str(HICOLOR_ROOT)],
    )
    for cmd in commands:
        if shutil.which(cmd[0]) is None:
            continue
        try:
            subprocess.run(cmd, check=False, capture_output=True, timeout=5)
        except Exception:  # noqa: BLE001
            pass


def ensure_desktop_integration() -> None:
    try:
        install_icon()
    except OSError as exc:
        print(f"[desktop-entry] icone: {exc}", file=sys.stderr)
    try:
        install_cli_alias()
    except OSError as exc:
        print(f"[desktop-entry] alias cli: {exc}", file=sys.stderr)
    try:
        # Alias first so Exec can point at the ASCII wrapper.
        install_desktop_entry(_resolve_exec_cmd())
    except OSError as exc:
        print(f"[desktop-entry] .desktop: {exc}", file=sys.stderr)
    _refresh_desktop_caches()


if __name__ == "__main__":
    ensure_desktop_integration()
    print(f"desktop : {DESKTOP_PATH}")
    print(f"icon    : {ICON_PATH}")
    print(f"cli     : {BIN_PATH}")
    print("Forge Pick instalado no menu de aplicativos do Ubuntu.")
