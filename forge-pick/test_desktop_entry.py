"""Unit tests for Forge Pick desktop integration."""

from __future__ import annotations

import json
from pathlib import Path

import desktop_entry as de


def test_forge_root_is_systemforge_not_app_dir() -> None:
    app_root = Path(de._APP_ROOT)
    forge_root = Path(de._FORGE_ROOT)
    assert app_root.name == "forge-pick"
    assert forge_root.name == "systemForge"
    assert (forge_root / ".claude" / "projects").is_dir()
    assert forge_root == app_root.parent.parent.parent


def test_desktop_path_is_forge_root() -> None:
    content = de._desktop_content("/tmp/fake-exec")
    assert f"Path={de._FORGE_ROOT}" in content
    assert f"Path={de._APP_ROOT}\n" not in content


def test_desktop_wmclass_matches_tk_and_icon_is_absolute() -> None:
    content = de._desktop_content("/tmp/fake-exec")
    assert "StartupWMClass=forge-pick\n" in content
    assert "StartupWMClass=ForgePick" not in content
    assert f"Icon={de.ICON_PATH}" in content
    assert "Icon=forge-pick\n" not in content


def test_show_all_defaults_false_and_roundtrips(tmp_path, monkeypatch) -> None:
    import app as forge_pick_app

    settings = tmp_path / "settings.json"
    monkeypatch.setattr(forge_pick_app, "SETTINGS_FILE", settings)
    assert forge_pick_app.load_show_all() is False
    forge_pick_app.save_show_all(True)
    assert json.loads(settings.read_text(encoding="utf-8"))["show_all"] is True
    assert forge_pick_app.load_show_all() is True
    forge_pick_app.save_show_all(False)
    assert forge_pick_app.load_show_all() is False


def test_resolve_exec_prefers_ascii_wrapper(tmp_path, monkeypatch) -> None:
    wrapper = tmp_path / "forge-pick"
    wrapper.write_text("#!/bin/sh\n", encoding="utf-8")
    wrapper.chmod(0o755)
    monkeypatch.setattr(de, "BIN_PATH", wrapper)
    cmd = de._resolve_exec_cmd()
    assert str(wrapper) in cmd
    assert "app.py" not in cmd
    assert "Reposit" not in cmd
