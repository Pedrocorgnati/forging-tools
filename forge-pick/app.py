#!/usr/bin/env python3
"""
Forge Pick — Project path launcher for SystemForge

Reads .claude/projects/*.json and types the relative path
on button click via xdotool after a 3-second delay.
"""

import json
import subprocess
import threading
import time
import tkinter as tk
from pathlib import Path

# Resolve systemForge root: ai-forge/forging-tools/forge-pick/app.py -> go up 3 levels
SCRIPT_DIR = Path(__file__).resolve().parent
FORGE_ROOT = SCRIPT_DIR.parent.parent.parent
PROJECTS_DIR = FORGE_ROOT / ".claude" / "projects"
FAVORITES_FILE = SCRIPT_DIR / "favorites.json"


def load_favorites() -> set[str]:
    """Load set of favorited project names from disk."""
    try:
        return set(json.loads(FAVORITES_FILE.read_text(encoding="utf-8")))
    except Exception:
        return set()


def save_favorites(favs: set[str]) -> None:
    FAVORITES_FILE.write_text(json.dumps(sorted(favs), ensure_ascii=False, indent=2), encoding="utf-8")


def load_projects() -> list[tuple[str, str, str, str]]:
    """Return list of (name, commercial_name, config_path, workspace_root) sorted by favorites first."""
    favorites = load_favorites()
    projects = []
    for json_file in sorted(PROJECTS_DIR.glob("*.json")):
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
    """Wait 3 seconds then type path via xdotool."""
    time.sleep(2)
    subprocess.run(
        ["xdotool", "type", "--clearmodifiers", "--", path],
        check=False,
    )


# ── colours (Catppuccin Mocha) ────────────────────────────────────────────────
BG      = "#1e1e2e"
SURFACE = "#313244"
HOVER   = "#45475a"
FG      = "#cdd6f4"
MUTED   = "#6c7086"
ACCENT  = "#89b4fa"   # blue — active/typing state
GREEN   = "#a6e3a1"   # workspace button accent
YELLOW  = "#f9e2af"   # favorite star colour

# ── fonts ─────────────────────────────────────────────────────────────────────
FONT_TITLE    = ("Ubuntu", 13, "bold")
FONT_SUBTITLE = ("DejaVu Sans", 8)
FONT_BTN      = ("Ubuntu", 10, "bold")
FONT_WS       = ("Ubuntu", 9)
FONT_PATH     = ("DejaVu Sans", 8)

RADIUS = 5


# ── rounded button ────────────────────────────────────────────────────────────

