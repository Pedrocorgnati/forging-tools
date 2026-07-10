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
from tkinter import ttk

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


def _extract_github_path(data: dict) -> str:
    """Extract the best available GitHub string from a project JSON."""
    github_data = data.get("github")
    if isinstance(github_data, str):
        return github_data
    if isinstance(github_data, dict):
        return (
            github_data.get("ssh_url", "")
            or github_data.get("url", "")
            or (
                f"https://github.com/{github_data['owner']}/{github_data['repo_slug']}"
                if github_data.get("owner") and github_data.get("repo_slug")
                else ""
            )
        )

    credentials = data.get("credentials", {})
    credentials_github = credentials.get("github", {})
    if isinstance(credentials_github, dict):
        return (
            credentials_github.get("ssh_url", "")
            or credentials_github.get("url", "")
            or (
                f"https://github.com/{credentials_github['owner']}/{credentials_github['repo_slug']}"
                if credentials_github.get("owner") and credentials_github.get("repo_slug")
                else ""
            )
        )

    bf = data.get("basic_flow", {})
    return bf.get("github_ssh", "") or bf.get("github", "")


def _read_workspace_file(workspace_root: str, filename: str) -> str:
    """Read a file from the workspace root of a project."""
    if not workspace_root:
        return ""

    workspace_path = Path(workspace_root)
    if not workspace_path.is_absolute():
        workspace_path = FORGE_ROOT / workspace_path

    target = workspace_path / filename
    try:
        return target.read_text(encoding="utf-8")
    except Exception:
        return ""


def load_projects() -> list[tuple]:
    """Return list of project entries shown in the launcher."""
    favorites = load_favorites()
    projects = []
    for json_file in sorted(PROJECTS_DIR.glob("*.json")):
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
            name = data.get("name") or json_file.stem
            commercial = data.get("commercial_name") or name.replace("-", " ").title()
            rel_path = f".claude/projects/{json_file.name}"
            bf = data.get("basic_flow", {})
            workspace  = bf.get("workspace_root", "") or ""
            wbs_root   = bf.get("wbs_root",        "") or ""
            brief_root = bf.get("brief_root",       "") or ""
            docs_root  = bf.get("docs_root",        "") or ""
            github = _extract_github_path(data)
            env_content = _read_workspace_file(workspace, ".env")
            env_production_content = _read_workspace_file(workspace, ".env.production")
            projects.append(
                (
                    name,
                    commercial,
                    rel_path,
                    workspace,
                    wbs_root,
                    brief_root,
                    docs_root,
                    github,
                    env_content,
                    env_production_content,
                )
            )
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


