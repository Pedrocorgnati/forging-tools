"""Design tokens — Warm Charcoal Gold (dark mode)."""


# ── Colors ──
BG = "#1C1917"
SURFACE = "#292524"
SURFACE_HOVER = "#44403C"
SURFACE_ELEVATED = "#44403C"
BORDER = "#57534E"
BORDER_LIGHT = "#44403C"
ACCENT = "#D4A574"
ACCENT_HOVER = "#E8C07D"
ACCENT_DARK = "#B4844C"
TEXT = "#FAFAF9"
TEXT_SEC = "#A8A29E"
TEXT_TERT = "#78716C"
ERROR = "#FB7185"
SUCCESS = "#34D399"

# ── Typography ──
FONT_FAMILY = "Inter, Segoe UI, system-ui, -apple-system, sans-serif"
FONT_MONO = "JetBrains Mono, Consolas, monospace"

# ── Radii ──
R_SM = 4
R_MD = 6
R_LG = 8
R_XL = 12

# ── Grip dots color ──
GRIP = "#57534E"
GRIP_HOVER = "#78716C"


def app_stylesheet() -> str:
    """Global QSS for the entire application."""
    return f"""
    /* ── Base ── */
    QWidget {{
        background-color: {BG};
        color: {TEXT};
        font-family: {FONT_FAMILY};
        font-size: 13px;
    }}
    QLabel {{
        background-color: transparent;
    }}

    /* ── Title bar ── */
    QWidget#title_bar {{
        background-color: {SURFACE};
        border-bottom: 1px solid {BORDER_LIGHT};
    }}
    QLabel#title_label {{
        color: {ACCENT};
        font-size: 14px;
        font-weight: 700;
        background: transparent;
    }}
    QPushButton#title_btn {{
        background: transparent;
        border: none;
        color: {TEXT_SEC};
        font-size: 16px;
        padding: 6px 12px;
        border-radius: {R_SM}px;
    }}
    QPushButton#title_btn:hover {{
        background-color: {SURFACE_HOVER};
        color: {TEXT};
    }}
    QPushButton#close_btn:hover {{
        background-color: {ERROR};
        color: {TEXT};
    }}

    /* ── URL bar ── */
    QLineEdit#url_bar {{
        background-color: {SURFACE};
        border: none;
        border-bottom: 1px solid {BORDER_LIGHT};
        border-radius: 0;
        padding: 4px 12px;
        color: {TEXT};
        font-size: 12px;
        font-family: {FONT_MONO};
        selection-background-color: {ACCENT}40;
    }}
    QLineEdit#url_bar:focus {{
        border-bottom: 1px solid {ACCENT};
    }}

    /* ── Row headers ── */
    QFrame#row_header {{
        background-color: {SURFACE};
        border-bottom: 1px solid {BORDER_LIGHT};
        padding: 2px 0 4px 0;
    }}
    QLabel#row_label {{
        color: {TEXT};
        font-size: 12px;
        font-weight: 600;
        background: transparent;
        padding-left: 12px;
    }}
    QPushButton#sidebar_btn {{
        background: transparent;
        border: 1px solid {BORDER};
        color: {ACCENT};
        font-size: 15px;
        padding: 4px 10px;
        border-radius: {R_MD}px;
        min-width: 32px;
        min-height: 24px;
    }}
    QPushButton#sidebar_btn:hover {{
        background-color: {SURFACE_HOVER};
        border-color: {ACCENT};
        color: {ACCENT_HOVER};
    }}
    QPushButton#sidebar_btn:pressed {{
        background-color: {ACCENT_DARK};
        color: {BG};
    }}

    /* ── Row 3 chevron (barra fina entre row 2 e row 3) ── */
    QPushButton#row3_chevron {{
        background-color: {SURFACE};
        border: none;
        border-top: 1px solid {BORDER_LIGHT};
        border-bottom: 1px solid {BORDER_LIGHT};
        color: {TEXT_SEC};
        font-size: 14px;
        padding: 0;
    }}
    QPushButton#row3_chevron:hover {{
        background-color: {SURFACE_HOVER};
        color: {ACCENT};
    }}

    /* ── Splitter ── */
    QSplitter::handle {{
        background-color: {BORDER_LIGHT};
    }}
    QSplitter::handle:vertical {{
        height: 6px;
        background: qlineargradient(
            x1:0, y1:0, x2:1, y2:0,
            stop:0 {BG}, stop:0.3 {GRIP}, stop:0.5 {GRIP_HOVER},
            stop:0.7 {GRIP}, stop:1 {BG}
        );
        border-top: 1px solid {BORDER_LIGHT};
        border-bottom: 1px solid {BORDER_LIGHT};
    }}
    QSplitter::handle:horizontal {{
        width: 6px;
        background: qlineargradient(
            x1:0, y1:0, x2:0, y2:1,
            stop:0 {BG}, stop:0.3 {GRIP}, stop:0.5 {GRIP_HOVER},
            stop:0.7 {GRIP}, stop:1 {BG}
        );
        border-left: 1px solid {BORDER_LIGHT};
        border-right: 1px solid {BORDER_LIGHT};
    }}
    QSplitter::handle:hover {{
        background-color: {ACCENT_DARK};
    }}

    /* ── Scrollbar ── */
    QScrollBar:vertical {{
        background: transparent;
        width: 8px;
    }}
    QScrollBar::handle:vertical {{
        background: {SURFACE_HOVER};
        border-radius: 4px;
        min-height: 24px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {BORDER};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0;
    }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
        background: transparent;
    }}
    """
