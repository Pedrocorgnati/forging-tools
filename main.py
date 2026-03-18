#!/usr/bin/env python3
"""Forging Tools — Visualize 2 WhatsApps + 2 páginas auxiliares em tela vertical."""
import os
import sys

# Flags do Chromium ANTES de importar Qt — remove sinais de automação
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = " ".join([
    "--disable-blink-features=AutomationControlled",
    "--disable-features=IsolateOrigins,site-per-process",
    "--disable-site-isolation-trials",
])

from PySide6.QtCore import Qt, QPoint, QRect, QEvent, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from browser_engine import BrowserEngine
from design_tokens import app_stylesheet, ACCENT, BG, BORDER_LIGHT, SURFACE
from forge_pick_panel import ForgePickPanel

_GRIP = 6  # largura das grip zones nas bordas


class _EdgeGrip(QWidget):
    """Widget fino e transparente posicionado sobre uma borda da janela.

    Captura mouse para redimensionamento manual em frameless windows.
    """

    _CURSORS = {
        "l": Qt.CursorShape.SizeHorCursor,
        "r": Qt.CursorShape.SizeHorCursor,
        "t": Qt.CursorShape.SizeVerCursor,
        "b": Qt.CursorShape.SizeVerCursor,
        "tl": Qt.CursorShape.SizeFDiagCursor,
        "br": Qt.CursorShape.SizeFDiagCursor,
        "tr": Qt.CursorShape.SizeBDiagCursor,
        "bl": Qt.CursorShape.SizeBDiagCursor,
    }

    def __init__(self, edge: str, parent: 'MainWindow'):
        super().__init__(parent)
        self._edge = edge
        self._window = parent
        self._drag_start = None
        self._geo_start = None
        self.setCursor(self._CURSORS[edge])
        self.setMouseTracking(True)
        # Fundo transparente mas clicável
        self.setStyleSheet("background: transparent;")

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton and not self._window.isMaximized():
            self._drag_start = event.globalPosition().toPoint()
            self._geo_start = self._window.geometry()

    def mouseMoveEvent(self, event: QMouseEvent):
        if not self._drag_start:
            return
        delta = event.globalPosition().toPoint() - self._drag_start
        geo = QRect(self._geo_start)
        min_w = self._window.minimumWidth()
        min_h = self._window.minimumHeight()
        e = self._edge

        if "r" in e:
            geo.setRight(max(geo.left() + min_w, geo.right() + delta.x()))
        if "l" in e:
            new_left = geo.left() + delta.x()
            if geo.right() - new_left >= min_w:
                geo.setLeft(new_left)
        if "b" in e:
            geo.setBottom(max(geo.top() + min_h, geo.bottom() + delta.y()))
        if "t" in e:
            new_top = geo.top() + delta.y()
            if geo.bottom() - new_top >= min_h:
                geo.setTop(new_top)

        self._window.setGeometry(geo)

    def mouseReleaseEvent(self, event: QMouseEvent):
        self._drag_start = None
        self._geo_start = None


class TitleBar(QWidget):
    """Barra de título customizada — usa startSystemMove() para drag nativo."""

    def __init__(self, parent: QMainWindow):
        super().__init__(parent)
        self._window = parent

        self.setObjectName("title_bar")
        self.setFixedHeight(40)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 8, 0)
        layout.setSpacing(0)

        icon_label = QLabel("◆")
        icon_label.setStyleSheet(f"color: {ACCENT}; font-size: 16px; background: transparent;")
        icon_label.setFixedWidth(24)
        layout.addWidget(icon_label)

        title = QLabel("Forging Tools")
        title.setObjectName("title_label")
        layout.addWidget(title)

        layout.addStretch()

        for text, obj_name, callback in [
            ("─", "title_btn", self._minimize),
            ("□", "title_btn", self._toggle_maximize),
            ("✕", "close_btn", self._close),
        ]:
            btn = QPushButton(text)
            btn.setObjectName(obj_name)
            btn.setFixedSize(36, 28)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(callback)
            layout.addWidget(btn)

    def _minimize(self):
        self._window.showMinimized()

    def _toggle_maximize(self):
        if self._window.isMaximized():
            self._window.showNormal()
        else:
            self._window.showMaximized()

    def _close(self):
        self._window.close()

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._window.windowHandle().startSystemMove()

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        self._toggle_maximize()


