"""Registro de testid para widgets tkinter (Forge Pick).

tkinter nao tem `data-testid` nativo: este modulo guarda, por widget, um
testid com prefixo `fp-` e remove a entrada quando o widget e destruido.
Sem UI e sem import de `app` (o overlay DataTest consome `registered_widgets`).
"""

from __future__ import annotations

import re
import sys
import tkinter as tk
from tkinter import ttk

TESTID_PREFIX = "fp-"
_TESTID_RE = re.compile(r"^fp-[a-z0-9]+(?:-[a-z0-9]+)*$")

# path Tk do widget -> (widget, testid)
_REGISTRY: dict[str, tuple[object, str]] = {}
# paths cujo widget ja recebeu o bind <Destroy> deste modulo -> objeto widget
_BOUND: dict[str, object] = {}


def _validate_testid(testid) -> None:
    if not isinstance(testid, str):
        raise ValueError(f"testid deve ser str com prefixo 'fp-'; recebido: {testid!r}")
    if not _TESTID_RE.match(testid):
        raise ValueError(
            "testid invalido: use 'fp-' seguido de partes [a-z0-9] separadas por '-'; "
            f"recebido: {testid!r}"
        )


def _widget_alive(widget) -> bool:
    try:
        return bool(widget.winfo_exists())
    except tk.TclError:
        return False


def _make_destroy_handler(path: str, widget):
    def _on_destroy(event) -> None:
        # <Destroy> de Tk/Toplevel tambem chega pelos filhos (bindtags):
        # so remove quando o evento e do proprio widget registrado.
        if str(event.widget) != path:
            return
        entry = _REGISTRY.get(path)
        if entry is not None and entry[0] is widget:
            del _REGISTRY[path]
        if _BOUND.get(path) is widget:
            del _BOUND[path]

    return _on_destroy


def register_testid(widget, testid):
    """Registra `testid` em `widget` e devolve o proprio widget."""
    _validate_testid(testid)
    if not _widget_alive(widget):
        raise ValueError(f"widget inexistente ou destruido ao registrar testid {testid!r}")
    path = str(widget)
    _REGISTRY[path] = (widget, testid)
    if _BOUND.get(path) is not widget:
        widget.bind("<Destroy>", _make_destroy_handler(path, widget), add="+")
        _BOUND[path] = widget
    return widget


def testid_of(widget) -> str | None:
    """Testid registrado para `widget`, ou None (nao registrado ou destruido)."""
    entry = _REGISTRY.get(str(widget))
    if entry is None or entry[0] is not widget or not _widget_alive(widget):
        return None
    return entry[1]


def registered_widgets() -> list[tuple[str, object]]:
    """Pares (testid, widget) vivos, ordenados por (testid, path do widget)."""
    alive = [
        (testid, widget)
        for path, (widget, testid) in list(_REGISTRY.items())
        if _widget_alive(widget)
    ]
    return sorted(alive, key=lambda item: (item[0], str(item[1])))


def live_testids() -> list[str]:
    """Testids vivos, unicos e ordenados."""
    return sorted({testid for testid, _widget in registered_widgets()})


def testid_slug(texto) -> str:
    """Converte texto livre em parte de testid: 'Vs code' -> 'vs-code'."""
    slug = re.sub(r"[^a-z0-9]+", "-", str(texto).lower()).strip("-")
    return slug or "sem-nome"


def _reset_registry() -> None:
    """Esvazia o registro (uso exclusivo de testes)."""
    _REGISTRY.clear()
    _BOUND.clear()


# ── overlay DataTest (item 013) ──────────────────────────────────────────────

MODE_OFF = "off"
MODE_MAIN = "main"
MODE_BODY = "body"
MODE_BUTTONS = "buttons"
_MODES = (MODE_OFF, MODE_MAIN, MODE_BODY, MODE_BUTTONS)

MAIN_TESTIDS = frozenset(
    {
        "fp-header",
        "fp-navbar",
        "fp-tab-forge-pick",
        "fp-tab-timers",
        "fp-forge-pick-list",
        "fp-forge-pick-favorites",
        "fp-daily-section",
        "fp-weekly-section",
        "fp-monthly-section",
        "fp-timers-warning",
    }
)
NATIVE_BUTTON_CLASSES = (
    tk.Button,
    tk.Checkbutton,
    tk.Radiobutton,
    ttk.Button,
    ttk.Checkbutton,
    ttk.Radiobutton,
)

