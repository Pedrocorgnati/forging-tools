"""Forge Pick Panel — Qt widget embeddable as sidebar in Row 1.

Reads .claude/projects/*.json and types the relative path
on button click via xdotool after a 2-second delay.
"""
import json
import subprocess
import threading
import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from design_tokens import (
    ACCENT,
    ACCENT_DARK,
    ACCENT_HOVER,
    BG,
    BORDER,
    BORDER_LIGHT,
    SURFACE,
    SURFACE_HOVER,
    TEXT,
    TEXT_SEC,
    TEXT_TERT,
    R_MD,
    R_SM,
    FONT_FAMILY,
    FONT_MONO,
)

# Resolve systemForge root: ai-forge/forging-tools/forge_pick_panel.py -> 3 levels up
_SCRIPT_DIR = Path(__file__).resolve().parent
_FORGE_ROOT = _SCRIPT_DIR.parent.parent
_PROJECTS_DIR = _FORGE_ROOT / ".claude" / "projects"
_FAVORITES_FILE = _SCRIPT_DIR / "forge-pick" / "favorites.json"

# Colors for button states
_SUCCESS = "#34D399"
_YELLOW = "#F9E2AF"


def _load_favorites() -> set:
    try:
        return set(json.loads(_FAVORITES_FILE.read_text(encoding="utf-8")))
    except Exception:
        return set()