class RowHeader(QFrame):
    """Header de cada row de WhatsApp com label, botão sidebar toggle e scroll-to-input."""

    def __init__(self, label_text: str, parent=None):
        super().__init__(parent)
        self.setObjectName("row_header")
        self.setFixedHeight(44)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(6)

        label = QLabel(label_text)
        label.setObjectName("row_label")
        layout.addWidget(label)

        layout.addStretch()

        self.input_btn = QPushButton("▼")
        self.input_btn.setObjectName("sidebar_btn")
        self.input_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.input_btn.setToolTip("Rolar até a barra de digitação")
        layout.addWidget(self.input_btn)

        self.sidebar_btn = QPushButton()
        self.sidebar_btn.setObjectName("sidebar_btn")
        self.sidebar_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._sidebar_half = True
        self._update_sidebar_icon()
        layout.addWidget(self.sidebar_btn)

    def _update_sidebar_icon(self):
        if self._sidebar_half:
            self.sidebar_btn.setText("◧")
            self.sidebar_btn.setToolTip("Sidebar 75% — clique para colapsar")
        else:
            self.sidebar_btn.setText("▷")
            self.sidebar_btn.setToolTip("Sidebar colapsada — clique para expandir")

    def toggle_sidebar_state(self):
        self._sidebar_half = not self._sidebar_half
        self._update_sidebar_icon()


class BrowserRow(QWidget):
    """Container com header + barra de URL toggle + WebEngineView.

    Opcionalmente suporta um sidebar panel (ex: ForgePickPanel) que desliza
    horizontalmente para dentro/fora do lado esquerdo.
    """

    def __init__(self, label: str, engine: BrowserEngine, slot_id: str, parent=None):
        super().__init__(parent)
        self._sidebar_panel = None
        self._sidebar_visible = False
        self._sidebar_anim = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.header = RowHeader(label)
        outer.addWidget(self.header)

        # Barra de URL (escondida por default)
        self._url_bar = QLineEdit()
        self._url_bar.setObjectName("url_bar")
        self._url_bar.setPlaceholderText("Digite a URL e pressione Enter...")
        self._url_bar.setFixedHeight(30)
        self._url_bar.setVisible(False)
        outer.addWidget(self._url_bar)

        # Content area: horizontal layout for sidebar + browser
        self._content = QWidget()
        self._content_layout = QHBoxLayout(self._content)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(0)

        self.view = engine.create_view(slot_id, inject_sidebar_toggle=True)
        self._content_layout.addWidget(self.view)
        outer.addWidget(self._content)

        self.header.sidebar_btn.clicked.connect(self._toggle_sidebar)
        self.header.input_btn.clicked.connect(self._toggle_url_bar)
        self._url_bar.returnPressed.connect(self._navigate_url)

        self.view.urlChanged.connect(
            lambda url: self._url_bar.setText(url.toString())
            if self._url_bar.isVisible() else None
        )

    def set_sidebar(self, panel: QWidget, width: int = 260):
        """Attach a sidebar panel (inserted at left, hidden initially)."""
        self._sidebar_panel = panel
        self._sidebar_width = width
        panel.setMinimumWidth(0)
        panel.setMaximumWidth(0)
        panel.setVisible(False)
        self._content_layout.insertWidget(0, panel)

    def toggle_sidebar_panel(self):
        """Slide the sidebar panel in/out horizontally."""
        if not self._sidebar_panel:
            return
        self._sidebar_visible = not self._sidebar_visible
        panel = self._sidebar_panel
        target_w = self._sidebar_width

        if self._sidebar_visible:
            panel.setVisible(True)

        anim = QPropertyAnimation(panel, b"maximumWidth", self)
        anim.setDuration(200)
        anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
        anim.setStartValue(panel.maximumWidth())
        anim.setEndValue(target_w if self._sidebar_visible else 0)

        if not self._sidebar_visible:
            anim.finished.connect(lambda: panel.setVisible(False))
        else:
            anim.finished.connect(lambda: panel.setMaximumWidth(target_w))

        anim.start()
        self._sidebar_anim = anim
        return self._sidebar_visible

    def _toggle_sidebar(self):
        self.view.page().runJavaScript(
            "if(window.__toggleSidebar) window.__toggleSidebar();",
            0,
        )
        self.header.toggle_sidebar_state()

    def _toggle_url_bar(self):
        visible = not self._url_bar.isVisible()
        self._url_bar.setVisible(visible)
        if visible:
            self._url_bar.setText(self.view.url().toString())
            self._url_bar.setFocus()
            self._url_bar.selectAll()
            self.header.input_btn.setText("▲")
        else:
            self.header.input_btn.setText("▼")

    def _navigate_url(self):
        url = self._url_bar.text().strip()
        if url and not url.startswith(("http://", "https://")):
            url = "https://" + url
        if url:
            from PySide6.QtCore import QUrl
            self.view.load(QUrl(url))


