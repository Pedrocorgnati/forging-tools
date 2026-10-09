"""UI da aba Timers do Forge Pick: 3 colunas por `frequency`, tick de 1 Hz e modal.

Contrato 010 -> 011: `TimersView.column_body` e o container de cards por
coluna e `TimersView.rerender` e a funcao de rerender. Os hooks
`card_factory`/`card_updater` sao trocaveis e o default e o `TimerCard`
portado (D1), fabricado e atualizado pelos metodos de `TimersView`. Este
modulo nunca importa `app` (D1) nem nada do task-manager-desktop (G2).
"""

from __future__ import annotations

import sqlite3
import tkinter as tk
import uuid
from datetime import datetime, timedelta, timezone
from tkinter import messagebox
from tkinter import ttk

import timers_store
from datatest_overlay import (
    MODE_BODY,
    MODE_OFF,
    DataTestController,
    register_testid,
    testid_slug,
)

# Paleta Catppuccin Mocha espelhada de app.py (item 014, D1): mesmos nomes e
# valores. Nunca importar o modulo da janela aqui (import circular, contrato
# 010 -> 014); a paridade e provada por teste.
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
FONT_BTN = ("Ubuntu", 10, "bold")
FONT_WS = ("Ubuntu", 9)
FONT_TIME = ("Ubuntu Mono", 15, "bold")

# Estilo ttk da scrollbar das colunas (DX1); o de app.py fica intocado.
TIMERS_SCROLLBAR_STYLE = "FPTimers.Vertical.TScrollbar"

# -- paleta e semaforo do card (D2) -----------------------------------------

# Cor de fallback quando `timer.color` nao esta entre as de TIMER_COLORS.
DEFAULT_TIMER_COLOR = "#71717A"
TIMER_COLORS = (
    ("cinza", "#71717A"),
    ("azul", "#3B82F6"),
    ("marrom", "#92400E"),
    ("verde", "#22C55E"),
    ("amarelo", "#FBBF24"),
    ("vermelho", "#EF4444"),
)
# Exibicao das cores gravadas na paleta (D4, D5): o dado gravado nao muda, so
# o tom pintado na faixa do card e no botao de cor do modal.
TIMER_COLOR_DISPLAY = {
    "#71717A": MUTED,
    "#3B82F6": ACCENT,
    "#92400E": VIOLET,
    "#22C55E": GREEN,
    "#FBBF24": YELLOW,
    "#EF4444": ORANGE,
}
# alerta False = numeros amarelos e bolinha verde; True = numeros e bolinha
# em tom quente de alerta (D5, D6).
SEMAPHORE = {False: (YELLOW, GREEN), True: (ORANGE, ORANGE)}
CARD_BORDER = YELLOW
TITLE_FG = FG
# Data final do card em tom mais escuro que o titulo: usa o cinza da paleta
# (MUTED), pois o walker de paleta so aceita tons dela.
FONT_TITLE_END = ("Ubuntu", 9, "bold")


def normalize_timer_color(value) -> str:
    """`value` se estiver entre os hex de TIMER_COLORS, senao o cinza (D2)."""
    validas = {hex_code for _nome, hex_code in TIMER_COLORS}
    return value if value in validas else DEFAULT_TIMER_COLOR


def display_timer_color(value) -> str:
    """Tom da paleta que representa a cor gravada `value` (D4, D5)."""
    return TIMER_COLOR_DISPLAY[normalize_timer_color(value)]


def _paint(widget, *, bg=BG, fg=FG, active_bg=None, active_fg=FG, border=None, field=SURFACE) -> None:
    """Aplica o conjunto completo de cores explicitas da paleta (D10).

    So configura as opcoes que o widget expoe em `widget.keys()`; nenhum
    default do Tk sobrevive em widget criado por este modulo.
    """
    borda = bg if border is None else border
    opcoes = {
        "bg": bg,
        "fg": fg,
        "activebackground": bg if active_bg is None else active_bg,
        "activeforeground": active_fg,
        "disabledforeground": MUTED,
        "highlightbackground": borda,
        "highlightcolor": borda,
        "selectcolor": SURFACE,
        "insertbackground": FG,
        "selectbackground": ACCENT,
        "selectforeground": BG,
        "readonlybackground": field,
        "disabledbackground": field,
        "buttonbackground": field,
        "troughcolor": SURFACE,
    }
    chaves = set(widget.keys())
    widget.configure(**{k: v for k, v in opcoes.items() if k in chaves})


def _style_frame(widget, bg=BG, border=None) -> None:
    _paint(widget, bg=bg, border=border)


def _style_label(widget, fg=FG, bg=BG) -> None:
    _paint(widget, bg=bg, fg=fg)


def _style_button(widget, bg=SURFACE, fg=FG) -> None:
    _paint(widget, bg=bg, fg=fg, active_bg=HOVER if bg == SURFACE else bg, active_fg=fg)


def _style_entry(widget) -> None:
    _paint(widget, bg=SURFACE, fg=FG, border=SURFACE)


def _style_radio(widget) -> None:
    _paint(widget, bg=BG, fg=FG)


def _style_spinbox(widget) -> None:
    _paint(widget, bg=SURFACE, fg=FG, border=SURFACE)


def _style_frames(widget) -> None:
    """Pinta `widget` e todo `tk.Frame` descendente com o proprio fundo (D10)."""
    if type(widget) is tk.Frame:
        _style_frame(widget, widget.cget("bg"))
    for filho in widget.winfo_children():
        _style_frames(filho)


# -- modal de cadastro e edicao (contrato 008 -> 012) -------------------------

# Icones do cabecalho do modal (copiar/renderizar data-testid), rasterizados
# dos mesmos paths SVG usados por corgly-desktop (ui/tema.py, nomes "copiar",
# "teste" e "check"), embutidos em base64 para nao exigir arquivo externo.
_ICON_PNG_B64 = {
    "copiar": "iVBORw0KGgoAAAANSUhEUgAAABIAAAASCAMAAABhEH5lAAAAIGNIUk0AAHomAACAhAAA+gAAAIDoAAB1MAAA6mAAADqYAAAXcJy6UTwAAABFUExURQAAAGxwhmxwhmxwhmxwhmxwhmxwhmxwhmxwhmxwhmxwhmxwhmxwhmxwhmxwhmxwhmxwhmxwhmxwhmxwhmxwhmxwhgAAANS9CuEAAAAVdFJOUwARLwgfdXEcaVoK6QQYAkIoWPNrpTqFEzcAAAABYktHRACIBR1IAAAAB3RJTUUH6goGDSwYNlW1kgAAAGJJREFUGNOVz0kOgCAUA1BkkFHBofe/qgH5aNCFdkVefprC2OcM/IxoIlGjGo14XCmIviqTNirHukaa6nwgMpjya45IRFTHwX/QsoaebtNuZBHL/g2SyPm6a79+EFK5kuw1B3wnBa6ZGNeHAAAAAElFTkSuQmCC",
    "teste": "iVBORw0KGgoAAAANSUhEUgAAABIAAAASCAMAAABhEH5lAAAAIGNIUk0AAHomAACAhAAA+gAAAIDoAAB1MAAA6mAAADqYAAAXcJy6UTwAAABIUExURQAAAGxwhmxwhmxwhmxwhmxwhmxwhmxwhmxwhmxwhmxwhmxwhmxwhmxwhmxwhmxwhmxwhmxwhmxwhmxwhmxwhmxwhmxwhgAAAFaIguMAAAAWdFJOUwBnItt1ATFfvwkosLEffZYTpcpotmuhkbSlAAAAAWJLR0QAiAUdSAAAAAd0SU1FB+oKBg0sGDZVtZIAAABvSURBVBjTlc5ZDoAgDARQoMUVUQTn/kc1LAJ+GSckJS9NOkL8iESM7EkRMZF6rRHF90E6ke5pwChGDD1NmMWMqZMFKzOvWBoZ5JgqG2yaFttDO440D+wPwZWPQ6UzN9JnJY/AMQG+dr/KxevVv+UGiuIFKzj7ljgAAAAASUVORK5CYII=",
    "check": "iVBORw0KGgoAAAANSUhEUgAAABIAAAASCAMAAABhEH5lAAAAIGNIUk0AAHomAACAhAAA+gAAAIDoAAB1MAAA6mAAADqYAAAXcJy6UTwAAABOUExURQAAAKbjoabjoabjoabjoabjoabjoabjoabjoabjoabjoabjoabjoabjoabjoabjoabjoabjoabjoabjoabjoabjoabjoabjoabjoQAAANAiZjAAAAAYdFJOUwAjZyQiJiEnIFjzFCkeNPcqHTUsHBviGuav4oMAAAABYktHRACIBR1IAAAAB3RJTUUH6goGDSwYNlW1kgAAAE1JREFUGNO9j0kOgDAMA8NeKFAatvn/S+ECIr2XHKJorNiyyI9TUCakgtqSBlpLOnDP3Q/+3iNMrzwTvCwQPy9KWGEzNgrsSbweZ5aiF7xhAwNW0vdIAAAAAElFTkSuQmCC",
}
_COPY_FEEDBACK_MS = 600
_SWATCH_LADO = 22