# Paleta Catppuccin Mocha espelhada de `app.py` (item 014, D1): mesmos nomes e
# mesmos valores, sem importar o modulo da janela (import circular). Unico bloco do arquivo com
# literais hex; `LABEL_FONT` fica como estava (D8).
BG = "#1e1e2e"
MANTLE = "#181825"
SURFACE = "#313244"
HOVER = "#45475a"
FG = "#cdd6f4"
MUTED = "#6c7086"
ACCENT = "#89b4fa"
GREEN = "#a6e3a1"
YELLOW = "#f9e2af"
VIOLET = "#b4befe"
CYAN = "#89dceb"
ORANGE = "#fab387"
RADIUS = 6

# Constantes do overlay pelos nomes da paleta (item 014, D7).
MODE_COLORS = {"main": GREEN, "body": VIOLET, "buttons": ACCENT, "px": YELLOW}
PANEL_BG = BG
LABEL_INK = BG
BTN_ACTIVE_FG = BG
BTN_INACTIVE_BG = SURFACE
BTN_INACTIVE_FG = FG
COPY_OK_BG = GREEN
COPY_FAIL_BG = ORANGE
LABEL_FONT = ("DejaVu Sans", 7)
LABEL_OFFSET_Y = 14
LABEL_MAX_STEPS = 20
REFRESH_DEBOUNCE_MS = 150
COPY_FLASH_MS = 600
PX_RULER_WIDTHS = (10, 50, 100)
PX_RULER_HEIGHT = 20
PX_RULER_MARGIN = 12
PX_RULER_GAP = 4
PANEL_GAP_Y = 4


def is_button_widget(widget, button_classes=()) -> bool:
    """True para botao nativo ou de uma classe injetada pelo app."""
    if isinstance(widget, NATIVE_BUTTON_CLASSES):
        return True
    injected = tuple(button_classes)
    return bool(injected) and isinstance(widget, injected)


def _chain_visible(widget, root) -> bool:
    """Todo nivel do widget ate o root tem gerenciador de geometria."""
    current = widget
    while current is not root:
        if current is None or not current.winfo_manager():
            return False
        current = current.master
    return True


def overlay_candidates(root) -> list[tuple[str, object]]:
    """Pares (testid, widget) vivos, do root, com cadeia visivel ate o root."""
    result = []
    for testid, widget in registered_widgets():
        try:
            if widget.winfo_toplevel() is not root:
                continue
            if not _chain_visible(widget, root):
                continue
        except tk.TclError:
            continue
        result.append((testid, widget))
    return result


def select_targets(mode, candidates, button_classes=()) -> list[tuple[str, object]]:
    """Filtra os candidatos pelo modo: main (estruturais), body (nao botoes) ou buttons."""
    if mode not in _MODES:
        raise ValueError(f"modo DataTest desconhecido: {mode!r}")
    if mode == MODE_OFF:
        return []
    if mode == MODE_MAIN:
        return [c for c in candidates if c[0] in MAIN_TESTIDS]
    want_button = mode == MODE_BUTTONS
    return [c for c in candidates if is_button_widget(c[1], button_classes) == want_button]


def _paint_colors(widget, **options) -> None:
    """Aplica em `widget` apenas as opcoes de cor que ele expoe em widget.keys() (D10)."""
    keys = set(widget.keys())
    config = {name: value for name, value in options.items() if name in keys}
    if config:
        widget.configure(**config)


