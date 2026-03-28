#!/usr/bin/env python3
"""Forging Tools — Visualize 2 WhatsApps + 2 páginas auxiliares em tela vertical."""
import json
import os
import sys
from pathlib import Path

_TIMERS_FILE = Path.home() / ".forging-tools" / "timers.json"
_URLS_FILE = Path.home() / ".forging-tools" / "mini_urls.json"
_PROGRESS_FILE = Path.home() / ".forging-tools" / "progress.json"

# Remote debugging — abra chrome://inspect ou http://localhost:9222 para ver console JS
os.environ["QTWEBENGINE_REMOTE_DEBUGGING"] = "9222"

# Flags do Chromium ANTES de importar Qt — remove sinais de automação
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = " ".join([
    "--disable-blink-features=AutomationControlled",
    "--disable-features=IsolateOrigins,site-per-process,WebRtcHideLocalIpsWithMdns",
    "--disable-site-isolation-trials",
    "--enable-features=WebRTCPipeWireCapturer,FileSystemAccessAPI,FileHandlingAPI,SharedArrayBuffer,OffscreenCanvas",
    "--autoplay-policy=no-user-gesture-required",
    "--enable-clipboard-read-write",
])

from PySide6.QtCore import Qt, QPoint, QRect, QUrl, QEvent, QPropertyAnimation, QEasingCurve, Signal, QTimer, QDateTime
from PySide6.QtGui import QColor, QMouseEvent, QPainter
from PySide6.QtWidgets import (
    QApplication,
    QDateTimeEdit,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from browser_engine import BrowserEngine
from design_tokens import (
    app_stylesheet,
    ACCENT, ACCENT_DARK, ACCENT_HOVER, BG, BORDER, BORDER_LIGHT,
    ERROR, FONT_MONO, R_LG, R_SM, SUCCESS,
    SURFACE, SURFACE_HOVER, TEXT, TEXT_SEC,
)
from forge_pick_panel import ForgePickPanel

_GRIP = 6  # largura das grip zones nas bordas
_WHATSAPP_URL = "https://web.whatsapp.com"
_CORGNATI_URL = "https://www.corgnati.com"
_DEFAULT_URL = "https://www.google.com"
_CLAUDE_URL = "https://claude.ai/settings/usage"


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

        self.page_btn1 = QPushButton("①")
        self.page_btn1.setObjectName("sidebar_btn")
        self.page_btn1.setCursor(Qt.CursorShape.PointingHandCursor)
        self.page_btn1.setToolTip("Página 1")
        layout.addWidget(self.page_btn1)

        self.page_btn2 = QPushButton("②")
        self.page_btn2.setObjectName("sidebar_btn")
        self.page_btn2.setCursor(Qt.CursorShape.PointingHandCursor)
        self.page_btn2.setToolTip("Página 2")
        layout.addWidget(self.page_btn2)

        self.page_btn3 = QPushButton("③")
        self.page_btn3.setObjectName("sidebar_btn")
        self.page_btn3.setCursor(Qt.CursorShape.PointingHandCursor)
        self.page_btn3.setToolTip("Página 3 (localhost:3000)")
        layout.addWidget(self.page_btn3)

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

    def __init__(self, label: str, engine: BrowserEngine, slot_id: str,
                 url1: str = _WHATSAPP_URL, url2: str = _CORGNATI_URL,
                 url3: str = "http://localhost:3000", parent=None):
        super().__init__(parent)
        self._url1 = url1
        self._url2 = url2
        self._url3 = url3
        self._sidebar_panel = None
        self._sidebar_border = None
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
        self.header.page_btn1.clicked.connect(lambda: self._load_page(self._url1))
        self.header.page_btn2.clicked.connect(lambda: self._load_page(self._url2))
        self.header.page_btn3.clicked.connect(lambda: self._load_page(self._url3))

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

        # Borda decorativa de alto relevo à direita do painel
        border = QFrame()
        border.setFixedWidth(5)
        border.setVisible(False)
        border.setStyleSheet(
            "background: qlineargradient(x1:0, y1:0, x2:1, y2:0, "
            f"stop:0 {BORDER}, stop:0.35 {TEXT_SEC}, stop:0.65 {BORDER}, stop:1 {BG});"
        )
        self._sidebar_border = border
        self._content_layout.insertWidget(1, border)

    def toggle_sidebar_panel(self):
        """Slide the sidebar panel in/out horizontally."""
        if not self._sidebar_panel:
            return
        self._sidebar_visible = not self._sidebar_visible
        panel = self._sidebar_panel
        target_w = self._sidebar_width

        # Garante que minimumWidth não bloqueie a animação
        panel.setMinimumWidth(0)

        if self._sidebar_visible:
            panel.setVisible(True)

        anim = QPropertyAnimation(panel, b"maximumWidth", self)
        anim.setDuration(200)
        anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
        anim.setStartValue(panel.maximumWidth())
        anim.setEndValue(target_w if self._sidebar_visible else 0)

        if not self._sidebar_visible:
            anim.finished.connect(lambda: (
                panel.setVisible(False),
                self._sidebar_border.setVisible(False) if self._sidebar_border else None,
            ))
        else:
            # setFixedWidth trava min e max no mesmo valor — impede o layout de
            # colapsar o painel quando view.load() dispara eventos de relayout
            anim.finished.connect(lambda: (
                panel.setFixedWidth(target_w),
                self._sidebar_border.setVisible(True) if self._sidebar_border else None,
            ))

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

    def _load_page(self, url: str):
        self.view.load(QUrl(url))

    def _navigate_url(self):
        url = self._url_bar.text().strip()
        if url and not url.startswith(("http://", "https://")):
            url = "https://" + url
        if url:
            self.view.load(QUrl(url))


class _CountdownDisplay(QFrame):
    """Relógio digital de contagem regressiva. Clicável para reabrir modal."""

    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("countdown_frame")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Clique para alterar o temporizador")
        self.setFixedHeight(22)

        inner = QHBoxLayout(self)
        inner.setContentsMargins(7, 0, 7, 0)
        inner.setSpacing(0)

        # Parte "Xd " — metade do tamanho da fonte do tempo (7px vs 14px)
        self._day_lbl = QLabel()
        self._day_lbl.setObjectName("cd_day")
        self._day_lbl.setVisible(False)
        inner.addWidget(self._day_lbl)

        # Parte HH:MM:SS
        self._time_lbl = QLabel("--:--:--")
        self._time_lbl.setObjectName("cd_time")
        inner.addWidget(self._time_lbl)

        self._apply_styles(expired=False)

    def _apply_styles(self, expired: bool):
        color = ERROR if expired else ACCENT_DARK
        self.setStyleSheet(
            f"QFrame#countdown_frame {{ background: {BG}; border: 1px solid {color}; "
            f"border-radius: {R_SM}px; }}"
        )
        self._day_lbl.setStyleSheet(
            f"QLabel#cd_day {{ color: {color}; font-family: {FONT_MONO}; "
            f"font-size: 10px; background: transparent; padding: 0; }}"
        )
        self._time_lbl.setStyleSheet(
            f"QLabel#cd_time {{ color: {color}; font-family: {FONT_MONO}; "
            f"font-size: 14px; font-weight: bold; background: transparent; padding: 0; "
            f"letter-spacing: 1px; }}"
        )

    def update_display(self, total_seconds: int):
        expired = total_seconds <= 0
        self._apply_styles(expired)

        if expired:
            self._day_lbl.setVisible(False)
            self._time_lbl.setText("00:00:00")
            return

        days = total_seconds // 86400
        rem = total_seconds % 86400
        h = rem // 3600
        rem %= 3600
        m = rem // 60
        s = rem % 60

        if days > 0:
            self._day_lbl.setText(f"{days}d ")
            self._day_lbl.setVisible(True)
        else:
            self._day_lbl.setVisible(False)

        self._time_lbl.setText(f"{h:02d}:{m:02d}:{s:02d}")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class TimerModal(QDialog):
    """Modal para definir data/hora do temporizador de contagem regressiva."""

    def __init__(self, target_dt=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Temporizador")
        self.setFixedSize(330, 130)
        self.setModal(True)
        self.setStyleSheet(
            f"QDialog {{ background: {SURFACE}; border: 1px solid {BORDER}; "
            f"border-radius: {R_LG}px; }}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 14, 20, 14)
        layout.setSpacing(10)

        lbl = QLabel("Data e hora de término:")
        lbl.setStyleSheet(f"color: {TEXT_SEC}; font-size: 12px; background: transparent;")
        layout.addWidget(lbl)

        self._dt_edit = QDateTimeEdit(self)
        self._dt_edit.setCalendarPopup(True)
        self._dt_edit.setDisplayFormat("dd/MM/yyyy  HH:mm:ss")
        if target_dt:
            self._dt_edit.setDateTime(target_dt)
        else:
            self._dt_edit.setDateTime(QDateTime.currentDateTime().addSecs(3600))
        self._dt_edit.setStyleSheet(
            f"QDateTimeEdit {{ background: {BG}; border: 1px solid {BORDER}; "
            f"border-radius: {R_SM}px; color: {TEXT}; font-family: {FONT_MONO}; "
            f"font-size: 13px; padding: 4px 8px; }}"
            f"QDateTimeEdit::drop-down {{ border: none; width: 20px; }}"
        )
        layout.addWidget(self._dt_edit)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addStretch()

        cancel_btn = QPushButton("Cancelar")
        cancel_btn.setFixedSize(84, 28)
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; border: 1px solid {BORDER}; "
            f"color: {TEXT_SEC}; font-size: 12px; border-radius: {R_SM}px; }}"
            f"QPushButton:hover {{ background: {SURFACE_HOVER}; }}"
        )
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        ok_btn = QPushButton("Iniciar")
        ok_btn.setFixedSize(84, 28)
        ok_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        ok_btn.setStyleSheet(
            f"QPushButton {{ background: {ACCENT}; border: none; color: {BG}; "
            f"font-size: 12px; font-weight: bold; border-radius: {R_SM}px; }}"
            f"QPushButton:hover {{ background: {ACCENT_HOVER}; }}"
        )
        ok_btn.clicked.connect(self.accept)
        btn_row.addWidget(ok_btn)

        layout.addLayout(btn_row)

    def selected_datetime(self):
        return self._dt_edit.dateTime()


class ProgressModal(QDialog):
    """Modal para configurar barra de progresso com início e término."""

    def __init__(self, start_dt=None, end_dt=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Barra de Progresso")
        self.setFixedSize(330, 180)
        self.setModal(True)
        self.setStyleSheet(
            f"QDialog {{ background: {SURFACE}; border: 1px solid {BORDER}; "
            f"border-radius: {R_LG}px; }}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 14, 20, 14)
        layout.setSpacing(8)

        lbl_start = QLabel("Início do processo:")
        lbl_start.setStyleSheet(f"color: {TEXT_SEC}; font-size: 12px; background: transparent;")
        layout.addWidget(lbl_start)

        self._start_edit = QDateTimeEdit(self)
        self._start_edit.setCalendarPopup(True)
        self._start_edit.setDisplayFormat("dd/MM/yyyy  HH:mm:ss")
        self._start_edit.setDateTime(start_dt if start_dt else QDateTime.currentDateTime())
        self._start_edit.setStyleSheet(
            f"QDateTimeEdit {{ background: {BG}; border: 1px solid {BORDER}; "
            f"border-radius: {R_SM}px; color: {TEXT}; font-family: {FONT_MONO}; "
            f"font-size: 13px; padding: 4px 8px; }}"
            f"QDateTimeEdit::drop-down {{ border: none; width: 20px; }}"
        )
        layout.addWidget(self._start_edit)

        lbl_end = QLabel("Término do processo:")
        lbl_end.setStyleSheet(f"color: {TEXT_SEC}; font-size: 12px; background: transparent;")
        layout.addWidget(lbl_end)

        self._end_edit = QDateTimeEdit(self)
        self._end_edit.setCalendarPopup(True)
        self._end_edit.setDisplayFormat("dd/MM/yyyy  HH:mm:ss")
        self._end_edit.setDateTime(end_dt if end_dt else QDateTime.currentDateTime().addSecs(3600))
        self._end_edit.setStyleSheet(
            f"QDateTimeEdit {{ background: {BG}; border: 1px solid {BORDER}; "
            f"border-radius: {R_SM}px; color: {TEXT}; font-family: {FONT_MONO}; "
            f"font-size: 13px; padding: 4px 8px; }}"
            f"QDateTimeEdit::drop-down {{ border: none; width: 20px; }}"
        )
        layout.addWidget(self._end_edit)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addStretch()

        cancel_btn = QPushButton("Cancelar")
        cancel_btn.setFixedSize(84, 28)
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; border: 1px solid {BORDER}; "
            f"color: {TEXT_SEC}; font-size: 12px; border-radius: {R_SM}px; }}"
            f"QPushButton:hover {{ background: {SURFACE_HOVER}; }}"
        )
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        ok_btn = QPushButton("Confirmar")
        ok_btn.setFixedSize(84, 28)
        ok_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        ok_btn.setStyleSheet(
            f"QPushButton {{ background: {ACCENT}; border: none; color: {BG}; "
            f"font-size: 12px; font-weight: bold; border-radius: {R_SM}px; }}"
            f"QPushButton:hover {{ background: {ACCENT_HOVER}; }}"
        )
        ok_btn.clicked.connect(self.accept)
        btn_row.addWidget(ok_btn)

        layout.addLayout(btn_row)

    def selected_start(self):
        return self._start_edit.dateTime()

    def selected_end(self):
        return self._end_edit.dateTime()


class _ProgressWidget(QProgressBar):
    """Barra de progresso clicável estilizada com tema dourado escuro."""

    from PySide6.QtCore import Signal
    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setRange(0, 100)
        self.setValue(0)
        self.setFormat("%p%")
        self.setTextVisible(False)  # texto desenhado manualmente com contorno
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(22)
        self.setMinimumWidth(70)
        self.setToolTip("Clique para editar / limpar quando concluído")
        self._done = False
        self._apply_style(done=False)

    def _apply_style(self, done: bool):
        bar_color = SUCCESS if done else ACCENT_DARK
        border_color = SUCCESS if done else ACCENT_DARK
        self.setStyleSheet(f"""
            QProgressBar {{
                background: {BG};
                border: 1px solid {border_color};
                border-radius: {R_SM}px;
                color: {bar_color};
                font-family: {FONT_MONO};
                font-size: 10px;
                font-weight: bold;
                text-align: center;
            }}
            QProgressBar::chunk {{
                background: {bar_color};
                border-radius: {R_SM}px;
            }}
        """)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        text = self.format().replace("%p", str(self.value()))
        rect = self.rect()
        painter.setFont(self.font())
        # contorno preto (8 direções)
        painter.setPen(QColor("#000000"))
        for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, -1), (-1, 1), (1, 1)]:
            painter.drawText(rect.translated(dx, dy), Qt.AlignmentFlag.AlignCenter, text)
        # texto na cor original por cima
        bar_color = SUCCESS if self._done else ACCENT_DARK
        painter.setPen(QColor(bar_color))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
        painter.end()

    def set_done(self, done: bool):
        self._done = done
        self._apply_style(done)
        if done:
            self.setValue(100)
            self.setToolTip("Concluído! Clique para limpar")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class MiniViewPanel(QWidget):
    """Mini browser panel com header ▼ + URL bar toggle para Row 3."""

    def __init__(self, label: str, view, panel_id: str = "", show_progress: bool = False, parent=None):
        super().__init__(parent)
        self.view = view
        self._panel_id = panel_id
        self._show_progress = show_progress
        self._slot_urls = [_DEFAULT_URL, _CLAUDE_URL]
        self._active_slot = 0
        self._target_dt = None
        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(1000)
        self._tick_timer.timeout.connect(self._on_timer_tick)

        # Progress bar state (only active when show_progress=True)
        self._prog_start_dt = None
        self._prog_end_dt = None
        self._prog_state = "none"  # "none" | "pre-start" | "active" | "done"
        self._prog_tick = QTimer(self)
        self._prog_tick.setInterval(1000)
        self._prog_tick.timeout.connect(self._on_progress_tick)

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

        self._page_btn1 = QPushButton("①")
        self._page_btn1.setObjectName("sidebar_btn")
        self._page_btn1.setCursor(Qt.CursorShape.PointingHandCursor)
        self._page_btn1.setToolTip("Página 1")
        self._page_btn1.setFixedSize(28, 22)
        self._page_btn1.setStyleSheet("font-size: 11px; padding: 2px 6px; min-width: 24px; min-height: 20px;")
        header_layout.addWidget(self._page_btn1)

        self._page_btn2 = QPushButton("②")
        self._page_btn2.setObjectName("sidebar_btn")
        self._page_btn2.setCursor(Qt.CursorShape.PointingHandCursor)
        self._page_btn2.setToolTip("Página 2")
        self._page_btn2.setFixedSize(28, 22)
        self._page_btn2.setStyleSheet("font-size: 11px; padding: 2px 6px; min-width: 24px; min-height: 20px;")
        header_layout.addWidget(self._page_btn2)

        lbl = QLabel(label)
        lbl.setObjectName("row_label")
        lbl.setStyleSheet("font-size: 11px;")
        header_layout.addWidget(lbl)
        header_layout.addStretch()

        # Botão relógio (visível quando não há timer)
        self._clock_btn = QPushButton("⏱")
        self._clock_btn.setObjectName("sidebar_btn")
        self._clock_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._clock_btn.setToolTip("Definir temporizador")
        self._clock_btn.setFixedSize(28, 22)
        self._clock_btn.setStyleSheet("font-size: 11px; padding: 2px 6px; min-width: 24px; min-height: 20px;")
        header_layout.addWidget(self._clock_btn)

        # Countdown display (visível quando timer está ativo)
        self._countdown = _CountdownDisplay()
        self._countdown.setVisible(False)
        header_layout.addWidget(self._countdown)

        # ── Progress bar widgets (apenas quando show_progress=True) ──
        if show_progress:
            # Estado inicial: botão de bateria
            self._prog_btn = QPushButton("🔋")
            self._prog_btn.setObjectName("sidebar_btn")
            self._prog_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self._prog_btn.setToolTip("Configurar barra de progresso")
            self._prog_btn.setFixedSize(28, 22)
            self._prog_btn.setStyleSheet("font-size: 11px; padding: 2px 6px; min-width: 24px; min-height: 20px;")
            self._prog_btn.clicked.connect(self._open_progress_modal)
            header_layout.addWidget(self._prog_btn)

            # Countdown para quando start_dt ainda não chegou
            self._prog_countdown = _CountdownDisplay()
            self._prog_countdown.setVisible(False)
            self._prog_countdown.setToolTip("Aguardando início — clique para editar")
            self._prog_countdown.clicked.connect(self._open_progress_modal)
            header_layout.addWidget(self._prog_countdown)

            # Barra de progresso propriamente dita
            self._prog_bar = _ProgressWidget()
            self._prog_bar.setVisible(False)
            self._prog_bar.clicked.connect(self._on_progress_bar_clicked)
            header_layout.addWidget(self._prog_bar)

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
        self._page_btn1.clicked.connect(lambda: self._switch_slot(0))
        self._page_btn2.clicked.connect(lambda: self._switch_slot(1))
        self.view.urlChanged.connect(self._on_url_changed)
        self._clock_btn.clicked.connect(self._open_timer_modal)
        self._countdown.clicked.connect(self._open_timer_modal)

        if self._panel_id:
            self._load_timer()
            self._load_urls()
            if self._show_progress:
                self._load_progress()

    def _switch_slot(self, slot: int):
        self._active_slot = slot
        self.view.load(QUrl(self._slot_urls[slot]))

    def _on_url_changed(self, url):
        url_str = url.toString()
        if url_str.startswith("http"):
            self._slot_urls[self._active_slot] = url_str
            self._save_urls()
        if self._url_bar.isVisible():
            self._url_bar.setText(url_str)

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
            self.view.load(QUrl(url))

    def _save_urls(self):
        if not self._panel_id:
            return
        try:
            data = {}
            if _URLS_FILE.exists():
                data = json.loads(_URLS_FILE.read_text(encoding="utf-8"))
            data[self._panel_id] = self._slot_urls
            _URLS_FILE.parent.mkdir(parents=True, exist_ok=True)
            _URLS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _load_urls(self):
        try:
            if not _URLS_FILE.exists():
                return
            data = json.loads(_URLS_FILE.read_text(encoding="utf-8"))
            urls = data.get(self._panel_id)
            if not urls or not isinstance(urls, list) or len(urls) < 2:
                return
            self._slot_urls = urls
            self.view.load(QUrl(urls[self._active_slot]))
        except Exception:
            pass

    def _save_timer(self):
        if not self._panel_id:
            return
        try:
            data = {}
            if _TIMERS_FILE.exists():
                data = json.loads(_TIMERS_FILE.read_text(encoding="utf-8"))
            if self._target_dt:
                data[self._panel_id] = self._target_dt.toString(Qt.DateFormat.ISODate)
            else:
                data.pop(self._panel_id, None)
            _TIMERS_FILE.parent.mkdir(parents=True, exist_ok=True)
            _TIMERS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _load_timer(self):
        try:
            if not _TIMERS_FILE.exists():
                return
            data = json.loads(_TIMERS_FILE.read_text(encoding="utf-8"))
            dt_str = data.get(self._panel_id)
            if not dt_str:
                return
            dt = QDateTime.fromString(dt_str, Qt.DateFormat.ISODate)
            if not dt.isValid() or QDateTime.currentDateTime().secsTo(dt) <= 0:
                return
            self._target_dt = dt
            self._clock_btn.setVisible(False)
            self._countdown.setVisible(True)
            self._tick_timer.start()
            self._on_timer_tick()
        except Exception:
            pass

    def _open_timer_modal(self):
        modal = TimerModal(self._target_dt, self.window())
        if modal.exec() == QDialog.DialogCode.Accepted:
            self._target_dt = modal.selected_datetime()
            self._clock_btn.setVisible(False)
            self._countdown.setVisible(True)
            self._tick_timer.start()
            self._on_timer_tick()
            self._save_timer()

    def _on_timer_tick(self):
        if not self._target_dt:
            return
        remaining = QDateTime.currentDateTime().secsTo(self._target_dt)
        self._countdown.update_display(remaining)
        if remaining <= 0:
            self._tick_timer.stop()
            self._target_dt = None
            self._save_timer()

    # ── Progress bar methods (only active when show_progress=True) ──

    def _open_progress_modal(self):
        if not self._show_progress:
            return
        modal = ProgressModal(self._prog_start_dt, self._prog_end_dt, self.window())
        if modal.exec() == QDialog.DialogCode.Accepted:
            self._prog_start_dt = modal.selected_start()
            self._prog_end_dt = modal.selected_end()
            self._save_progress()
            self._update_progress_display()
            self._prog_tick.start()
            self._on_progress_tick()

    def _on_progress_bar_clicked(self):
        """Click on the progress bar: if done, clear; otherwise open modal."""
        if self._prog_state == "done":
            self._clear_progress()
        else:
            self._open_progress_modal()

    def _on_progress_tick(self):
        if not self._show_progress or not self._prog_start_dt or not self._prog_end_dt:
            return

        now = QDateTime.currentDateTime()
        secs_to_start = now.secsTo(self._prog_start_dt)
        secs_to_end = now.secsTo(self._prog_end_dt)
        total_secs = self._prog_start_dt.secsTo(self._prog_end_dt)

        if secs_to_start > 0:
            # Before start: show countdown to start time
            if self._prog_state != "pre-start":
                self._prog_state = "pre-start"
                self._update_progress_display()
            self._prog_countdown.update_display(secs_to_start)

        elif secs_to_end > 0 and total_secs > 0:
            # Active: show progress bar
            elapsed = self._prog_start_dt.secsTo(now)
            pct = max(0, min(100, int(elapsed * 100 / total_secs)))
            if self._prog_state != "active":
                self._prog_state = "active"
                self._update_progress_display()
            self._prog_bar.setValue(pct)

        else:
            # Finished
            if self._prog_state != "done":
                self._prog_state = "done"
                self._update_progress_display()
            self._prog_tick.stop()

    def _update_progress_display(self):
        """Show/hide the correct widget based on current progress state."""
        if not self._show_progress:
            return
        state = self._prog_state
        self._prog_btn.setVisible(state == "none")
        self._prog_countdown.setVisible(state == "pre-start")
        self._prog_bar.setVisible(state in ("active", "done"))
        if state == "done":
            self._prog_bar.set_done(True)
        elif state == "active":
            self._prog_bar.set_done(False)

    def _clear_progress(self):
        """Reset progress bar to initial battery-button state."""
        self._prog_tick.stop()
        self._prog_start_dt = None
        self._prog_end_dt = None
        self._prog_state = "none"
        self._save_progress()
        self._update_progress_display()

    def _save_progress(self):
        if not self._panel_id or not self._show_progress:
            return
        try:
            data = {}
            if _PROGRESS_FILE.exists():
                data = json.loads(_PROGRESS_FILE.read_text(encoding="utf-8"))
            if self._prog_start_dt and self._prog_end_dt:
                data[self._panel_id] = {
                    "start": self._prog_start_dt.toString(Qt.DateFormat.ISODate),
                    "end": self._prog_end_dt.toString(Qt.DateFormat.ISODate),
                }
            else:
                data.pop(self._panel_id, None)
            _PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
            _PROGRESS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _load_progress(self):
        if not self._panel_id or not self._show_progress:
            return
        try:
            if not _PROGRESS_FILE.exists():
                return
            data = json.loads(_PROGRESS_FILE.read_text(encoding="utf-8"))
            entry = data.get(self._panel_id)
            if not entry:
                return
            start = QDateTime.fromString(entry.get("start", ""), Qt.DateFormat.ISODate)
            end = QDateTime.fromString(entry.get("end", ""), Qt.DateFormat.ISODate)
            if not start.isValid() or not end.isValid() or start >= end:
                return
            self._prog_start_dt = start
            self._prog_end_dt = end
            # Determine initial state
            now = QDateTime.currentDateTime()
            if now.secsTo(end) <= 0:
                self._prog_state = "done"
            elif now.secsTo(start) > 0:
                self._prog_state = "pre-start"
            else:
                self._prog_state = "active"
            self._update_progress_display()
            self._prog_tick.start()
            self._on_progress_tick()
        except Exception:
            pass


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
        self._row1.set_sidebar(self._forge_pick_panel, width=250)

        # Chevron button to toggle forge-pick sidebar
        self._forge_pick_btn = QPushButton("▸")
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

        # Row 3 content: Two QWebEngine views (sessões independentes)
        self._row3_content = QWidget()
        self._row3_content_layout = QVBoxLayout(self._row3_content)
        self._row3_content_layout.setContentsMargins(0, 0, 0, 0)
        self._row3_content_layout.setSpacing(0)

        self._row3_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._row3_splitter.setHandleWidth(6)
        self._row3_splitter.setChildrenCollapsible(False)

        view3 = self._engine.create_view(
            "slot-3", url=_CLAUDE_URL, inject_sidebar_toggle=False
        )
        self._mini3 = MiniViewPanel("", view3, panel_id="mini3")
        self._row3_splitter.addWidget(self._mini3)

        view4 = self._engine.create_view(
            "slot-4", url=_CLAUDE_URL, inject_sidebar_toggle=False
        )
        self._mini4 = MiniViewPanel("", view4, panel_id="mini4", show_progress=True)
        self._row3_splitter.addWidget(self._mini4)

        self._row3_splitter.setStretchFactor(0, 1)
        self._row3_splitter.setStretchFactor(1, 1)

        self._row3_content_layout.addWidget(self._row3_splitter)
        row3_layout.addWidget(self._row3_content)

        self._splitter.addWidget(self._row3_wrapper)

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
        """▾ colapsa a div 3 inteira no splitter. ▴ restaura."""
        self._row3_visible = not self._row3_visible

        if not self._row3_visible:
            # Salva tamanhos atuais e colapsa o wrapper para o tamanho do botão
            self._row3_saved_sizes = self._splitter.sizes()
            self._row3_content.setVisible(False)
            self._row3_collapse_btn.setText("▴")
            self._row3_collapse_btn.setToolTip("Mostrar painel auxiliar")
            btn_h = 20
            # Trava o wrapper no tamanho mínimo (só o botão)
            self._row3_wrapper.setMinimumHeight(btn_h)
            self._row3_wrapper.setMaximumHeight(btn_h)
            s = self._row3_saved_sizes
            if len(s) >= 3 and s[2] > btn_h:
                extra = s[2] - btn_h
                self._splitter.setSizes([s[0] + extra // 2, s[1] + extra - extra // 2, btn_h])
        else:
            # Remove restrições e restaura tamanhos salvos
            self._row3_wrapper.setMinimumHeight(0)
            self._row3_wrapper.setMaximumHeight(16777215)
            self._row3_content.setVisible(True)
            self._row3_collapse_btn.setText("▾")
            self._row3_collapse_btn.setToolTip("Esconder painel auxiliar")
            if hasattr(self, '_row3_saved_sizes'):
                self._splitter.setSizes(self._row3_saved_sizes)

    # ── FEATURE: Forge Pick toggle (sidebar integrada) ──

    def _toggle_forge_pick(self):
        """▸ desliza o Forge Pick para dentro da div 1. ◂ desliza de volta."""
        visible = self._row1.toggle_sidebar_panel()
        if visible:
            self._forge_pick_btn.setText("◂")
            self._forge_pick_btn.setToolTip("Fechar Forge Pick")
        else:
            self._forge_pick_btn.setText("▸")
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