MODE_OPTIONS = (
    ("datetime", "Data/hora final + duracao"),
    ("daily", "Horario fixo (diario)"),
    ("weekly", "Horario fixo (semanal)"),
    ("monthly", "Horario fixo (mensal)"),
)
FREQUENCY_OPTIONS = (
    ("daily", "Diario"),
    ("weekly", "Semanal"),
    ("monthly", "Mensal"),
)
WEEKDAY_NAMES = ("Segunda", "Terca", "Quarta", "Quinta", "Sexta", "Sabado", "Domingo")
END_FORMAT = "%d/%m/%Y %H:%M"
DEFAULT_FIXED_TIME = "09:00"
FIXED_MODES = ("daily", "weekly", "monthly")


def format_duration_text(seconds) -> str:
    """Segundos como "hhh:mm:ss" (horas limitadas a 999, negativo vira zero)."""
    horas, resto = divmod(max(0, int(seconds)), 3600)
    minutos, segundos = divmod(resto, 60)
    return f"{min(999, horas):03d}:{minutos:02d}:{segundos:02d}"


def parse_duration_text(text) -> int | None:
    """Segundos de "hhh:mm:ss" (exatos 3:2:2 digitos) ou None se invalido."""
    partes = str(text or "").strip().split(":")
    if len(partes) != 3 or [len(p) for p in partes] != [3, 2, 2]:
        return None
    if not all(p.isdigit() and p.isascii() for p in partes):
        return None
    horas, minutos, segundos = (int(p) for p in partes)
    if minutos > 59 or segundos > 59:
        return None
    return horas * 3600 + minutos * 60 + segundos


def _parse_end_text(text) -> datetime | None:
    """"DD/MM/AAAA HH:MM" local como datetime aware, ou None se invalido."""
    try:
        return datetime.strptime(str(text or "").strip(), END_FORMAT).astimezone()
    except ValueError:
        return None


def _format_end(moment: datetime) -> str:
    return moment.astimezone().strftime(END_FORMAT)


# Colunas da aba, na ordem do grid (0, 1, 2).
FREQUENCY_COLUMNS = (
    ("daily", "Temporizadores diarios"),
    ("weekly", "Temporizadores semanais"),
    ("monthly", "Temporizadores mensais"),
)

# Nenhuma coluna fica sem texto: sem timers, o texto de vazio e obrigatorio.
EMPTY_TEXTS = {
    "daily": "Nenhum temporizador diario",
    "weekly": "Nenhum temporizador semanal",
    "monthly": "Nenhum temporizador mensal",
}


def group_by_frequency(timers, now: datetime | None = None) -> dict[str, list]:
    """Agrupa por `frequency`, sempre com as 3 chaves de FREQUENCY_COLUMNS.

    `frequency` fora de `timers_store.FREQUENCIES` cai em "weekly" (default do
    dataclass), para que nenhum timer fique sem coluna. Cada lista sai
    ordenada por tempo restante, com os zerados no fim (D10).
    """
    agrupados: dict[str, list] = {frequency: [] for frequency, _titulo in FREQUENCY_COLUMNS}
    for timer in timers:
        frequency = getattr(timer, "frequency", "")
        if frequency not in timers_store.FREQUENCIES:
            frequency = "weekly"
        agrupados[frequency].append(timer)
    return {
        frequency: timers_store._sorted_timers(items, now)
        for frequency, items in agrupados.items()
    }


def format_remaining(seconds) -> str:
    """Tempo restante como "HH:MM:SS", com prefixo "{d}d " a partir de 1 dia."""
    total = max(0, int(seconds))
    horas, resto = divmod(total, 3600)
    minutos, segundos = divmod(resto, 60)
    if total >= 86400:
        dias, horas = divmod(horas, 24)
        return f"{dias}d {horas:02d}:{minutos:02d}:{segundos:02d}"
    return f"{horas:02d}:{minutos:02d}:{segundos:02d}"


class TimerCard(tk.Frame):
    """Card de um timer: faixa de cor, titulo, tempo e as 5 acoes (D3, D4)."""

    def __init__(self, parent, timer, on_edit, on_alert, on_pause, on_plus_one, on_delete):
        super().__init__(
            parent,
            bg=SURFACE,
            highlightthickness=1,
            highlightbackground=CARD_BORDER,
            highlightcolor=CARD_BORDER,
        )
        self.timer_id = timer.id
        self._signature = None
        slug = testid_slug(timer.id)

        _style_frame(self, SURFACE, border=CARD_BORDER)
        self.stripe = tk.Frame(self, width=7, bg=display_timer_color(timer.color))
        _style_frame(self.stripe, display_timer_color(timer.color))
        self.stripe.pack(side="left", fill="y")

        corpo = tk.Frame(self, bg=SURFACE)
        _style_frame(corpo, SURFACE)
        corpo.pack(side="left", fill="both", expand=True, padx=(6, 4), pady=4)
        linha_titulo = tk.Frame(corpo, bg=SURFACE)
        _style_frame(linha_titulo, SURFACE)
        linha_titulo.pack(fill="x")
        # Data final ("dd/mm hh:mm") a direita, com width exato para
        # "00/00 00:00"; o titulo ocupa todo o restante da linha.
        self.end_label = tk.Label(
            linha_titulo,
            font=FONT_TITLE_END,
            fg=MUTED,
            bg=SURFACE,
            anchor="e",
            width=len("00/00 00:00"),
        )
        _style_label(self.end_label, MUTED, SURFACE)
        self.end_label.pack(side="right")
        self.title_label = tk.Label(
            linha_titulo,
            text=timer.title,
            font=FONT_BTN,
            fg=TITLE_FG,
            bg=SURFACE,
            anchor="w",
        )
        _style_label(self.title_label, TITLE_FG, SURFACE)
        self.title_label.pack(side="left", fill="x", expand=True)
        self.time_label = tk.Label(corpo, font=FONT_TIME, bg=SURFACE, anchor="w")
        _style_label(self.time_label, SEMAPHORE[False][0], SURFACE)
        self.time_label.pack(fill="x")

        controles = tk.Frame(self, bg=SURFACE)
        _style_frame(controles, SURFACE)
        controles.pack(side="right", padx=4)
        self.edit_btn = self._botao(controles, "✎", on_edit)
        self.alert_btn = self._botao(controles, "●", on_alert)
        self.pause_btn = self._botao(controles, "⏸", on_pause)
        self.plus_one_btn = self._botao(controles, "+1h", on_plus_one)
        self.delete_btn = self._botao(controles, "×", on_delete)
        for botao in (
            self.edit_btn,
            self.alert_btn,
            self.pause_btn,
            self.plus_one_btn,
            self.delete_btn,
        ):
            botao.pack(side="left", padx=1)

        register_testid(self, f"fp-timer-{slug}")
        register_testid(self.stripe, f"fp-timer-color-{slug}")
        register_testid(self.title_label, f"fp-timer-title-{slug}")
        register_testid(self.end_label, f"fp-timer-end-{slug}")
        register_testid(self.time_label, f"fp-timer-time-{slug}")
        register_testid(self.edit_btn, f"fp-timer-edit-{slug}")
        register_testid(self.alert_btn, f"fp-timer-alert-{slug}")
        register_testid(self.pause_btn, f"fp-timer-pause-{slug}")
        register_testid(self.plus_one_btn, f"fp-timer-plus-one-{slug}")
        register_testid(self.delete_btn, f"fp-timer-delete-{slug}")

        # Clique no titulo ou no tempo abre a edicao (D9). O bind entrega o
        # event ao callback, por isso o lambda zero-arg.
        self.title_label.bind("<Button-1>", lambda _event: on_edit())
        self.end_label.bind("<Button-1>", lambda _event: on_edit())
        self.time_label.bind("<Button-1>", lambda _event: on_edit())

    @staticmethod
    def _botao(parent, texto, command) -> tk.Button:
        """Botao de acao do card: flat, com `command` sempre definido (D3)."""
        botao = tk.Button(
            parent,
            text=texto,
            command=command,
            relief="flat",
            bd=0,
            highlightthickness=0,
            bg=SURFACE,
            activebackground=HOVER,
            fg=FG,
            font=FONT_WS,
            cursor="hand2",
        )
        _style_button(botao)
        return botao

    def apply(self, timer, now) -> None:
        """Aplica tempo e estado do `timer` em place (D5); nada e persistido."""
        remaining = timers_store._remaining_seconds(timer, now)
        done = remaining <= 0
        alert = bool(timer.alert)
        color = normalize_timer_color(timer.color)
        paused = bool(timer.paused)
        if done:
            self.time_label.configure(text="Finalizado", fg=ORANGE)
        else:
            self.time_label.configure(
                text=format_remaining(remaining), fg=SEMAPHORE[alert][0]
            )
        end = timers_store._parse_iso(timer.ends_at)
        end_text = end.astimezone().strftime("%d/%m %H:%M") if end is not None else ""
        assinatura = (done, paused, alert, color, timer.title, end_text)
        if assinatura == self._signature:
            return
        self._signature = assinatura
        self.title_label.configure(text=timer.title)
        self.end_label.configure(text=end_text)
        self.stripe.configure(bg=display_timer_color(color))
        self.alert_btn.configure(fg=SEMAPHORE[alert][1])
        self.pause_btn.configure(text="▶" if paused else "⏸")
        for botao in (
            self.edit_btn,
            self.alert_btn,
            self.pause_btn,
            self.plus_one_btn,
            self.delete_btn,
        ):
            botao.pack_forget()
        if done:
            visiveis = (self.edit_btn, self.plus_one_btn, self.delete_btn)
        elif paused:
            visiveis = (self.edit_btn, self.alert_btn, self.pause_btn, self.delete_btn)
        else:
            visiveis = (self.edit_btn, self.alert_btn, self.pause_btn)
        for botao in visiveis:
            botao.pack(side="left", padx=1)