class MiniViewPanel(QWidget):
    """Mini browser panel com header ▼ + URL bar toggle para Row 3."""

    def __init__(self, label: str, view, parent=None):
        super().__init__(parent)
        self.view = view

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Mini header
        header = QFrame()
        header.setObjectName("row_header")
        header.setFixedHeight(36)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(8, 0, 6, 0)
        header_layout.setSpacing(4)
        header_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        lbl = QLabel(label)
        lbl.setObjectName("row_label")
        lbl.setStyleSheet("font-size: 11px;")
        header_layout.addWidget(lbl)
        header_layout.addStretch()

        self._url_btn = QPushButton("▼")
        self._url_btn.setObjectName("sidebar_btn")
        self._url_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._url_btn.setToolTip("Mostrar/ocultar barra de URL")
        self._url_btn.setFixedSize(28, 22)
        self._url_btn.setStyleSheet("font-size: 11px; padding: 2px 6px; min-width: 24px; min-height: 20px;")
        header_layout.addWidget(self._url_btn)
        layout.addWidget(header)

        # URL bar (escondida)
        self._url_bar = QLineEdit()
        self._url_bar.setObjectName("url_bar")
        self._url_bar.setPlaceholderText("URL...")
        self._url_bar.setFixedHeight(26)
        self._url_bar.setStyleSheet("font-size: 11px; padding: 2px 8px;")
        self._url_bar.setVisible(False)
        layout.addWidget(self._url_bar)

        layout.addWidget(self.view)

        self._url_btn.clicked.connect(self._toggle_url_bar)
        self._url_bar.returnPressed.connect(self._navigate_url)
        self.view.urlChanged.connect(
            lambda url: self._url_bar.setText(url.toString())
            if self._url_bar.isVisible() else None
        )

    def _toggle_url_bar(self):
        visible = not self._url_bar.isVisible()
        self._url_bar.setVisible(visible)
        if visible:
            self._url_bar.setText(self.view.url().toString())
            self._url_bar.setFocus()
            self._url_bar.selectAll()
            self._url_btn.setText("▲")
        else:
            self._url_btn.setText("▼")

    def _navigate_url(self):
        url = self._url_bar.text().strip()
        if url and not url.startswith(("http://", "https://")):
            url = "https://" + url
        if url:
            from PySide6.QtCore import QUrl
            self.view.load(QUrl(url))


