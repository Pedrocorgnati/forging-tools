"""Forge Pick Panel — Qt widget embeddable as sidebar in Row 1.

Reads .claude/projects/*.json and types the relative path
on button click via xdotool after a 2-second delay.
"""
import json
import subprocess
import threading
import time
from pathlib import Path

from PySide6.QtCore import Qt, QMimeData, QPoint
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
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

# Custom MIME type for drag-drop reordering
_DRAG_MIME = "application/x-forge-pick-fav"


# ── Favorites persistence (ordered list, not sorted set) ──

def _load_favorites_ordered() -> list:
    """Return ordered list of favorite project names (preserves drag order)."""
    try:
        data = json.loads(_FAVORITES_FILE.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
        return []
    except Exception:
        return []


def _load_favorites() -> set:
    return set(_load_favorites_ordered())


def _save_favorites(favs_ordered: list) -> None:
    """Save favorites as ordered list — NO sorting, preserves user-defined order."""
    _FAVORITES_FILE.parent.mkdir(parents=True, exist_ok=True)
    _FAVORITES_FILE.write_text(
        json.dumps(favs_ordered, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _toggle_favorite(name: str) -> None:
    """Add or remove a project from favorites, preserving existing order."""
    current = _load_favorites_ordered()
    if name in current:
        current.remove(name)
    else:
        current.append(name)
    _save_favorites(current)


def _load_all_projects() -> list:
    """Return list of (name, commercial_name, config_path, workspace_root)."""
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
    return projects


def _type_worker(path: str) -> None:
    """Wait 2 seconds then type path via xdotool."""
    time.sleep(2)
    subprocess.run(
        ["xdotool", "type", "--clearmodifiers", "--", path],
        check=False,
    )


# ── Widgets ──

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
        _toggle_favorite(self._name)
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
        threading.Thread(target=_type_worker, args=(self._path,), daemon=True).start()


class _DragHandle(QLabel):
    """Grip icon on the left of favorite rows — initiate drag by pulling."""

    def __init__(self, row_name: str, row_widget, parent=None):
        super().__init__("⠿", parent)
        self._row_name = row_name
        self._row_widget = row_widget  # reference to the full row QFrame for pixmap
        self._drag_start = None

        self.setFixedSize(14, 22)
        self.setCursor(Qt.CursorShape.SizeVerCursor)
        self.setStyleSheet(
            f"color: {TEXT_TERT}; font-size: 11px; background: transparent; padding: 0;"
        )
        self.setToolTip("Arrastar para reordenar")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = event.globalPosition().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if (self._drag_start is not None and
                (event.globalPosition().toPoint() - self._drag_start).manhattanLength() > 5):
            self._start_drag()
            self._drag_start = None
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_start = None
        super().mouseReleaseEvent(event)

    def _start_drag(self):
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(_DRAG_MIME, self._row_name.encode("utf-8"))
        drag.setMimeData(mime)
        if self._row_widget:
            pixmap = self._row_widget.grab()
            drag.setPixmap(pixmap)
            drag.setHotSpot(QPoint(pixmap.width() // 2, pixmap.height() // 2))
        drag.exec(Qt.DropAction.MoveAction)


class _FavoritesContainer(QWidget):
    """Container for favorite rows — accepts drops to reorder items."""

    def __init__(self, on_reorder, parent=None):
        super().__init__(parent)
        self._on_reorder = on_reorder
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(3)
        self._row_names: list[str] = []

        # Drop indicator: free-floating child NOT in layout, positioned manually
        self._indicator = QFrame(self)
        self._indicator.setFixedHeight(2)
        self._indicator.setStyleSheet(f"background: {ACCENT_DARK};")
        self._indicator.hide()

        self.setAcceptDrops(True)

    def add_row(self, name: str, widget: QWidget):
        self._row_names.append(name)
        self._layout.addWidget(widget)

    def _get_drop_index(self, y: int) -> int:
        """Map a y coordinate to a drop insertion index."""
        count = self._layout.count()
        for i in range(count):
            item = self._layout.itemAt(i)
            if item and item.widget():
                w = item.widget()
                if y < w.y() + w.height() // 2:
                    return i
        return count

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(_DRAG_MIME):
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(_DRAG_MIME):
            idx = self._get_drop_index(int(event.position().y()))
            self._show_indicator(idx)
            event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        self._indicator.hide()
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        self._indicator.hide()
        if not event.mimeData().hasFormat(_DRAG_MIME):
            return

        try:
            name = bytes(event.mimeData().data(_DRAG_MIME)).decode("utf-8")
        except Exception:
            event.ignore()
            return

        if name not in self._row_names:
            event.ignore()
            return

        drop_idx = self._get_drop_index(int(event.position().y()))
        old_idx = self._row_names.index(name)

        # Adjust: removing the element shifts indices above it
        if old_idx < drop_idx:
            drop_idx -= 1

        if old_idx != drop_idx:
            self._row_names.pop(old_idx)
            self._row_names.insert(drop_idx, name)
            self._on_reorder(list(self._row_names))

        event.acceptProposedAction()

    def _show_indicator(self, idx: int):
        count = self._layout.count()
        if count == 0:
            self._indicator.hide()
            return

        if idx < count:
            item = self._layout.itemAt(idx)
            if item and item.widget():
                y = max(0, item.widget().y() - 1)
                self._indicator.setGeometry(0, y, self.width(), 2)
                self._indicator.show()
                self._indicator.raise_()
        else:
            item = self._layout.itemAt(count - 1)
            if item and item.widget():
                w = item.widget()
                y = w.y() + w.height()
                self._indicator.setGeometry(0, y, self.width(), 2)
                self._indicator.show()
                self._indicator.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._indicator.isVisible():
            geo = self._indicator.geometry()
            self._indicator.setGeometry(0, geo.y(), self.width(), 2)


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

        # Search / grep filter bar
        self._search_bar = QLineEdit()
        self._search_bar.setPlaceholderText("🔍 Filtrar...")
        self._search_bar.setFixedHeight(28)
        self._search_bar.setStyleSheet(
            f"QLineEdit {{ background: {SURFACE}; border: none; "
            f"border-bottom: 1px solid {BORDER_LIGHT}; "
            f"color: {TEXT}; font-size: 11px; padding: 2px 8px; }}"
            f"QLineEdit:focus {{ border-bottom: 1px solid {ACCENT_DARK}; }}"
        )
        self._search_bar.textChanged.connect(self._on_search)
        layout.addWidget(self._search_bar)

        # Scrollable project list
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            f"QScrollArea {{ background: {BG}; border: none; }}"
        )
        self._list_widget = QWidget()
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.setContentsMargins(1, 6, 8, 6)
        self._list_layout.setSpacing(3)
        self._list_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(self._list_widget)
        layout.addWidget(scroll)

        # Right border separator
        self.setStyleSheet(
            f"ForgePickPanel {{ background-color: {BG}; border-right: 1px solid {BORDER_LIGHT}; }}"
        )

        self._reload()

    def _on_search(self, text: str):
        self._reload(filter_text=text.strip().lower())

    def _on_fav_reordered(self, new_visible_order: list):
        """Persist the new favorites order after a drag-drop in the container."""
        all_favs = _load_favorites_ordered()
        # Visible favorites in new order first, then any that were filtered out
        visible_set = set(new_visible_order)
        hidden_favs = [n for n in all_favs if n not in visible_set]
        _save_favorites(new_visible_order + hidden_favs)

    def _reload(self, filter_text: str = ""):
        # Clear existing rows
        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        all_projects = _load_all_projects()
        fav_order = _load_favorites_ordered()
        fav_set = set(fav_order)

        # Build project map by name
        proj_map = {p[0]: p for p in all_projects}

        # Favorites in user-defined order
        fav_projects = [proj_map[n] for n in fav_order if n in proj_map]

        # Non-favorites alphabetically
        other_projects = sorted(
            [p for p in all_projects if p[0] not in fav_set],
            key=lambda p: p[0].lower(),
        )

        # Apply search filter
        if filter_text:
            fav_projects = [
                p for p in fav_projects
                if filter_text in p[0].lower() or filter_text in p[1].lower()
            ]
            other_projects = [
                p for p in other_projects
                if filter_text in p[0].lower() or filter_text in p[1].lower()
            ]

        if not fav_projects and not other_projects:
            empty = QLabel("Nenhum projeto.")
            empty.setStyleSheet(
                f"color: {TEXT_TERT}; font-size: 11px; padding: 12px; background: transparent;"
            )
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._list_layout.addWidget(empty)
            return

        # ── Favorites section (draggable) ──
        if fav_projects:
            fav_container = _FavoritesContainer(self._on_fav_reordered)
            for name, commercial, path, workspace in fav_projects:
                row = self._make_row(name, commercial, path, workspace, is_fav=True)
                fav_container.add_row(name, row)
            self._list_layout.addWidget(fav_container)

        # Separator between favorites and regular projects
        if fav_projects and other_projects:
            sep = QFrame()
            sep.setFixedHeight(1)
            sep.setStyleSheet(f"background-color: {BORDER_LIGHT};")
            self._list_layout.addWidget(sep)

        # ── Non-favorites section (regular) ──
        for name, commercial, path, workspace in other_projects:
            row = self._make_row(name, commercial, path, workspace, is_fav=False)
            self._list_layout.addWidget(row)

    def _make_row(
        self, name: str, commercial: str, path: str, workspace: str, is_fav: bool
    ) -> QFrame:
        row = QFrame()
        row.setStyleSheet(
            f"QFrame {{ background: transparent; border-radius: {R_SM}px; }}"
            f"QFrame:hover {{ background: {SURFACE}; }}"
        )
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(4, 3, 4, 3)
        row_layout.setSpacing(5)

        if is_fav:
            # Drag handle — pass row reference for pixmap grab (set after full construction)
            handle = _DragHandle(name, row)
            row_layout.addWidget(handle)

        fav = _FavDot(name, self._reload, row)
        row_layout.addWidget(fav)

        label = QLabel(commercial)
        if is_fav:
            # Bold + 2px larger font for favorites
            label.setStyleSheet(
                f"color: {TEXT}; font-size: 13px; font-weight: bold; background: transparent;"
            )
            label.setMaximumWidth(100)  # slightly narrower to accommodate drag handle
        else:
            label.setStyleSheet(
                f"color: {TEXT}; font-size: 11px; background: transparent;"
            )
            label.setMaximumWidth(112)
        label.setWordWrap(False)
        label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        row_layout.addWidget(label, 1)

        json_btn = _ActionBtn("JSON", path, _YELLOW, True, row)
        row_layout.addWidget(json_btn)

        ws_btn = _ActionBtn("WS", workspace, _SUCCESS, bool(workspace), row)
        row_layout.addWidget(ws_btn)

        return row