class TimerDialog(tk.Toplevel):
    """Modal de cadastro/edicao de timer (D1..D10); sem timer = cadastro."""

    def __init__(self, view, timer=None) -> None:
        super().__init__(view.frame.winfo_toplevel())
        self.view = view
        self.timer = timer
        self._syncing = False
        self._ready = False
        _style_frame(self, BG)
        # Paridade com a referencia de task-manager-desktop (Task 03 da nota
        # 10-04-forge-pick-modal-timer-melhoria): titulo unico "Temporizador";
        # a distincao novo/edicao foi descartada por descaracterizar a paridade.
        self.title("Temporizador")
        self.transient(view.frame.winfo_toplevel())
        register_testid(self, "fp-clock-timer-dialog")
        self._icons: dict[str, tk.PhotoImage] = {}
        self._datatest: DataTestController | None = None

        agora = datetime.now(timezone.utc)
        mode = getattr(timer, "mode", "datetime")
        if mode not in timers_store.MODES:
            mode = "datetime"
        frequency = getattr(timer, "frequency", "weekly")
        if frequency not in timers_store.FREQUENCIES:
            frequency = "weekly"
        saved_time = getattr(timer, "weekly_time", "") or ""
        saved_daily = getattr(timer, "daily_time", "") or ""
        weekday = getattr(timer, "weekly_weekday", None)
        day = getattr(timer, "monthly_day", None)
        end = agora + timedelta(hours=1)
        duration = 3600
        if timer is not None and mode == "datetime":
            parsed = timers_store._parse_iso(timer.ends_at)
            if parsed is not None and parsed > agora:
                end = parsed
                duration = timers_store._seconds_until_iso(timer.ends_at, agora)

        self.mode_var = tk.StringVar(value=mode)
        self.frequency_var = tk.StringVar(value=frequency)
        self.title_var = tk.StringVar(value=getattr(timer, "title", "") or "")
        self.end_var = tk.StringVar(value=_format_end(end))
        self.duration_var = tk.StringVar(value=format_duration_text(duration))
        self.daily_time_var = tk.StringVar(value=saved_daily or DEFAULT_FIXED_TIME)
        self.weekday_var = tk.IntVar(
            value=weekday if isinstance(weekday, int) and 0 <= weekday <= 6 else -1
        )
        self._weekday_name_var = tk.StringVar(
            value=WEEKDAY_NAMES[self.weekday_var.get()] if self.weekday_var.get() >= 0 else ""
        )
        self.weekly_time_var = tk.StringVar(
            value=saved_time or DEFAULT_FIXED_TIME
        )
        self.monthly_day_var = tk.IntVar(
            value=day if isinstance(day, int) and 1 <= day <= 31 else 1
        )
        self.monthly_time_var = tk.StringVar(
            value=saved_time or DEFAULT_FIXED_TIME
        )
        self.color_var = tk.StringVar(
            value=normalize_timer_color(getattr(timer, "color", DEFAULT_TIMER_COLOR))
        )
        self.mode_radios: dict[str, tk.Radiobutton] = {}
        self.frequency_radios: dict[str, tk.Radiobutton] = {}
        self.color_buttons: dict[str, tk.Button] = {}

        self._build()
        self._sync_frequency_with_mode()
        for var in (
            self.title_var,
            self.end_var,
            self.duration_var,
            self.daily_time_var,
            self.weekly_time_var,
            self.monthly_time_var,
            self.weekday_var,
            self.monthly_day_var,
        ):
            var.trace_add("write", lambda *_args: self._refresh())
        self._ready = True
        self._refresh()

        self.bind("<Escape>", lambda _event: self.cancel())
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        self.bind("<Destroy>", self._on_destroy, add="+")
        try:
            self.grab_set()
        except tk.TclError:
            pass
        self.title_entry.focus_set()

    # -- construcao (D9, D10) ------------------------------------------------

    def _label(self, parent, text) -> tk.Label:
        label = tk.Label(parent, text=text, fg=MUTED, bg=BG, anchor="w", font=FONT_WS)
        _style_label(label, MUTED, BG)
        return label

    def _entry(self, parent, var, testid, width=18) -> tk.Entry:
        entry = tk.Entry(
            parent,
            textvariable=var,
            width=width,
            bg=SURFACE,
            fg=FG,
            insertbackground=FG,
            relief="flat",
            font=FONT_WS,
        )
        _style_entry(entry)
        register_testid(entry, testid)
        return entry

    def _block(self) -> tk.Frame:
        bloco = tk.Frame(self, bg=BG)
        bloco.pack(fill="x", padx=12, pady=2)
        return bloco

    def _radio(self, parent, text, var, value, command, testid) -> tk.Radiobutton:
        radio = tk.Radiobutton(
            parent,
            text=text,
            variable=var,
            value=value,
            command=command,
            fg=FG,
            bg=BG,
            selectcolor=SURFACE,
            activebackground=BG,
            activeforeground=FG,
            anchor="w",
            font=FONT_WS,
        )
        _style_radio(radio)
        register_testid(radio, testid)
        return radio

    def _build_combo_style(self) -> None:
        """Estilo `FP.TCombobox` e popdown na paleta (D10)."""
        estilo = ttk.Style(self)
        estilo.configure(
            "FP.TCombobox",
            fieldbackground=SURFACE,
            foreground=FG,
            background=SURFACE,
            arrowcolor=MUTED,
            bordercolor=SURFACE,
            lightcolor=SURFACE,
            darkcolor=SURFACE,
            selectbackground=SURFACE,
            selectforeground=FG,
        )
        estilo.map(
            "FP.TCombobox",
            fieldbackground=[("readonly", SURFACE), ("focus", SURFACE)],
            foreground=[("readonly", FG), ("focus", FG)],
            background=[("readonly", SURFACE), ("active", SURFACE)],
            selectbackground=[("readonly", SURFACE), ("focus", SURFACE)],
            selectforeground=[("readonly", FG), ("focus", FG)],
        )
        self.option_add("*TCombobox*Listbox.background", SURFACE)
        self.option_add("*TCombobox*Listbox.foreground", FG)
        self.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
        self.option_add("*TCombobox*Listbox.selectForeground", BG)

    def _build(self) -> None:
        self._build_combo_style()

        # -- header: titulo + botoes copiar/renderizar data-testid -------------
        cabecalho = tk.Frame(self, bg=BG)
        cabecalho.pack(fill="x", padx=12, pady=(12, 2))

        titulo_label = tk.Label(
            cabecalho, text="Temporizador", fg=FG, bg=BG,
            anchor="w", font=("Ubuntu", 13, "bold"),
        )
        _style_label(titulo_label, FG, BG)
        titulo_label.pack(side="left")

        self._copy_btn = tk.Button(
            cabecalho, image=self._icone("copiar"), relief="flat", bd=0,
            highlightthickness=0, bg=BG, activebackground=HOVER, cursor="hand2",
            font=FONT_WS, command=self._copiar_testid_dialog,
        )
        _style_button(self._copy_btn, BG, MUTED)
        register_testid(self._copy_btn, "fp-clock-timer-copy-testid")
        self._copy_btn.pack(side="left", padx=(4, 0))

        self._render_btn = tk.Button(
            cabecalho, image=self._icone("teste"), relief="flat", bd=0,
            highlightthickness=0, bg=BG, activebackground=HOVER, cursor="hand2",
            font=FONT_WS, command=self._alternar_render_testids,
        )
        _style_button(self._render_btn, BG, MUTED)
        register_testid(self._render_btn, "fp-clock-timer-copy-render")
        self._render_btn.pack(side="left", padx=(4, 0))

        # -- NOME -------------------------------------------------------------
        nome_frame = tk.Frame(self, bg=BG)
        nome_frame.pack(fill="x", padx=12, pady=(8, 2))
        self._label(nome_frame, "NOME").pack(anchor="w")
        self.title_entry = self._entry(nome_frame, self.title_var, "fp-clock-timer-title-input", 40)
        self.title_entry.pack(fill="x")

        # -- BLOCO DE AGENDAMENTO (card com borda) ----------------------------
        schedule_box = tk.Frame(self, bg=SURFACE, highlightthickness=1,
                               highlightbackground=HOVER, highlightcolor=HOVER)
        _style_frame(schedule_box, SURFACE, border=HOVER)
        register_testid(schedule_box, "fp-clock-timer-schedule-box")
        schedule_box.pack(fill="x", padx=12, pady=(10, 2))

        sched = tk.Frame(schedule_box, bg=SURFACE)
        _style_frame(sched, SURFACE)
        sched.pack(fill="x", padx=10, pady=8)

        # -- radio de modo (apenas datetime visivel como cabecalho do card) ---
        mode_dt_radio = self._radio(
            sched, "Data/hora final + duracao", self.mode_var,
            "datetime", self._on_mode_change,
            "fp-clock-timer-mode-datetime",
        )
        mode_dt_radio.pack(anchor="w")
        self.mode_radios["datetime"] = mode_dt_radio
        # radios ocultos para daily/weekly/monthly (selecionados por foco)
        for value in ("daily", "weekly", "monthly"):
            text = next(t for v, t in MODE_OPTIONS if v == value)
            radio = self._radio(
                sched, text, self.mode_var, value, self._on_mode_change,
                f"fp-clock-timer-mode-{value}",
            )
            self.mode_radios[value] = radio

        # -- 3 COLUNAS: data/hora final | duracao | frequencia ---------------
        top_row = tk.Frame(sched, bg=SURFACE)
        _style_frame(top_row, SURFACE)
        top_row.pack(fill="x", pady=(4, 0))

        # coluna esquerda: data/hora final
        dt_col = tk.Frame(top_row, bg=SURFACE)
        _style_frame(dt_col, SURFACE)
        dt_col.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self._label(dt_col, "DATA/HORA FINAL").pack(anchor="w")
        dt_row = tk.Frame(dt_col, bg=SURFACE)
        _style_frame(dt_row, SURFACE)
        dt_row.pack(fill="x")
        self.end_entry = self._entry(dt_row, self.end_var, "fp-clock-timer-end-input")
        self.end_entry.pack(side="left", fill="x", expand=True)
        self.end_entry.bind("<FocusOut>", lambda _e: self._sync_duration_from_end(), add="+")
        self.end_entry.bind("<Return>", lambda _e: self._sync_duration_from_end(), add="+")
        self.end_entry.bind("<FocusIn>", lambda _e: self._select_mode("datetime"), add="+")

        # coluna central: duracao + atalhos
        dur_col = tk.Frame(top_row, bg=SURFACE)
        _style_frame(dur_col, SURFACE)
        dur_col.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self._label(dur_col, "DURACAO").pack(anchor="w")
        dur_row = tk.Frame(dur_col, bg=SURFACE)
        _style_frame(dur_row, SURFACE)
        dur_row.pack(fill="x")
        self.duration_entry = self._entry(
            dur_row, self.duration_var, "fp-clock-timer-duration-input", 12
        )
        self.duration_entry.pack(side="left")
        self.shortcut_1d_btn = self._shortcut(dur_row, "1d", 86400, "fp-clock-timer-shortcut-1d")
        self.shortcut_7d_btn = self._shortcut(dur_row, "7d", 7 * 86400, "fp-clock-timer-shortcut-7d")
        self.duration_entry.bind("<FocusOut>", lambda _e: self._apply_duration_input(), add="+")
        self.duration_entry.bind("<Return>", lambda _e: self._apply_duration_input(), add="+")
        self.duration_entry.bind("<FocusIn>", lambda _e: self._select_mode("datetime"), add="+")

        # coluna direita: frequencia (coluna de exibicao)
        freq_col = tk.Frame(top_row, bg=SURFACE)
        _style_frame(freq_col, SURFACE)
        freq_col.pack(side="left", fill="x", expand=True)
        self._label(freq_col, "FREQUENCIA").pack(anchor="w")
        for value, text in FREQUENCY_OPTIONS:
            radio = self._radio(
                freq_col, text, self.frequency_var, value, self._refresh,
                f"fp-clock-timer-frequency-{value}",
            )
            radio.pack(anchor="w")
            self.frequency_radios[value] = radio

        # -- DIVIDER ---------------------------------------------------------
        divider = tk.Frame(sched, bg=HOVER, height=1)
        _style_frame(divider, HOVER)
        divider.pack(fill="x", pady=(10, 8))

        # -- HORARIO FIXO: semanal | mensal (2 colunas) -----------------------
        self._label(sched, "HORARIO FIXO").pack(anchor="w")

        fixed_cols = tk.Frame(sched, bg=SURFACE)
        _style_frame(fixed_cols, SURFACE)
        fixed_cols.pack(fill="x", pady=(4, 0))

        # coluna esquerda: semanal
        weekly_col = tk.Frame(fixed_cols, bg=SURFACE)
        _style_frame(weekly_col, SURFACE)
        weekly_col.pack(side="left", fill="x", expand=True, padx=(0, 8))
        mode_weekly_radio = self._radio(
            weekly_col, "Horario fixo (semanal)", self.mode_var,
            "weekly", self._on_mode_change,
            "fp-clock-timer-mode-weekly",
        )
        mode_weekly_radio.pack(anchor="w")
        self.mode_radios["weekly"] = mode_weekly_radio
        self._label(weekly_col, "DIA DA SEMANA E HORARIO").pack(anchor="w", pady=(4, 0))
        weekday_row = tk.Frame(weekly_col, bg=SURFACE)
        _style_frame(weekday_row, SURFACE)
        weekday_row.pack(fill="x")
        self.weekday_combo = ttk.Combobox(
            weekday_row,
            textvariable=self._weekday_name_var,
            values=WEEKDAY_NAMES,
            state="readonly",
            width=12,
            style="FP.TCombobox",
            font=FONT_WS,
        )
        register_testid(self.weekday_combo, "fp-clock-timer-weekly-weekday")
        self.weekday_combo.pack(side="left", padx=(0, 6))
        self.weekday_combo.bind("<<ComboboxSelected>>", self._on_weekday_selected, add="+")
        self.weekday_combo.bind("<FocusIn>", lambda _e: self._select_mode("weekly"), add="+")
        self.weekly_entry = self._entry(
            weekday_row, self.weekly_time_var, "fp-clock-timer-weekly-time-input", 8
        )
        self.weekly_entry.pack(side="left")
        self.weekly_entry.bind("<FocusIn>", lambda _e: self._select_mode("weekly"), add="+")

        # coluna direita: mensal
        monthly_col = tk.Frame(fixed_cols, bg=SURFACE)
        _style_frame(monthly_col, SURFACE)
        monthly_col.pack(side="left", fill="x", expand=True)
        mode_monthly_radio = self._radio(
            monthly_col, "Horario fixo (mensal)", self.mode_var,
            "monthly", self._on_mode_change,
            "fp-clock-timer-mode-monthly",
        )
        mode_monthly_radio.pack(anchor="w")
        self.mode_radios["monthly"] = mode_monthly_radio
        self._label(monthly_col, "DIA DO MES E HORARIO").pack(anchor="w", pady=(4, 0))
        month_row = tk.Frame(monthly_col, bg=SURFACE)
        _style_frame(month_row, SURFACE)
        month_row.pack(fill="x")
        self.monthly_day_spin = tk.Spinbox(
            month_row,
            from_=1,
            to=31,
            width=4,
            textvariable=self.monthly_day_var,
            bg=SURFACE,
            fg=FG,
            insertbackground=FG,
            relief="flat",
            font=FONT_WS,
        )
        _style_spinbox(self.monthly_day_spin)
        register_testid(self.monthly_day_spin, "fp-clock-timer-monthly-day")
        self.monthly_day_spin.pack(side="left", padx=(0, 6))
        self.monthly_day_spin.bind("<FocusIn>", lambda _e: self._select_mode("monthly"), add="+")
        self.monthly_entry = self._entry(
            month_row, self.monthly_time_var, "fp-clock-timer-monthly-time-input", 8
        )
        self.monthly_entry.pack(side="left")
        self.monthly_entry.bind("<FocusIn>", lambda _e: self._select_mode("monthly"), add="+")

        # -- HORARIO DIARIO (campo unico, abaixo do par semanal/mensal) -------
        daily_row = tk.Frame(sched, bg=SURFACE)
        _style_frame(daily_row, SURFACE)
        daily_row.pack(fill="x", pady=(6, 0))
        self._label(daily_row, "DIARIO (HH:MM)").pack(side="left")
        self.daily_entry = self._entry(
            daily_row, self.daily_time_var, "fp-clock-timer-daily-time-input", 8
        )
        self.daily_entry.pack(side="left", padx=(6, 0))
        self.daily_entry.bind("<FocusIn>", lambda _e: self._select_mode("daily"), add="+")

        # -- HELP TEXT (explicacao de recorrencia fixa) -----------------------
        help_text = (
            "Recorrencia fixa: ao zerar, reinicia para o mesmo dia e horario "
            "da semana (ou do mes) seguinte. Dias inexistentes no mes (ex.: 31) "
            "caem no ultimo dia daquele mes."
        )
        help_label = tk.Label(
            sched, text=help_text, fg=MUTED, bg=SURFACE,
            anchor="w", justify="left", wraplength=480,
            font=("Ubuntu", 8),
        )
        _style_label(help_label, MUTED, SURFACE)
        register_testid(help_label, "fp-clock-timer-help-text")
        help_label.pack(anchor="w", pady=(8, 0))

        # -- COR DO CARD -----------------------------------------------------
        cores = tk.Frame(self, bg=BG)
        _style_frame(cores, BG)
        cores.pack(fill="x", padx=12, pady=(8, 2))
        self._label(cores, "COR DO CARD").pack(anchor="w")
        faixa = tk.Frame(cores, bg=BG)
        _style_frame(faixa, BG)
        faixa.pack(anchor="w")
        self._swatch_images: list[tk.PhotoImage] = []
        for nome_cor, hex_code in TIMER_COLORS:
            tom = display_timer_color(hex_code)
            imagem = tk.PhotoImage(width=_SWATCH_LADO, height=_SWATCH_LADO)
            imagem.put(tom, to=(0, 0, _SWATCH_LADO, _SWATCH_LADO))
            self._swatch_images.append(imagem)
            botao = tk.Button(
                faixa,
                image=imagem,
                relief="flat",
                bd=0,
                highlightthickness=0,
                bg=tom,
                activebackground=tom,
                command=lambda h=hex_code: self._select_color(h),
                cursor="hand2",
                font=FONT_WS,
            )
            _style_button(botao, tom, BG)
            register_testid(botao, f"fp-clock-timer-color-{nome_cor}")
            botao.pack(side="left", padx=2)
            self.color_buttons[hex_code] = botao
        self._paint_colors()

        # -- ROTINA (checkbox daily) -----------------------------------------
        rotina = tk.Frame(self, bg=BG)
        _style_frame(rotina, BG)
        rotina.pack(fill="x", padx=12, pady=(8, 2))
        self._label(rotina, "ROTINA").pack(anchor="w")
        self.daily_var = tk.BooleanVar(
            value=(getattr(self.timer, "mode", "") == "daily")
            if self.timer is not None else False
        )
        daily_check = tk.Checkbutton(
            rotina,
            text="Daily (rotina diaria, card verde)",
            variable=self.daily_var,
            fg=FG,
            bg=BG,
            selectcolor=SURFACE,
            activebackground=BG,
            activeforeground=FG,
            font=FONT_WS,
            cursor="hand2",
        )
        _style_radio(daily_check)
        register_testid(daily_check, "fp-clock-timer-daily-toggle")
        daily_check.pack(anchor="w")
        daily_check.configure(command=self._on_daily_toggle)

        # -- ERRO ------------------------------------------------------------
        self.error_label = tk.Label(
            self, text="", fg=ORANGE, bg=BG, anchor="w", justify="left", wraplength=360,
            font=FONT_WS,
        )
        _style_label(self.error_label, ORANGE, BG)
        register_testid(self.error_label, "fp-clock-timer-error")
        self.error_label.pack(fill="x", padx=12, pady=(8, 0))

        # -- BOTOES (estilo referencia: Cancelar + OK) -----------------------
        acoes = tk.Frame(self, bg=BG)
        _style_frame(acoes, BG)
        acoes.pack(fill="x", padx=12, pady=12)
        self.save_btn = tk.Button(
            acoes, text="\u2713  OK", command=self.save,
            bg=ACCENT, fg=BG,
            activebackground=GREEN, activeforeground=BG,
            relief="flat", cursor="hand2", font=FONT_BTN,
        )
        _style_button(self.save_btn, ACCENT, BG)
        register_testid(self.save_btn, "fp-clock-timer-save")
        self.save_btn.pack(side="right", padx=(6, 0))
        self.cancel_btn = tk.Button(
            acoes, text="\u2715  Cancelar", command=self.cancel,
            bg=SURFACE, fg=MUTED,
            activebackground=HOVER, activeforeground=FG,
            relief="flat", cursor="hand2", font=FONT_WS,
        )
        _style_button(self.cancel_btn, SURFACE, MUTED)
        register_testid(self.cancel_btn, "fp-clock-timer-cancel")
        self.cancel_btn.pack(side="right")
        _style_frames(self)

    def _icone(self, nome) -> tk.PhotoImage:
        """Icone do cabecalho (mesmos desenhos de corgly-desktop), com cache."""
        if nome not in self._icons:
            self._icons[nome] = tk.PhotoImage(data=_ICON_PNG_B64[nome])
        return self._icons[nome]

    def _copiar_testid(self, testid: str) -> None:
        """Copia `data-testid="..."` para o clipboard (espelha corgly-desktop)."""
        valor = f'data-testid="{testid}"'
        try:
            self.clipboard_clear()
            self.clipboard_append(valor)
        except tk.TclError:
            pass

    def _copiar_testid_dialog(self) -> None:
        """Copia o testid do modal e troca o icone por um check (feedback, D10)."""
        self._copiar_testid("fp-clock-timer-dialog")
        try:
            self._copy_btn.configure(image=self._icone("check"))
            self.after(_COPY_FEEDBACK_MS, self._restaurar_icone_copiar)
        except tk.TclError:
            pass

    def _restaurar_icone_copiar(self) -> None:
        try:
            self._copy_btn.configure(image=self._icone("copiar"))
        except tk.TclError:
            pass

    def _alternar_render_testids(self) -> None:
        """Liga/desliga o overlay com os data-testids do proprio modal."""
        if self._datatest is None:
            self._datatest = DataTestController(self)
            self._datatest.anchor_widget = self._render_btn
        if self._datatest.is_panel_open and self._datatest.mode != MODE_OFF:
            self._datatest.close_panel()
            return
        self._datatest.open_panel()
        self._datatest.set_mode(MODE_BODY)

    def _shortcut(self, parent, text, seconds, testid) -> tk.Button:
        botao = tk.Button(
            parent, text=text, command=lambda: self._set_duration_seconds(seconds),
            bg=SURFACE, fg=FG, activebackground=HOVER, relief="flat", cursor="hand2",
            font=FONT_WS,
        )
        _style_button(botao)
        register_testid(botao, testid)
        botao.pack(side="left", padx=(6, 0))
        return botao

    # -- modo, frequencia e cor (D3, D4, D10) --------------------------------

    def _on_mode_change(self) -> None:
        self._sync_frequency_with_mode()
        self._refresh()

    def _select_mode(self, mode) -> None:
        if self.mode_var.get() != mode:
            self.mode_var.set(mode)
            self._on_mode_change()

    def _sync_frequency_with_mode(self) -> None:
        mode = self.mode_var.get()
        fixo = mode in FIXED_MODES
        if fixo:
            self.frequency_var.set(mode)
        for radio in self.frequency_radios.values():
            radio.configure(state="disabled" if fixo else "normal")

    def _on_daily_toggle(self) -> None:
        """Checkbox daily: marca/desmarca o modo 'daily'."""
        if self.daily_var.get():
            self._select_mode("daily")
        else:
            self._select_mode("datetime")

    def _select_color(self, hex_code) -> None:
        self.color_var.set(hex_code)
        self._paint_colors()

    def _paint_colors(self) -> None:
        atual = self.color_var.get()
        for hex_code, botao in self.color_buttons.items():
            if hex_code == atual:
                botao.configure(highlightthickness=2, highlightbackground=FG,
                                highlightcolor=FG)
            else:
                botao.configure(highlightthickness=0)

    def _on_weekday_selected(self, _event=None) -> None:
        nome = self._weekday_name_var.get()
        self.weekday_var.set(WEEKDAY_NAMES.index(nome) if nome in WEEKDAY_NAMES else -1)
        self._select_mode("weekly")

    # -- sincronia data final <-> duracao (D5) -------------------------------

    def _set_duration_seconds(self, seconds) -> None:
        self.duration_var.set(format_duration_text(seconds))
        self._select_mode("datetime")
        self._apply_duration_input()

    def _apply_duration_input(self) -> None:
        """Duracao digitada vira data final = agora + duracao."""
        if self._syncing:
            return
        segundos = parse_duration_text(self.duration_var.get())
        if segundos is None:
            return
        self._syncing = True
        try:
            self.end_var.set(_format_end(datetime.now(timezone.utc) + timedelta(seconds=segundos)))
        finally:
            self._syncing = False
        self._refresh()

    def _sync_duration_from_end(self) -> None:
        """Data final digitada vira duracao = final - agora."""
        if self._syncing:
            return
        fim = _parse_end_text(self.end_var.get())
        if fim is None:
            return
        restante = (fim - datetime.now(timezone.utc)).total_seconds()
        if restante <= 0:
            return
        self._syncing = True
        try:
            self.duration_var.set(format_duration_text(restante))
        finally:
            self._syncing = False
        self._refresh()

    # -- validacao (D6) ------------------------------------------------------

    def _weekday(self):
        try:
            valor = int(self.weekday_var.get())
        except (tk.TclError, ValueError):
            return None
        return valor if 0 <= valor <= 6 else None

    def _monthly_day(self):
        try:
            valor = int(self.monthly_day_var.get())
        except (tk.TclError, ValueError):
            return None
        return valor if 1 <= valor <= 31 else None

    def _validate(self, now=None) -> str:
        """Primeira mensagem de erro (ou "" se valido), na ordem do D6."""
        now = now or datetime.now(timezone.utc)
        if not self.title_var.get().strip():
            return "Informe o nome do temporizador."
        mode = self.mode_var.get()
        parse_hhmm = timers_store._parse_weekly_time
        if mode == "datetime":
            fim = _parse_end_text(self.end_var.get())
            if fim is None:
                return "Informe a data no formato DD/MM/AAAA HH:MM."
            if fim <= now:
                return "Escolha uma data/hora no futuro."
            if parse_duration_text(self.duration_var.get()) is None:
                return "Informe a duracao no formato hhh:mm:ss."
        elif mode == "daily":
            if parse_hhmm(self.daily_time_var.get()) is None:
                return "Informe um horario valido no formato HH:MM."
        elif mode == "weekly":
            if self._weekday() is None or parse_hhmm(self.weekly_time_var.get()) is None:
                return "Escolha um dia da semana e um horario validos."
        elif mode == "monthly":
            if self._monthly_day() is None or parse_hhmm(self.monthly_time_var.get()) is None:
                return "Escolha um dia do mes e um horario validos."
        return ""

    def _refresh(self) -> None:
        if not self._ready:
            return
        mensagem = self._validate()
        self.error_label.configure(text=mensagem)
        self.save_btn.configure(state="disabled" if mensagem else "normal")

    # -- salvar e cancelar (D7, D8) -----------------------------------------

    def save(self, now: datetime | None = None) -> bool:
        """Valida, calcula ends_at, grava (create/update) e fecha o modal."""
        now = now or datetime.now(timezone.utc)
        mensagem = self._validate(now)
        if mensagem:
            self.error_label.configure(text=mensagem)
            self.save_btn.configure(state="disabled")
            return False
        titulo = self.title_var.get().strip()
        mode = self.mode_var.get()
        weekly_weekday = None
        weekly_time = ""
        monthly_day = None
        daily_time = ""
        if mode == "daily":
            daily_time = self.daily_time_var.get().strip()
            ends_at = timers_store._next_daily_occurrence(daily_time, now)
        elif mode == "weekly":
            weekly_weekday = self._weekday()
            weekly_time = self.weekly_time_var.get().strip()
            ends_at = timers_store._next_weekly_occurrence(weekly_weekday, weekly_time, now)
        elif mode == "monthly":
            monthly_day = self._monthly_day()
            weekly_time = self.monthly_time_var.get().strip()
            ends_at = timers_store._next_monthly_occurrence(monthly_day, weekly_time, now)
        else:
            ends_at = _parse_end_text(self.end_var.get()).astimezone(timezone.utc).isoformat()
        remaining = timers_store._seconds_until_iso(ends_at, now)
        campos = dict(
            title=titulo,
            duration_seconds=remaining,
            remaining_seconds=remaining,
            ends_at=ends_at,
            color=normalize_timer_color(self.color_var.get()),
            state="done" if remaining <= 0 else "running",
            paused=False,
            paused_at=None,
            mode=mode,
            weekly_weekday=weekly_weekday,
            weekly_time=weekly_time,
            monthly_day=monthly_day,
            daily_time=daily_time,
            frequency=self.frequency_var.get(),
        )
        store = self.view.store
        try:
            if self.timer is None:
                novo = timers_store.ClockTimer(
                    id=f"tm-{uuid.uuid4().hex[:10]}", alert=False, **campos
                )
                store.create_clock_timer(novo)
            else:
                fresco = self.view._find_timer(self.timer.id)
                if fresco is None:
                    raise timers_store.ClockTimerNotFoundError(
                        f"ClockTimer {self.timer.id!r} nao encontrado"
                    )
                atualizado = timers_store.ClockTimer(
                    id=fresco.id, alert=fresco.alert, created_at=fresco.created_at, **campos
                )
                store.update_clock_timer(atualizado)
        except (sqlite3.Error, OSError) as exc:
            messagebox.showerror(
                "Temporizadores", f'Nao foi possivel salvar "{titulo}": {exc}', parent=self
            )
            return False
        except timers_store.ClockTimerNotFoundError as exc:
            messagebox.showerror(
                "Temporizadores", f'Nao foi possivel salvar "{titulo}": {exc}', parent=self
            )
            self.view.rerender(now)
            self.destroy()
            return False
        self.view.rerender(now)
        self.destroy()
        return True

    def cancel(self) -> None:
        """Fecha sem tocar no store (D8)."""
        self.destroy()

    def _on_destroy(self, event) -> None:
        # <Destroy> chega tambem pelos filhos: so o proprio dialogo libera a view.
        if event.widget is not self:
            return
        if self._datatest is not None:
            self._datatest.close_panel()
        if self.view._dialog is self:
            self.view._dialog = None