class DataTestController:
    """Painel flutuante DataTest: etiquetas de testid, copia por clique e reguas de px."""

    def __init__(self, root, button_classes=(), on_panel_change=None) -> None:
        self.root = root
        self._button_classes = tuple(button_classes)
        self._on_panel_change = on_panel_change
        self.anchor_widget = None
        self.mode = MODE_OFF
        self.px_ruler_on = False
        self.panel = None
        self._mode_buttons: dict[str, tk.Button] = {}
        self._px_button = None
        self._labels: list[tuple[str, tk.Label]] = []
        self._rulers: list[tk.Label] = []
        self._after_id = None
        # flash de copia pendente por etiqueta: str(label) -> (texto, cor, after_id)
        self._flash: dict[str, tuple[str, str, object]] = {}
        self._drag_offset = (0, 0)
        root.bind("<Configure>", self._on_root_configure, add="+")

    # ── painel ───────────────────────────────────────────────────────────────

    @property
    def is_panel_open(self) -> bool:
        if self.panel is None:
            return False
        try:
            return bool(self.panel.winfo_exists())
        except tk.TclError:
            return False

    def _notify(self, opened: bool) -> None:
        if self._on_panel_change is not None:
            self._on_panel_change(opened)

    def open_panel(self):
        if self.is_panel_open:
            self.panel.lift()
            return self.panel
        panel = tk.Toplevel(self.root)
        panel.overrideredirect(True)
        try:
            panel.attributes("-topmost", True)
        except tk.TclError:
            pass
        _paint_colors(
            panel,
            bg=PANEL_BG, fg=FG,
            activebackground=PANEL_BG, activeforeground=FG,
            disabledforeground=MUTED,
            highlightbackground=PANEL_BG, highlightcolor=PANEL_BG,
        )
        register_testid(panel, "fp-datatest-floating-panel")

        handle = tk.Label(
            panel, text="DataTest", bg=BTN_INACTIVE_BG, fg=BTN_INACTIVE_FG,
            font=LABEL_FONT, cursor="fleur",
        )
        _paint_colors(
            handle,
            bg=BTN_INACTIVE_BG, fg=BTN_INACTIVE_FG,
            activebackground=BTN_INACTIVE_BG, activeforeground=BTN_INACTIVE_FG,
            disabledforeground=MUTED,
            highlightbackground=BTN_INACTIVE_BG, highlightcolor=BTN_INACTIVE_BG,
        )
        handle.pack(fill="x")
        register_testid(handle, "fp-datatest-panel-handle")
        handle.bind("<ButtonPress-1>", self._on_drag_press)
        handle.bind("<B1-Motion>", self._on_drag_motion)

        self._mode_buttons = {}
        for mode, text, testid in (
            (MODE_MAIN, "Main", "fp-datatest-mode-main"),
            (MODE_BODY, "Body", "fp-datatest-mode-body"),
            (MODE_BUTTONS, "Btn", "fp-datatest-mode-btn"),
        ):
            btn = tk.Button(
                panel, text=text, command=lambda m=mode: self.on_mode_click(m),
                relief="flat", bd=0, padx=8, pady=2,
            )
            btn.pack(fill="x", padx=4, pady=(4, 0))
            register_testid(btn, testid)
            self._mode_buttons[mode] = btn
        self._px_button = tk.Button(
            panel, text="px ruler", command=self.toggle_px_ruler, relief="flat", bd=0,
            padx=8, pady=2,
        )
        self._px_button.pack(fill="x", padx=4, pady=4)
        register_testid(self._px_button, "fp-datatest-px-ruler-toggle")

        self.panel = panel
        self._sync_buttons()
        self._place_panel(panel)
        self._notify(True)
        return panel

    def _place_panel(self, panel) -> None:
        panel.update_idletasks()
        width = panel.winfo_reqwidth()
        anchor = self.anchor_widget
        try:
            if anchor is not None and anchor.winfo_exists():
                x = anchor.winfo_rootx() + anchor.winfo_width() - width
                y = anchor.winfo_rooty() + anchor.winfo_height() + PANEL_GAP_Y
            else:
                x = self.root.winfo_rootx() + self.root.winfo_width() - width
                y = self.root.winfo_rooty() + PANEL_GAP_Y
        except tk.TclError:
            return
        panel.geometry(f"+{max(x, 0)}+{max(y, 0)}")

    def close_panel(self) -> None:
        panel = self.panel
        self.panel = None
        self._mode_buttons = {}
        self._px_button = None
        self.mode = MODE_OFF
        self.px_ruler_on = False
        self._clear_labels()
        self._clear_rulers()
        if panel is not None:
            try:
                panel.destroy()
            except tk.TclError:
                pass
            self._notify(False)

    def toggle_panel(self) -> None:
        if self.is_panel_open:
            self.close_panel()
        else:
            self.open_panel()

    def _on_drag_press(self, event) -> None:
        if self.panel is None:
            return
        self._drag_offset = (event.x_root - self.panel.winfo_x(), event.y_root - self.panel.winfo_y())

    def _on_drag_motion(self, event) -> None:
        if self.panel is None:
            return
        dx, dy = self._drag_offset
        self.panel.geometry(f"+{event.x_root - dx}+{event.y_root - dy}")

    def _sync_buttons(self) -> None:
        for mode, btn in self._mode_buttons.items():
            self._paint_button(btn, MODE_COLORS[mode], self.mode == mode)
        if self._px_button is not None:
            self._paint_button(self._px_button, MODE_COLORS["px"], self.px_ruler_on)

    @staticmethod
    def _paint_button(btn, color, active) -> None:
        try:
            if active:
                _paint_colors(
                    btn,
                    bg=color, fg=BTN_ACTIVE_FG,
                    activebackground=color, activeforeground=BTN_ACTIVE_FG,
                    disabledforeground=MUTED,
                    highlightbackground=color, highlightcolor=color,
                )
            else:
                _paint_colors(
                    btn,
                    bg=BTN_INACTIVE_BG, fg=BTN_INACTIVE_FG,
                    activebackground=BTN_INACTIVE_BG, activeforeground=BTN_INACTIVE_FG,
                    disabledforeground=MUTED,
                    highlightbackground=BTN_INACTIVE_BG, highlightcolor=BTN_INACTIVE_BG,
                )
        except tk.TclError:
            pass

    # ── modos ────────────────────────────────────────────────────────────────

    def set_mode(self, mode) -> None:
        if mode not in _MODES:
            raise ValueError(f"modo DataTest desconhecido: {mode!r}")
        self.mode = mode
        self._sync_buttons()
        self.refresh()

    def on_mode_click(self, mode) -> None:
        if mode not in _MODES:
            raise ValueError(f"modo DataTest desconhecido: {mode!r}")
        self.set_mode(MODE_OFF if mode == self.mode else mode)

    def toggle_px_ruler(self) -> None:
        self.px_ruler_on = not self.px_ruler_on
        self._sync_buttons()
        self.refresh()

    # ── etiquetas e reguas ───────────────────────────────────────────────────

    def overlay_labels(self) -> list[tuple[str, tk.Label]]:
        return [(t, lb) for t, lb in self._labels if _widget_alive(lb)]

    def ruler_labels(self) -> list[tk.Label]:
        return [lb for lb in self._rulers if _widget_alive(lb)]

    def _clear_labels(self) -> None:
        for _testid, label in self._labels:
            try:
                label.destroy()
            except tk.TclError:
                pass
        self._labels = []

    def _clear_rulers(self) -> None:
        for label in self._rulers:
            try:
                label.destroy()
            except tk.TclError:
                pass
        self._rulers = []

    def refresh(self) -> None:
        """Recoloca etiquetas do modo ativo e reguas de px sobre a aba visivel."""
        self._clear_labels()
        self._clear_rulers()
        try:
            if self.mode != MODE_OFF:
                self._build_labels()
            if self.px_ruler_on:
                self._build_rulers()
        except tk.TclError as exc:
            print(f"[forge-pick] DataTest: falha ao atualizar overlay: {exc}", file=sys.stderr)

    def _build_labels(self) -> None:
        root = self.root
        root.update_idletasks()
        root_w, root_h = root.winfo_width(), root.winfo_height()
        base_x, base_y = root.winfo_rootx(), root.winfo_rooty()
        targets = select_targets(self.mode, overlay_candidates(root), self._button_classes)
        placed: list[tuple[int, int, int, int]] = []
        color = MODE_COLORS[self.mode]
        for testid, widget in targets:
            x = widget.winfo_rootx() - base_x
            y = widget.winfo_rooty() - base_y - LABEL_OFFSET_Y
            if y < 0:
                y = widget.winfo_rooty() - base_y
            label = tk.Label(
                root, text=testid, bg=color, fg=LABEL_INK, font=LABEL_FONT, bd=0, cursor="hand2"
            )
            _paint_colors(
                label,
                bg=color, fg=LABEL_INK,
                activebackground=color, activeforeground=LABEL_INK,
                disabledforeground=MUTED,
                highlightbackground=color, highlightcolor=color,
            )
            lw, lh = label.winfo_reqwidth(), label.winfo_reqheight()
            for _ in range(LABEL_MAX_STEPS):
                if not any(x < px + pw and px < x + lw and y < py + ph and py < y + lh
                           for px, py, pw, ph in placed):
                    break
                y += lh + 1
            if x >= root_w or y >= root_h or x + lw <= 0 or y + lh <= 0:
                label.destroy()
                continue
            placed.append((x, y, lw, lh))
            label.place(x=x, y=y)
            label.lift()
            label.bind("<Button-1>", lambda _e, t=testid, lb=label: self.copy_testid(t, lb))
            self._labels.append((testid, label))

    def _build_rulers(self) -> None:
        root = self.root
        root.update_idletasks()
        root_h = max(root.winfo_height(), root.winfo_reqheight())
        y = root_h - PX_RULER_MARGIN - PX_RULER_HEIGHT
        positions = []
        for width in reversed(PX_RULER_WIDTHS):
            positions.append((width, y))
            y -= PX_RULER_HEIGHT + PX_RULER_GAP
        for width, ypos in reversed(positions):
            label = tk.Label(
                root, text=f"{width}px", bg=MODE_COLORS["px"], fg=LABEL_INK, font=LABEL_FONT, bd=0
            )
            _paint_colors(
                label,
                bg=MODE_COLORS["px"], fg=LABEL_INK,
                activebackground=MODE_COLORS["px"], activeforeground=LABEL_INK,
                disabledforeground=MUTED,
                highlightbackground=MODE_COLORS["px"], highlightcolor=MODE_COLORS["px"],
            )
            label.place(x=PX_RULER_MARGIN, y=ypos, width=width, height=PX_RULER_HEIGHT)
            label.lift()
            self._rulers.append(label)

    def _on_root_configure(self, event) -> None:
        if self.mode == MODE_OFF and not self.px_ruler_on:
            return
        own = {str(lb) for _t, lb in self._labels} | {str(lb) for lb in self._rulers}
        if str(event.widget) in own:
            return
        if self._after_id is not None:
            try:
                self.root.after_cancel(self._after_id)
            except tk.TclError:
                pass
        try:
            self._after_id = self.root.after(REFRESH_DEBOUNCE_MS, self._debounced_refresh)
        except tk.TclError:
            self._after_id = None

    def _debounced_refresh(self) -> None:
        self._after_id = None
        try:
            if self.root.winfo_exists():
                self.refresh()
        except tk.TclError:
            pass

    # ── clipboard ────────────────────────────────────────────────────────────

    def copy_testid(self, testid, label) -> bool:
        """Copia o testid puro para o clipboard e sinaliza o resultado na etiqueta."""
        key = str(label)
        pending = self._flash.pop(key, None)
        if pending is not None:
            # clique durante um flash ativo: o original e o do primeiro clique
            original_text, original_bg, old_after = pending
            try:
                self.root.after_cancel(old_after)
            except (tk.TclError, ValueError):
                pass
        else:
            original_text = label.cget("text")
            original_bg = label.cget("bg")
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(testid)
        except tk.TclError as exc:
            print(f"[forge-pick] DataTest: falha ao copiar {testid}: {exc}", file=sys.stderr)
            flash_text, flash_bg, ok = "falhou ao copiar", COPY_FAIL_BG, False
        else:
            flash_text, flash_bg, ok = "copiado", COPY_OK_BG, True
        try:
            label.configure(text=flash_text, bg=flash_bg)
        except tk.TclError as exc:
            print(f"[forge-pick] DataTest: etiqueta indisponivel para o flash: {exc}", file=sys.stderr)
            return ok

        def _restore() -> None:
            self._flash.pop(key, None)
            try:
                if label.winfo_exists():
                    label.configure(text=original_text, bg=original_bg)
            except tk.TclError:
                pass

        after_id = self.root.after(COPY_FLASH_MS, _restore)
        self._flash[key] = (original_text, original_bg, after_id)
        return ok