def _save_favorites(favs: set) -> None:
    _FAVORITES_FILE.parent.mkdir(parents=True, exist_ok=True)
    _FAVORITES_FILE.write_text(
        json.dumps(sorted(favs), ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _load_projects() -> list:
    """Return list of (name, commercial_name, config_path, workspace_root)."""
    favorites = _load_favorites()
    projects = []
    if not _PROJECTS_DIR.is_dir():
        return projects
    for json_file in sorted(_PROJECTS_DIR.glob("*.json")):
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
            name = data.get("name") or json_file.stem
            commercial = data.get("commercial_name") or name.replace("-", " ").title()
            rel_path = f".claude/projects/{json_file.name}"
            workspace = data.get("basic_flow", {}).get("workspace_root", "")
            projects.append((name, commercial, rel_path, workspace))
        except Exception:
            pass
    projects.sort(key=lambda p: (0 if p[0] in favorites else 1, p[0].lower()))
    return projects


def _type_worker(path: str) -> None:
    """Wait 2 seconds then type path via xdotool."""
    time.sleep(2)
    subprocess.run(
        ["xdotool", "type", "--clearmodifiers", "--", path],
        check=False,
    )


class _FavDot(QPushButton):
    """Small dot that toggles favourite state."""

    def __init__(self, name: str, on_toggle, parent=None):
        super().__init__(parent)
        self._name = name
        self._on_toggle = on_toggle
        self.setFixedSize(16, 16)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("border: none; background: transparent;")
        self.clicked.connect(self._toggle)
        self._refresh()

    def _refresh(self):
        favs = _load_favorites()
        color = _YELLOW if self._name in favs else TEXT_TERT
        self.setText("●")
        self.setStyleSheet(
            f"border: none; background: transparent; color: {color}; "
            f"font-size: 10px; padding: 0;"
        )

    def _toggle(self):
        favs = _load_favorites()
        if self._name in favs:
            favs.discard(self._name)
        else:
            favs.add(self._name)
        _save_favorites(favs)
        self._on_toggle()


class _ActionBtn(QPushButton):
    """Small action button (JSON / WS) with typing functionality."""

    def __init__(self, text: str, path: str, color: str, enabled: bool = True, parent=None):
        super().__init__(text, parent)
        self._path = path
        self._color = color
        self._orig_text = text
        self._typing = False

        self.setFixedSize(42, 24)
        self.setCursor(Qt.CursorShape.PointingHandCursor if enabled else Qt.CursorShape.ArrowCursor)
        self.setEnabled(enabled)

        if enabled:
            self.setStyleSheet(
                f"QPushButton {{ background: {SURFACE}; color: {color}; border: 1px solid {BORDER_LIGHT}; "
                f"border-radius: {R_SM}px; font-size: 10px; font-weight: bold; padding: 2px 4px; }}"
                f"QPushButton:hover {{ background: {SURFACE_HOVER}; border-color: {color}; }}"
            )
        else:
            self.setStyleSheet(
                f"QPushButton {{ background: {BG}; color: {TEXT_TERT}; border: 1px solid {BG}; "
                f"border-radius: {R_SM}px; font-size: 10px; padding: 2px 4px; }}"
            )

        if enabled:
            self.clicked.connect(self._on_click)

    def _on_click(self):
        if self._typing:
            return
        self._typing = True
        self.setText("…")
        self.setStyleSheet(
            f"QPushButton {{ background: {ACCENT}; color: {BG}; border: 1px solid {ACCENT}; "
            f"border-radius: {R_SM}px; font-size: 10px; font-weight: bold; padding: 2px 4px; }}"
        )
        self.setCursor(Qt.CursorShape.WaitCursor)

        def worker():
            _type_worker(self._path)
            # Restore on main thread
            QTimer.singleShot(0, self._restore)

        threading.Thread(target=worker, daemon=True).start()

    def _restore(self):
        self._typing = False
        self.setText(self._orig_text)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(
            f"QPushButton {{ background: {SURFACE}; color: {self._color}; border: 1px solid {BORDER_LIGHT}; "
            f"border-radius: {R_SM}px; font-size: 10px; font-weight: bold; padding: 2px 4px; }}"
            f"QPushButton:hover {{ background: {SURFACE_HOVER}; border-color: {self._color}; }}"
        )


class ForgePickPanel(QWidget):
    """Sidebar panel with project list — embeddable in Row 1."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background-color: {BG};")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        header = QFrame()
        header.setFixedHeight(36)
        header.setStyleSheet(
            f"background-color: {SURFACE}; border-bottom: 1px solid {BORDER_LIGHT};"
        )
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(10, 0, 6, 0)
        h_layout.setSpacing(4)

        title = QLabel("Forge Pick")
        title.setStyleSheet(
            f"color: {ACCENT}; font-size: 12px; font-weight: bold; background: transparent;"
        )
        h_layout.addWidget(title)
        h_layout.addStretch()

        refresh_btn = QPushButton("⟳")
        refresh_btn.setFixedSize(24, 22)
        refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        refresh_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none; color: {TEXT_SEC}; font-size: 14px; }}"
            f"QPushButton:hover {{ color: {ACCENT}; }}"
        )
        refresh_btn.setToolTip("Recarregar projetos")
        refresh_btn.clicked.connect(self._reload)
        h_layout.addWidget(refresh_btn)

        layout.addWidget(header)

        # Separator
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background-color: {BORDER_LIGHT};")
        layout.addWidget(sep)

        # Scrollable project list
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            f"QScrollArea {{ background: {BG}; border: none; }}"
        )
        self._list_widget = QWidget()
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.setContentsMargins(8, 6, 8, 6)
        self._list_layout.setSpacing(3)
        self._list_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(self._list_widget)
        layout.addWidget(scroll)

        # Right border separator
        self.setStyleSheet(
            f"ForgePickPanel {{ background-color: {BG}; border-right: 1px solid {BORDER_LIGHT}; }}"
        )

        self._reload()

    def _reload(self):
        # Clear existing rows
        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        projects = _load_projects()
        if not projects:
            empty = QLabel("Nenhum projeto.")
            empty.setStyleSheet(
                f"color: {TEXT_TERT}; font-size: 11px; padding: 12px; background: transparent;"
            )
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._list_layout.addWidget(empty)
            return

        for name, commercial, path, workspace in projects:
            self._add_row(name, commercial, path, workspace)

    def _add_row(self, name: str, commercial: str, path: str, workspace: str):
        row = QFrame()
        row.setStyleSheet(
            f"QFrame {{ background: transparent; border-radius: {R_SM}px; }}"
            f"QFrame:hover {{ background: {SURFACE}; }}"
        )
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(4, 3, 4, 3)
        row_layout.setSpacing(5)

        fav = _FavDot(name, self._reload, row)
        row_layout.addWidget(fav)

        label = QLabel(commercial)
        label.setStyleSheet(
            f"color: {TEXT}; font-size: 11px; background: transparent;"
        )
        label.setWordWrap(False)
        row_layout.addWidget(label, 1)

        json_btn = _ActionBtn("JSON", path, _YELLOW, True, row)
        row_layout.addWidget(json_btn)

        ws_btn = _ActionBtn("WS", workspace, _SUCCESS, bool(workspace), row)
        row_layout.addWidget(ws_btn)

        self._list_layout.addWidget(row)