class TimersView:
    """3 colunas de timers (daily/weekly/monthly) com scroll e tick proprios."""

    def __init__(self, parent, store, boot_error) -> None:
        self.store = store
        self.boot_error = boot_error
        self.card_factory = self._make_card
        self.card_updater = self._update_card
        self.on_edit = None
        self._dialog: TimerDialog | None = None
        self._columns: dict[str, dict] = {}
        self._cards: dict[str, tk.Widget] = {}
        self._order: dict[str, list[str]] = {
            frequency: [] for frequency, _titulo in FREQUENCY_COLUMNS
        }
        self._after_id: str | None = None
        self._warning: tk.Label | None = None

        self.frame = tk.Frame(parent, bg=BG)
        _style_frame(self.frame, BG)
        self.frame.pack(fill="both", expand=True)
        for indice in range(len(FREQUENCY_COLUMNS)):
            self.frame.grid_columnconfigure(indice, weight=1, uniform="timers")
        self.frame.grid_rowconfigure(1, weight=1)
        self._build_scrollbar_style()
        for indice, (frequency, titulo) in enumerate(FREQUENCY_COLUMNS):
            self._columns[frequency] = self._build_column(indice, frequency, titulo)
        self.frame.bind("<Destroy>", self._on_frame_destroy, add="+")
        self.on_edit = self.open_edit_dialog

    # -- layout (D3) ---------------------------------------------------------

    def _build_scrollbar_style(self) -> None:
        """Estilo exclusivo da aba Timers (DX1): o mapa global do clam pinta o
        thumb com #dcdad5 em disabled e #eeebe7 em active, fora da paleta. O
        FP.Vertical.TScrollbar de app.py segue intocado (D2, G3)."""
        estilo = ttk.Style(self.frame)
        estilo.configure(
            TIMERS_SCROLLBAR_STYLE,
            troughcolor=BG,
            background=SURFACE,
            arrowcolor=MUTED,
            bordercolor=BG,
            lightcolor=SURFACE,
            darkcolor=SURFACE,
        )
        estilo.map(
            TIMERS_SCROLLBAR_STYLE,
            background=[("disabled", SURFACE), ("pressed", HOVER), ("active", HOVER)],
            arrowcolor=[("disabled", MUTED), ("pressed", MUTED), ("active", MUTED)],
        )

    def _build_column(self, indice: int, frequency: str, titulo: str) -> dict:
        section = tk.Frame(self.frame, bg=BG)
        _style_frame(section, BG)
        section.grid(row=1, column=indice, sticky="nsew", padx=6, pady=(0, 6))
        register_testid(section, f"fp-{frequency}-section")

        title = tk.Label(section, text=titulo, font=FONT_BTN, fg=MUTED, bg=BG)
        _style_label(title, MUTED, BG)
        title.pack(side="top", fill="x")
        register_testid(title, f"fp-{frequency}-section-title")

        canvas = tk.Canvas(section, bg=BG, highlightthickness=0)
        _paint(canvas, bg=BG)
        register_testid(canvas, f"fp-{frequency}-scroll")
        scrollbar = ttk.Scrollbar(
            section, orient="vertical", style=TIMERS_SCROLLBAR_STYLE, command=canvas.yview
        )
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        body = tk.Frame(canvas, bg=BG)
        _style_frame(body, BG)
        window_id = canvas.create_window((0, 0), window=body, anchor="nw")
        register_testid(body, f"fp-{frequency}-list")
        body.bind("<Configure>", lambda _event, c=canvas: c.configure(scrollregion=c.bbox("all")))
        canvas.bind(
            "<Configure>",
            lambda event, c=canvas, w=window_id: c.itemconfigure(w, width=event.width),
        )
        return {
            "section": section,
            "title": title,
            "canvas": canvas,
            "scrollbar": scrollbar,
            "body": body,
        }

    def column_body(self, frequency: str) -> tk.Frame:
        """Container de cards da coluna `frequency` (contrato 010 -> 011)."""
        if frequency not in self._columns:
            raise ValueError(f"frequencia desconhecida: {frequency!r}")
        return self._columns[frequency]["body"]

    # -- leitura e estados (D5, D6, D7) --------------------------------------

    def _read_timers(self) -> tuple[str | None, list]:
        """(mensagem de erro ou None, timers) segundo as fontes de erro (D6)."""
        if self.store is None:
            return self.boot_error or "banco de timers indisponivel", []
        try:
            return None, self.store.list_clock_timers()
        except (sqlite3.Error, OSError) as exc:
            return str(exc), []

    def _ensure_warning(self) -> None:
        """`boot_error` com store presente vira aviso, nunca silencio (D6)."""
        if self._warning is not None or self.store is None or not self.boot_error:
            return
        self._warning = tk.Label(
            self.frame,
            text=f"Aviso ao carregar timers: {self.boot_error}",
            fg=YELLOW,
            bg=BG,
            anchor="w",
            font=FONT_WS,
        )
        _style_label(self._warning, YELLOW, BG)
        self._warning.grid(row=0, column=0, columnspan=3, sticky="ew")
        register_testid(self._warning, "fp-timers-warning")

    def _render(self, erro: str | None, grouped: dict | None, now: datetime) -> None:
        """Ponto unico de renderizacao: exatamente um estado por coluna."""
        self._ensure_warning()
        self._cards = {}
        for frequency, _titulo in FREQUENCY_COLUMNS:
            body = self.column_body(frequency)
            for filho in body.winfo_children():
                filho.destroy()
            if erro is not None:
                label = tk.Label(
                    body,
                    text=f"Erro ao ler temporizadores: {erro}",
                    fg=ORANGE,
                    bg=BG,
                    anchor="w",
                    justify="left",
                    wraplength=260,
                    font=FONT_WS,
                )
                _style_label(label, ORANGE, BG)
                register_testid(label, f"fp-{frequency}-error")
                label.pack(fill="x", padx=4, pady=4)
                self._order[frequency] = []
                continue
            timers = grouped[frequency]
            if not timers:
                label = tk.Label(
                    body, text=EMPTY_TEXTS[frequency], fg=MUTED, bg=BG, anchor="w",
                    font=FONT_WS,
                )
                _style_label(label, MUTED, BG)
                register_testid(label, f"fp-{frequency}-empty")
                label.pack(fill="x", padx=4, pady=4)
                self._order[frequency] = []
                continue
            ids: list[str] = []
            for timer in timers:
                widget = self.card_factory(body, timer, now)
                widget.pack(fill="x", pady=2)
                self._cards[timer.id] = widget
                ids.append(timer.id)
            self._order[frequency] = ids

    def rerender(self, now: datetime | None = None) -> None:
        """Relê o store e re-renderiza as 3 colunas (contrato 010 -> 011/012)."""
        now = now or datetime.now(timezone.utc)
        erro, timers = self._read_timers()
        if erro is not None:
            self._render(erro, None, now)
            return
        self._render(None, group_by_frequency(timers, now), now)

    # -- cards (D1, D10) -----------------------------------------------------

    def _make_card(self, parent, timer, now) -> TimerCard:
        """Fabrica o `TimerCard` com os handlers das acoes (contrato 011)."""
        card = TimerCard(
            parent,
            timer,
            on_edit=lambda: self.edit_timer(timer.id),
            on_alert=lambda: self.toggle_alert(timer.id),
            on_pause=lambda: self.toggle_pause(timer.id),
            on_plus_one=lambda: self.restart_one_hour(timer.id),
            on_delete=lambda: self.delete_timer(timer.id),
        )
        card.apply(timer, now)
        return card

    def _update_card(self, widget, timer, now) -> None:
        """Atualiza o card in place; fabrica trocada por teste fica intocado."""
        if isinstance(widget, TimerCard):
            widget.apply(timer, now)

    # -- acoes dos cards (D6, D7, D8, D9) ------------------------------------

    def _find_timer(self, timer_id):
        """Timer fresco do store por `timer_id`, ou None se nao existe (D6)."""
        if self.store is None:
            return None
        return next((t for t in self.store.list_clock_timers() if t.id == timer_id), None)

    def _falha_de_acao(self, acao: str, titulo, exc, now) -> bool:
        """Mensagem de erro de uma acao + rerender; sempre devolve False (D8)."""
        messagebox.showerror(
            "Temporizadores", f'Nao foi possivel {acao} "{titulo}": {exc}', parent=self.frame
        )
        self.rerender(now)
        return False

    def edit_timer(self, timer_id: str) -> bool:
        """Dispara a edicao de `timer_id` via `on_edit` (contrato 011 -> 012)."""
        now = datetime.now(timezone.utc)
        if self.store is None:
            return False
        acao = "editar"
        titulo = timer_id
        try:
            timer = self._find_timer(timer_id)
            if timer is None:
                raise timers_store.ClockTimerNotFoundError(
                    f"ClockTimer {timer_id!r} nao encontrado"
                )
            titulo = timer.title
        except (sqlite3.Error, OSError, timers_store.ClockTimerNotFoundError) as exc:
            return self._falha_de_acao(acao, titulo, exc, now)
        if self.on_edit is None:
            messagebox.showinfo(
                "Editar timer", "A edicao de timers ainda nao esta disponivel.", parent=self.frame
            )
            return False
        self.on_edit(timer)
        return True

    def toggle_pause(self, timer_id: str, now: datetime | None = None) -> bool:
        """Pausa ou retoma `timer_id`; recusa timer zerado (D6)."""
        now = now or datetime.now(timezone.utc)
        if self.store is None:
            return False
        acao = "pausar"
        titulo = timer_id
        try:
            timer = self._find_timer(timer_id)
            if timer is None:
                raise timers_store.ClockTimerNotFoundError(
                    f"ClockTimer {timer_id!r} nao encontrado"
                )
            titulo = timer.title
            remaining = timers_store._remaining_seconds(timer, now)
            if remaining <= 0:
                return False
            if timer.paused:
                acao = "retomar"
                fim = timers_store._parse_iso(timer.ends_at)
                pausa = timers_store._parse_iso(timer.paused_at)
                if fim is not None and pausa is not None:
                    timer.ends_at = (fim + (now - pausa)).isoformat()
                timer.paused = False
                timer.paused_at = None
            else:
                timer.paused = True
                timer.paused_at = now.isoformat()
                timer.remaining_seconds = remaining
            self.store.update_clock_timer(timer)
        except (sqlite3.Error, OSError, timers_store.ClockTimerNotFoundError) as exc:
            return self._falha_de_acao(acao, titulo, exc, now)
        self.rerender(now)
        return True

    def toggle_alert(self, timer_id: str, now: datetime | None = None) -> bool:
        """Alterna o semaforo manual de `timer_id`; recusa zerado (D6)."""
        now = now or datetime.now(timezone.utc)
        if self.store is None:
            return False
        acao = "alternar o alerta de"
        titulo = timer_id
        try:
            timer = self._find_timer(timer_id)
            if timer is None:
                raise timers_store.ClockTimerNotFoundError(
                    f"ClockTimer {timer_id!r} nao encontrado"
                )
            titulo = timer.title
            if timers_store._remaining_seconds(timer, now) <= 0:
                return False
            timer.alert = not bool(timer.alert)
            self.store.update_clock_timer(timer)
        except (sqlite3.Error, OSError, timers_store.ClockTimerNotFoundError) as exc:
            return self._falha_de_acao(acao, titulo, exc, now)
        self.rerender(now)
        return True

    def delete_timer(self, timer_id: str, now: datetime | None = None) -> bool:
        """Apaga `timer_id` zerado ou pausado, apos confirmacao (D6, D7)."""
        now = now or datetime.now(timezone.utc)
        if self.store is None:
            return False
        acao = "excluir"
        titulo = timer_id
        try:
            timer = self._find_timer(timer_id)
            if timer is None:
                raise timers_store.ClockTimerNotFoundError(
                    f"ClockTimer {timer_id!r} nao encontrado"
                )
            titulo = timer.title
            remaining = timers_store._remaining_seconds(timer, now)
            if remaining > 0 and not timer.paused:
                return False
            if not messagebox.askyesno(
                "Excluir temporizador",
                f'Excluir o temporizador "{timer.title}"?',
                parent=self.frame,
            ):
                return False
            self.store.delete_clock_timer(timer.id)
        except (sqlite3.Error, OSError, timers_store.ClockTimerNotFoundError) as exc:
            return self._falha_de_acao(acao, titulo, exc, now)
        self.rerender(now)
        return True

    def restart_one_hour(self, timer_id: str, now: datetime | None = None) -> bool:
        """Reinicia `timer_id` zerado com +1h e alerta verde (D6)."""
        now = now or datetime.now(timezone.utc)
        if self.store is None:
            return False
        acao = "reiniciar"
        titulo = timer_id
        try:
            timer = self._find_timer(timer_id)
            if timer is None:
                raise timers_store.ClockTimerNotFoundError(
                    f"ClockTimer {timer_id!r} nao encontrado"
                )
            titulo = timer.title
            if timers_store._remaining_seconds(timer, now) > 0:
                return False
            timer.duration_seconds = 3600
            timer.remaining_seconds = 3600
            timer.ends_at = (now + timedelta(seconds=3600)).isoformat()
            timer.state = "running"
            timer.paused = False
            timer.paused_at = None
            timers_store._reset_alert(timer)
            self.store.update_clock_timer(timer)
        except (sqlite3.Error, OSError, timers_store.ClockTimerNotFoundError) as exc:
            return self._falha_de_acao(acao, titulo, exc, now)
        self.rerender(now)
        return True

    # -- modal de cadastro e edicao (D1, D2) ---------------------------------

    def open_add_dialog(self):
        """Abre o modal de cadastro (contrato 008 -> 012)."""
        return self._open_dialog(None)

    def open_edit_dialog(self, timer):
        """Abre o modal de edicao de `timer` (contrato 011 -> 012)."""
        return self._open_dialog(timer)

    def _open_dialog(self, timer):
        if self.store is None:
            messagebox.showerror(
                "Temporizadores",
                f"Banco de timers indisponivel: {self.boot_error or 'sem detalhe'}",
                parent=self.frame,
            )
            return None
        if self._dialog is not None:
            try:
                if self._dialog.winfo_exists():
                    self._dialog.lift()
                    self._dialog.focus_force()
                    return self._dialog
            except tk.TclError:
                pass
            self._dialog = None
        self._dialog = TimerDialog(self, timer)
        return self._dialog

    # -- tick de 1 Hz (D8) ---------------------------------------------------

    def tick(self, now: datetime | None = None) -> bool:
        """Aplica o roll e atualiza os cards; False = parar o ticker."""
        if self.store is None:
            return False
        now = now or datetime.now(timezone.utc)
        try:
            rolled = self.store.roll_due_fixed_timers(now)
            timers = self.store.list_clock_timers()
        except (sqlite3.Error, OSError, timers_store.ClockTimerNotFoundError) as exc:
            self._render(
                f"{exc} (atualizacao automatica pausada; reabra o Forge Pick)", None, now
            )
            return False
        grouped = group_by_frequency(timers, now)
        ordem_mudou = any(
            self._order[frequency] != [timer.id for timer in grouped[frequency]]
            for frequency, _titulo in FREQUENCY_COLUMNS
        )
        if rolled or ordem_mudou:
            self._render(None, grouped, now)
            return True
        for timer in timers:
            widget = self._cards.get(timer.id)
            if widget is not None:
                self.card_updater(widget, timer, now)
        return True

    def start_tick(self) -> None:
        """Agenda o proximo tick; no-op sem store ou com tick ja agendado."""
        if self.store is None or self._after_id is not None:
            return
        self._after_id = self.frame.after(1000, self._on_tick)

    def _on_tick(self) -> None:
        self._after_id = None
        if not self.tick():
            return
        try:
            if self.frame.winfo_exists():
                self._after_id = self.frame.after(1000, self._on_tick)
        except tk.TclError:
            return

    def stop_tick(self) -> None:
        """Cancela o tick agendado (destroy da view ou parada em erro)."""
        if self._after_id is None:
            return
        try:
            self.frame.after_cancel(self._after_id)
        except tk.TclError:
            pass
        self._after_id = None

    def _on_frame_destroy(self, event) -> None:
        # <Destroy> chega tambem pelos filhos: so o frame da view encerra o tick.
        if event.widget is self.frame:
            self.stop_tick()

    # -- roda do mouse por coluna (D4) ---------------------------------------

    def on_mousewheel(self, event) -> bool:
        """Rola apenas a coluna sob o cursor; True quando o evento foi tratado."""
        x_root = getattr(event, "x_root", None)
        y_root = getattr(event, "y_root", None)
        if x_root is None or y_root is None:
            return False
        try:
            widget = self.frame.winfo_containing(x_root, y_root)
        except (KeyError, tk.TclError):
            return False
        frequency = self._frequency_of(widget)
        if frequency is None:
            return False
        num = getattr(event, "num", None)
        if num == 4:
            passos = -1
        elif num == 5:
            passos = 1
        else:
            passos = int(-1 * ((getattr(event, "delta", 0) or 0) / 120))
        if passos == 0:
            return False
        canvas = self._columns[frequency]["canvas"]
        if canvas.yview() != (0.0, 1.0):
            canvas.yview_scroll(passos, "units")
        return True

    def _frequency_of(self, widget) -> str | None:
        """Coluna dona de `widget`, subindo por `.master` ate a section."""
        atual = widget
        while atual is not None:
            for frequency, coluna in self._columns.items():
                if atual is coluna["section"]:
                    return frequency
            atual = getattr(atual, "master", None)
        return None