# ── colours (Catppuccin Mocha) ────────────────────────────────────────────────
BG      = "#1e1e2e"
SURFACE = "#313244"
HOVER   = "#45475a"
FG      = "#cdd6f4"
MUTED   = "#6c7086"
ACCENT  = "#89b4fa"   # blue
GREEN   = "#a6e3a1"
YELLOW  = "#f9e2af"
VIOLET  = "#b4befe"
CYAN    = "#89dceb"
ORANGE  = "#fab387"

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
        self.create_arc(0, 0, r*2, r*2, start=90, extent=90, fill=fill, outline=fill)
        self.create_arc(w-r*2, 0, w, r*2, start=0, extent=90, fill=fill, outline=fill)
        self.create_arc(0, h-r*2, r*2, h, start=180, extent=90, fill=fill, outline=fill)
        self.create_arc(w-r*2, h-r*2, w, h, start=270, extent=90, fill=fill, outline=fill)
        self.create_rectangle(r, 0, w-r, h, fill=fill, outline=fill)
        self.create_rectangle(0, r, w, h-r, fill=fill, outline=fill)
        x = r if self._anchor == "w" else w // 2
        anchor = "w" if self._anchor == "w" else "center"
        self.create_text(
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
        if bg not in (BG,):
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
        self.resizable(True, True)
        self.minsize(420, 200)
        self.geometry("480x520")
        self.configure(bg=BG)
        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", lambda *_: self._load_buttons())
        self._build_header()
        tk.Frame(self, bg=SURFACE, height=1).pack(fill="x", padx=16, pady=(0, 4))
        self._build_scrollable_area()
        self._load_buttons()

    # ── header ────────────────────────────────────────────────────────────────

    def _build_header(self) -> None:
        header = tk.Frame(self, bg=BG)
        header.pack(fill="x", padx=16, pady=(12, 6))

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

        # search box — filtra a lista de projetos ao vivo
        search_wrap = tk.Frame(header, bg=SURFACE, highlightthickness=0, bd=0)
        search_wrap.pack(side="right", padx=(0, 8), pady=4)
        tk.Label(search_wrap, text="⌕", font=("Ubuntu", 11), bg=SURFACE, fg=MUTED).pack(
            side="left", padx=(8, 2)
        )
        search_entry = tk.Entry(
            search_wrap,
            textvariable=self._search_var,
            font=FONT_PATH,
            width=18,
            bg=SURFACE,
            fg=FG,
            insertbackground=FG,
            relief="flat",
            bd=0,
            highlightthickness=0,
        )
        search_entry.pack(side="left", padx=(0, 8), pady=6, ipady=2)
        search_entry.bind("<Escape>", lambda _e: self._search_var.set(""))

    # ── scrollable area ───────────────────────────────────────────────────────

    def _build_scrollable_area(self) -> None:
        container = tk.Frame(self, bg=BG)
        container.pack(fill="both", expand=True, padx=16, pady=(0, 10))
        container.grid_rowconfigure(0, weight=1)
        container.grid_columnconfigure(0, weight=1)

        # Scrollbar vertical (ttk para ficar estilizado)
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "FP.Vertical.TScrollbar",
            troughcolor=BG,
            background=SURFACE,
            arrowcolor=MUTED,
            bordercolor=BG,
            lightcolor=SURFACE,
            darkcolor=SURFACE,
        )

        self._canvas = tk.Canvas(container, bg=BG, highlightthickness=0)
        scrollbar = ttk.Scrollbar(
            container, orient="vertical",
            command=self._canvas.yview,
            style="FP.Vertical.TScrollbar",
        )
        self._canvas.configure(yscrollcommand=scrollbar.set)

        self._canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        # Frame interno do canvas (onde as linhas são inseridas)
        self._buttons_frame = tk.Frame(self._canvas, bg=BG)
        self._canvas_window = self._canvas.create_window(
            (0, 0), window=self._buttons_frame, anchor="nw"
        )

        self._buttons_frame.bind("<Configure>", self._on_frame_configure)
        self._canvas.bind("<Configure>", self._on_canvas_resize)

        # Scroll via mouse wheel
        self._canvas.bind_all("<MouseWheel>",    self._on_mousewheel)
        self._canvas.bind_all("<Button-4>",      self._on_mousewheel)
        self._canvas.bind_all("<Button-5>",      self._on_mousewheel)

    def _on_frame_configure(self, _event=None) -> None:
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_canvas_resize(self, event) -> None:
        self._canvas.itemconfig(self._canvas_window, width=event.width)

    def _on_mousewheel(self, event) -> None:
        if event.num == 4:
            self._canvas.yview_scroll(-1, "units")
        elif event.num == 5:
            self._canvas.yview_scroll(1, "units")
        elif hasattr(event, "delta"):
            self._canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    # ── buttons ───────────────────────────────────────────────────────────────

    def _load_buttons(self) -> None:
        for widget in self._buttons_frame.winfo_children():
            widget.destroy()

        projects = load_projects()
        query = self._search_var.get().strip().lower()
        if query:
            projects = [
                p for p in projects
                if query in p[0].lower() or query in p[1].lower()
            ]

        if not projects:
            tk.Label(
                self._buttons_frame,
                text="Nenhum projeto corresponde." if query else "Nenhum projeto encontrado.",
                font=FONT_PATH,
                bg=BG,
                fg=MUTED,
            ).pack(pady=16)
            return

        for name, commercial, path, workspace, wbs_root, brief_root, docs_root, github, env_content, env_production_content in projects:
            self._make_row(
                name,
                commercial,
                path,
                workspace,
                wbs_root,
                brief_root,
                docs_root,
                github,
                env_content,
                env_production_content,
            )

        self._on_frame_configure()

    def _make_row(
        self,
        name: str,
        commercial: str,
        path: str,
        workspace: str,
        wbs_root: str,
        brief_root: str,
        docs_root: str,
        github: str,
        env_content: str,
        env_production_content: str,
    ) -> None:
        outer = tk.Frame(self._buttons_frame, bg=BG)
        outer.pack(fill="x", pady=(0, 4))

        # ── Linha 1: fav dot + nome ──
        top = tk.Frame(outer, bg=BG)
        top.pack(fill="x")

        FavDot(top, name, on_toggle=self._load_buttons).pack(
            side="left", padx=(0, 6), anchor="center"
        )

        tk.Label(
            top,
            text=commercial,
            font=FONT_BTN,
            bg=BG,
            fg=FG,
            anchor="w",
        ).pack(side="left", fill="x", expand=True)

        # ── Linha 2: botões de ação ──
        btns = tk.Frame(outer, bg=BG)
        btns.pack(fill="x", pady=(2, 0))

        _BTN_PADY = 5
        _BTN_PADX = 8

        for text, value, fg_color in [
            ("JSON",  path,       YELLOW),
            ("WS",    workspace,  GREEN),
            ("wbs",   wbs_root,   VIOLET),
            ("brief", brief_root, CYAN),
            ("docs",  docs_root,  ORANGE),
            ("github", github,    ACCENT),
            (".env", env_content, FG),
            (".env.production", env_production_content, FG),
        ]:
            disabled = not bool(value)
            btn = RoundedButton(
                btns,
                text=text,
                font=FONT_WS,
                bg=SURFACE if not disabled else BG,
                fg=fg_color if not disabled else MUTED,
                hover_bg=HOVER if not disabled else BG,
                padx=_BTN_PADX,
                pady=_BTN_PADY,
                anchor="center",
                disabled=disabled,
            )
            btn.pack(side="left", padx=(0, 4))
            if not disabled:
                btn.set_command(
                    lambda b=btn, v=value, t=text, f=fg_color: self._click(b, t, v, SURFACE, f)
                )

        # Separador fino
        tk.Frame(self._buttons_frame, bg=SURFACE, height=1).pack(fill="x", pady=(2, 0))

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