class MainWindow(QMainWindow):
    """Janela principal com resize via edge grips sobrepostos."""

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setMinimumSize(600, 800)
        self.resize(800, 1200)
        self.setWindowTitle("Forging Tools")

        self._engine = BrowserEngine(self)
        self._row3_visible = True

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Title bar
        self._title_bar = TitleBar(self)
        main_layout.addWidget(self._title_bar)

        # Main splitter (vertical — 3 rows)
        self._splitter = QSplitter(Qt.Orientation.Vertical)
        self._splitter.setHandleWidth(6)
        self._splitter.setChildrenCollapsible(False)
        main_layout.addWidget(self._splitter)

        # Row 1: WhatsApp 2 (slot-2) + Forge Pick sidebar
        self._row1 = BrowserRow("", self._engine, "slot-2")

        # Forge Pick embedded sidebar
        self._forge_pick_panel = ForgePickPanel()
        self._row1.set_sidebar(self._forge_pick_panel)

        # Chevron button to toggle forge-pick sidebar
        self._forge_pick_btn = QPushButton("◂")
        self._forge_pick_btn.setObjectName("sidebar_btn")
        self._forge_pick_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._forge_pick_btn.setToolTip("Abrir Forge Pick")
        self._forge_pick_btn.clicked.connect(self._toggle_forge_pick)
        self._row1.header.layout().insertWidget(0, self._forge_pick_btn)
        self._splitter.addWidget(self._row1)

        # Row 2: WhatsApp 1 (slot-1)
        self._row2 = BrowserRow("", self._engine, "slot-1")
        self._splitter.addWidget(self._row2)

        # ── FEATURE: Row 3 colapsável via chevron down ──
        self._row3_wrapper = QWidget()
        row3_layout = QVBoxLayout(self._row3_wrapper)
        row3_layout.setContentsMargins(0, 0, 0, 0)
        row3_layout.setSpacing(0)

        # Chevron button (barra fina no topo da div 3)
        self._row3_collapse_btn = QPushButton("▾")
        self._row3_collapse_btn.setObjectName("row3_chevron")
        self._row3_collapse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._row3_collapse_btn.setToolTip("Esconder painel auxiliar")
        self._row3_collapse_btn.setFixedHeight(20)
        self._row3_collapse_btn.clicked.connect(self._toggle_row3)
        row3_layout.addWidget(self._row3_collapse_btn)

        # Row 3 content: Two QWebEngine views (sessões compartilhadas)
        self._row3_content = QWidget()
        self._row3_content_layout = QVBoxLayout(self._row3_content)
        self._row3_content_layout.setContentsMargins(0, 0, 0, 0)
        self._row3_content_layout.setSpacing(0)

        self._row3_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._row3_splitter.setHandleWidth(6)
        self._row3_splitter.setChildrenCollapsible(False)

        _AUX_URL = "https://google.com"

        view3 = self._engine.create_view(
            "slot-2", url=_AUX_URL, inject_sidebar_toggle=False
        )
        self._mini3 = MiniViewPanel("", view3)
        self._row3_splitter.addWidget(self._mini3)

        view4 = self._engine.create_view(
            "slot-1", url=_AUX_URL, inject_sidebar_toggle=False
        )
        self._mini4 = MiniViewPanel("", view4)
        self._row3_splitter.addWidget(self._mini4)

        self._row3_splitter.setStretchFactor(0, 1)
        self._row3_splitter.setStretchFactor(1, 1)

        self._row3_content_layout.addWidget(self._row3_splitter)
        row3_layout.addWidget(self._row3_content)

        self._splitter.addWidget(self._row3_wrapper)
        self._row3_expanded_height = 0  # capturado no primeiro show

        self._splitter.setStretchFactor(0, 4)
        self._splitter.setStretchFactor(1, 4)
        self._splitter.setStretchFactor(2, 2)

        # ── Edge grips (sobrepostos ao conteúdo, raised) ──
        self._grips = []
        for edge in ("l", "r", "t", "b", "tl", "tr", "bl", "br"):
            grip = _EdgeGrip(edge, self)
            self._grips.append(grip)
            grip.raise_()

        self._position_grips()

    # ── FEATURE: Row 3 collapse/expand ──

    def _toggle_row3(self):
        """▾ desliza a div 3 para baixo (colapsa). ▴ desliza de volta."""
        self._row3_visible = not self._row3_visible

        # Captura a altura atual do conteúdo antes de animar
        if self._row3_expanded_height == 0:
            self._row3_expanded_height = self._row3_content.height()

        target_height = self._row3_expanded_height if self._row3_visible else 0

        anim = QPropertyAnimation(self._row3_content, b"maximumHeight", self)
        anim.setDuration(250)
        anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
        anim.setStartValue(self._row3_content.height())
        anim.setEndValue(target_height)

        if self._row3_visible:
            # Ao expandir, garante que o widget está visível antes de animar
            self._row3_content.setVisible(True)
            self._row3_collapse_btn.setText("▾")
            self._row3_collapse_btn.setToolTip("Esconder painel auxiliar")
        else:
            self._row3_collapse_btn.setText("▴")
            self._row3_collapse_btn.setToolTip("Mostrar painel auxiliar")
            # Ao colapsar, esconde depois que a animação terminar
            anim.finished.connect(lambda: self._row3_content.setVisible(False))

        # Remove o limite de maxHeight ao expandir, depois da animação
        if self._row3_visible:
            anim.finished.connect(lambda: self._row3_content.setMaximumHeight(16777215))

        anim.start()
        self._row3_anim = anim  # manter referência para GC não matar

    # ── FEATURE: Forge Pick toggle (sidebar integrada) ──

    def _toggle_forge_pick(self):
        """◂ desliza o Forge Pick para dentro da div 1. ▸ desliza de volta."""
        visible = self._row1.toggle_sidebar_panel()
        if visible:
            self._forge_pick_btn.setText("▸")
            self._forge_pick_btn.setToolTip("Fechar Forge Pick")
        else:
            self._forge_pick_btn.setText("◂")
            self._forge_pick_btn.setToolTip("Abrir Forge Pick")

    # ── Edge grip positioning (original) ──

    def _position_grips(self):
        """Posiciona os 8 grips nas bordas/cantos da janela."""
        w, h = self.width(), self.height()
        g = _GRIP

        for grip in self._grips:
            e = grip._edge
            if e == "l":
                grip.setGeometry(0, g, g, h - 2 * g)
            elif e == "r":
                grip.setGeometry(w - g, g, g, h - 2 * g)
            elif e == "t":
                grip.setGeometry(g, 0, w - 2 * g, g)
            elif e == "b":
                grip.setGeometry(g, h - g, w - 2 * g, g)
            elif e == "tl":
                grip.setGeometry(0, 0, g, g)
            elif e == "tr":
                grip.setGeometry(w - g, 0, g, g)
            elif e == "bl":
                grip.setGeometry(0, h - g, g, g)
            elif e == "br":
                grip.setGeometry(w - g, h - g, g, g)

    def resizeEvent(self, event):
        self._position_grips()
        super().resizeEvent(event)

    def changeEvent(self, event):
        """Esconde grips quando maximizado, mostra quando normal."""
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            visible = not self.isMaximized()
            for grip in self._grips:
                grip.setVisible(visible)

    def closeEvent(self, event):
        self._engine.cleanup()
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Forging Tools")
    app.setStyleSheet(app_stylesheet())

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