class RoundedButton(tk.Canvas):
    """Canvas-based button with configurable border-radius."""

    def __init__(
        self,
        parent,
        text: str,
        command=None,
        bg: str = SURFACE,
        fg: str = FG,
        hover_bg: str = HOVER,
        font=FONT_BTN,
        padx: int = 14,
        pady: int = 8,
        radius: int = RADIUS,
        anchor: str = "center",
        disabled: bool = False,
        **kwargs,
    ):
        self._bg = bg
        self._fg = fg
        self._hover_bg = hover_bg
        self._font = font
        self._padx = padx
        self._pady = pady
        self._radius = radius
        self._text = text
        self._anchor = anchor
        self._command = command
        self._disabled = disabled

        # Measure text size to auto-size canvas
        dummy = tk.Label(font=font, text=text)
        tw = dummy.winfo_reqwidth()
        th = dummy.winfo_reqheight()
        self._btn_w = tw + padx * 2
        self._btn_h = th + pady * 2

        super().__init__(
            parent,
            width=self._btn_w,
            height=self._btn_h,
            bg=parent["bg"],
            highlightthickness=0,
            bd=0,
            cursor="hand2" if not disabled else "arrow",
            **kwargs,
        )

        self._rect = None
        self._label = None
        self._draw(bg)

        if not disabled:
            self.bind("<Enter>", lambda e: self._draw(hover_bg))
            self.bind("<Leave>", lambda e: self._draw(self._bg))
            self.bind("<ButtonPress-1>", self._on_press)
            self.bind("<ButtonRelease-1>", self._on_release)

    def _draw(self, fill: str) -> None:
        self.delete("all")
        r, w, h = self._radius, self._btn_w, self._btn_h
        # Draw rounded rectangle via polygon + arcs
        self.create_arc(0, 0, r*2, r*2, start=90, extent=90, fill=fill, outline=fill)
        self.create_arc(w-r*2, 0, w, r*2, start=0, extent=90, fill=fill, outline=fill)
        self.create_arc(0, h-r*2, r*2, h, start=180, extent=90, fill=fill, outline=fill)
        self.create_arc(w-r*2, h-r*2, w, h, start=270, extent=90, fill=fill, outline=fill)
        self.create_rectangle(r, 0, w-r, h, fill=fill, outline=fill)
        self.create_rectangle(0, r, w, h-r, fill=fill, outline=fill)
        # Text
        x = r if self._anchor == "w" else w // 2
        anchor = "w" if self._anchor == "w" else "center"
        self._label_id = self.create_text(
            x + (self._padx - r if self._anchor == "w" else 0),
            h // 2,
            text=self._text,
            fill=self._fg,
            font=self._font,
            anchor=anchor,
        )

    def _on_press(self, _event) -> None:
        self._draw(ACCENT if self._bg == SURFACE else self._hover_bg)

    def _on_release(self, _event) -> None:
        self._draw(self._hover_bg)
        if self._command:
            self._command()

    def set_command(self, command) -> None:
        self._command = command

    def configure_state(self, text: str, bg: str, fg: str) -> None:
        self._bg = bg
        self._fg = fg
        self._text = text
        if bg == BG or bg == SURFACE or bg == GREEN:
            self._disabled = False
            self.configure(cursor="hand2")
        self._draw(bg)


# ── favourite dot ─────────────────────────────────────────────────────────────

class FavDot(tk.Canvas):
    """Small circle that toggles favourite state for a project."""

    SIZE = 14

    def __init__(self, parent, name: str, on_toggle, **kwargs):
        super().__init__(
            parent,
            width=self.SIZE,
            height=self.SIZE,
            bg=parent["bg"],
            highlightthickness=0,
            bd=0,
            cursor="hand2",
            **kwargs,
        )
        self._name = name
        self._on_toggle = on_toggle
        self._favs = load_favorites()
        self._draw()
        self.bind("<ButtonRelease-1>", self._toggle)

    def _is_fav(self) -> bool:
        return self._name in self._favs

    def _draw(self) -> None:
        self.delete("all")
        color = YELLOW if self._is_fav() else MUTED
        pad = 2
        self.create_oval(pad, pad, self.SIZE - pad, self.SIZE - pad, fill=color, outline=color)

    def _toggle(self, _event) -> None:
        self._favs = load_favorites()
        if self._is_fav():
            self._favs.discard(self._name)
        else:
            self._favs.add(self._name)
        save_favorites(self._favs)
        self._on_toggle()


# ── app ───────────────────────────────────────────────────────────────────────

class ForgePick(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Forge Pick")
        self.resizable(False, False)
        self.configure(bg=BG)
        self._build_header()
        tk.Frame(self, bg=SURFACE, height=1).pack(fill="x", padx=16, pady=(0, 8))
        self._buttons_frame = tk.Frame(self, bg=BG)
        self._buttons_frame.pack(fill="both", expand=True, padx=16, pady=(0, 12))
        self._load_buttons()

    # ── header ────────────────────────────────────────────────────────────────

    def _build_header(self) -> None:
        header = tk.Frame(self, bg=BG)
        header.pack(fill="x", padx=16, pady=(14, 8))

        left = tk.Frame(header, bg=BG)
        left.pack(side="left")
        tk.Label(left, text="Forge Pick", font=FONT_TITLE, bg=BG, fg=FG).pack(anchor="w")
        tk.Label(left, text="project launcher", font=FONT_SUBTITLE, bg=BG, fg=MUTED).pack(anchor="w")

        RoundedButton(
            header,
            text="⟳",
            command=self._load_buttons,
            font=("Ubuntu", 13),
            padx=10,
            pady=6,
            anchor="center",
        ).pack(side="right")

    # ── buttons ───────────────────────────────────────────────────────────────

    def _load_buttons(self) -> None:
        for widget in self._buttons_frame.winfo_children():
            widget.destroy()

        projects = load_projects()
        if not projects:
            tk.Label(
                self._buttons_frame,
                text="Nenhum projeto encontrado.",
                font=FONT_PATH,
                bg=BG,
                fg=MUTED,
            ).pack(pady=16)
            return

        for name, commercial, path, workspace in projects:
            self._make_row(name, commercial, path, workspace)

    def _make_row(self, name: str, commercial: str, path: str, workspace: str) -> None:
        row = tk.Frame(self._buttons_frame, bg=BG)
        row.pack(fill="x", pady=(0, 5))

        # favourite dot
        FavDot(row, name, on_toggle=self._load_buttons).pack(
            side="left", padx=(0, 6), anchor="center"
        )

        # commercial name label — fills available width
        name_frame = tk.Frame(row, bg=BG)
        name_frame.pack(side="left", fill="x", expand=True)
        tk.Label(
            name_frame,
            text=commercial,
            font=FONT_BTN,
            bg=BG,
            fg=FG,
            anchor="w",
        ).pack(fill="x", padx=(6, 0), anchor="w")

        # JSON button (yellow text, small fixed width)
        BTN_W = 50
        json_btn = RoundedButton(
            row,
            text="JSON",
            font=FONT_WS,
            bg=SURFACE,
            fg=YELLOW,
            hover_bg=HOVER,
            padx=10,
            pady=8,
            anchor="center",
        )
        json_btn.pack(side="right", padx=(4, 0))
        json_btn.configure(width=BTN_W)
        json_btn._btn_w = BTN_W
        json_btn._draw(json_btn._bg)
        json_btn.set_command(
            lambda b=json_btn, p=path, n="JSON": self._click(b, n, p, SURFACE, YELLOW)
        )

        # WS button (same small fixed width)
        ws_btn = RoundedButton(
            row,
            text="WS",
            font=FONT_WS,
            bg=SURFACE if workspace else BG,
            fg=GREEN if workspace else MUTED,
            hover_bg=HOVER if workspace else BG,
            padx=10,
            pady=8,
            anchor="center",
            disabled=not workspace,
        )
        ws_btn.pack(side="right", padx=(4, 0))
        ws_btn.configure(width=BTN_W)
        ws_btn._btn_w = BTN_W
        ws_btn._draw(ws_btn._bg)
        if workspace:
            ws_btn.set_command(
                lambda b=ws_btn, w=workspace: self._click(b, "WS", w, SURFACE, GREEN)
            )

    def _click(
        self,
        btn: RoundedButton,
        original_text: str,
        path: str,
        original_bg: str,
        original_fg: str,
    ) -> None:
        btn.configure(cursor="arrow")
        btn.unbind("<Enter>")
        btn.unbind("<Leave>")
        btn.configure_state("typing…", ACCENT, BG)
        threading.Thread(
            target=self._type_and_restore,
            args=(btn, original_text, path, original_bg, original_fg),
            daemon=True,
        ).start()

    def _type_and_restore(
        self,
        btn: RoundedButton,
        original_text: str,
        path: str,
        original_bg: str,
        original_fg: str,
    ) -> None:
        _type_worker(path)
        def restore():
            btn.configure_state(original_text, original_bg, original_fg)
            btn.bind("<Enter>", lambda e: btn._draw(btn._hover_bg))
            btn.bind("<Leave>", lambda e: btn._draw(btn._bg))
            btn.configure(cursor="hand2")
        self.after(0, restore)


if __name__ == "__main__":
    ForgePick().mainloop()
