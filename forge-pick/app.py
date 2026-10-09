#!/usr/bin/env python3
"""
Forge Pick — Project path launcher for SystemForge

Reads .claude/projects/*.json and types the relative path
on button click via xdotool after a 3-second delay.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk
from pathlib import Path
import timers_store
import timers_ui
from datatest_overlay import DataTestController, register_testid, testid_slug

# Resolve systemForge root: ai-forge/forging-tools/forge-pick/app.py -> go up 3 levels
SCRIPT_DIR = Path(__file__).resolve().parent
FORGE_ROOT = SCRIPT_DIR.parent.parent.parent
PROJECTS_DIR = FORGE_ROOT / ".claude" / "projects"
FAVORITES_FILE = SCRIPT_DIR / "favorites.json"
SETTINGS_FILE = Path.home() / ".local" / "share" / "forge-pick" / "settings.json"


def load_favorites_ordered() -> list[str]:
    """Return ordered list of favorite project names (preserves drag order)."""
    try:
        data = json.loads(FAVORITES_FILE.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return [str(item) for item in data]
        return []
    except Exception:
        return []


def load_favorites() -> set[str]:
    return set(load_favorites_ordered())


def save_favorites(favs_ordered: list[str]) -> None:
    """Save favorites as ordered list — no sorting, preserves user-defined order."""
    FAVORITES_FILE.parent.mkdir(parents=True, exist_ok=True)
    FAVORITES_FILE.write_text(
        json.dumps(favs_ordered, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def toggle_favorite(name: str) -> None:
    """Add or remove a project from favorites, preserving existing order."""
    current = load_favorites_ordered()
    if name in current:
        current.remove(name)
    else:
        current.append(name)
    save_favorites(current)


def load_show_all() -> bool:
    """Whether the list shows every project. Default: favorites only."""
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return bool(data.get("show_all", False))
    except Exception:
        pass
    return False


def save_show_all(show_all: bool) -> None:
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    current: dict = {}
    try:
        loaded = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            current = loaded
    except Exception:
        current = {}
    current["show_all"] = bool(show_all)
    SETTINGS_FILE.write_text(
        json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8"
    )


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
    return projects


def _type_worker(path: str) -> None:
    """Wait 2 seconds then type path via xdotool."""
    time.sleep(2)
    subprocess.run(
        ["xdotool", "type", "--clearmodifiers", "--", path],
        check=False,
    )


def _resolve_workspace_dir(workspace: str) -> Path | None:
    """Return absolute existing directory for a project's workspace_root."""
    if not workspace or not str(workspace).strip():
        return None
    path = Path(str(workspace).strip()).expanduser()
    if not path.is_absolute():
        path = FORGE_ROOT / path
    try:
        path = path.resolve()
    except OSError:
        return None
    return path if path.is_dir() else None


def _open_linux_terminal(cwd: Path) -> bool:
    """Open a system terminal with cwd set to the project workspace."""
    cwd_s = str(cwd)
    candidates = (
        ("gnome-terminal", ["--working-directory", cwd_s]),
        ("ptyxis", ["--new-window", "--directory", cwd_s]),
        ("kgx", ["--working-directory", cwd_s]),
        ("konsole", ["--workdir", cwd_s]),
        ("xfce4-terminal", [f"--working-directory={cwd_s}"]),
        ("mate-terminal", [f"--working-directory={cwd_s}"]),
        ("tilix", [f"--working-directory={cwd_s}"]),
        ("terminator", [f"--working-directory={cwd_s}"]),
        ("kitty", ["--directory", cwd_s]),
        ("alacritty", ["--working-directory", cwd_s]),
        ("wezterm", ["start", "--cwd", cwd_s]),
        ("ghostty", [f"--working-directory={cwd_s}"]),
        ("x-terminal-emulator", []),
        ("xdg-terminal-exec", []),
        ("xterm", []),
    )
    for binary, args in candidates:
        if shutil.which(binary) is None:
            continue
        try:
            subprocess.Popen(
                [binary, *args],
                cwd=cwd_s,
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        except OSError:
            continue
    return False


def _open_in_file_manager(path: Path) -> bool:
    """Open a directory in the default Linux file manager."""
    path_s = str(path)
    candidates = (
        ("xdg-open", [path_s]),
        ("gio", ["open", path_s]),
        ("nautilus", ["--new-window", path_s]),
    )
    for binary, args in candidates:
        if shutil.which(binary) is None:
            continue
        try:
            subprocess.Popen(
                [binary, *args],
                cwd=path_s,
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        except OSError:
            continue
    return False


def _open_vscode(target: Path) -> bool:
    """Open VS Code at a workspace directory or a specific file."""
    target_s = str(target)
    cwd = target if target.is_dir() else target.parent
    candidates = ("code", "code-insiders", "codium", "code-oss")
    for binary in candidates:
        if shutil.which(binary) is None:
            continue
        try:
            subprocess.Popen(
                [binary, target_s],
                cwd=str(cwd),
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        except OSError:
            continue
    return False


# ── colours (Catppuccin Mocha) ────────────────────────────────────────────────
BG      = "#1e1e2e"
MANTLE  = "#181825"
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
FONT_TITLE    = ("Ubuntu", 18, "bold")
FONT_SUBTITLE = ("DejaVu Sans", 8)
FONT_BTN      = ("Ubuntu", 10, "bold")
FONT_WS       = ("Ubuntu", 9)
FONT_PATH     = ("DejaVu Sans", 8)

RADIUS = 6
SCROLL_HIDE_SPAN = 0.995

# ── abas ─────────────────────────────────────────────────────────────────────
TAB_FORGE_PICK = "forge_pick"
TAB_TIMERS = "timers"
TABS = (TAB_FORGE_PICK, TAB_TIMERS)
TAB_LABELS = {TAB_FORGE_PICK: "Forge Pick", TAB_TIMERS: "Timers"}

BOOT_GEOMETRY = "628x520"
BOOT_MINSIZE = (573, 200)
TIMERS_MIN_WIDTH = 900


def widen_geometry(geometry: str, min_width: int, min_height: int) -> str:
    """Devolve WxH com no minimo min_width x min_height, sem posicao (D2)."""
    match = re.match(r"^(\d+)x(\d+)([+-]-?\d+[+-]-?\d+)?$", geometry)
    if match is None:
        raise ValueError(f"geometria invalida: {geometry!r}")
    w = int(match.group(1))
    h = int(match.group(2))
    return f"{max(w, min_width)}x{max(h, min_height)}"


def scroll_needed(first: float, last: float) -> bool:
    """True when the canvas viewport does NOT cover the full scrollregion (scrollbar needed)."""
    try:
        # If viewport covers 99.5%+ of content, scrollbar is hidden (returns False)
        # If viewport covers < 99.5% of content, scrollbar is shown (returns True)
        return float(last) - float(first) < SCROLL_HIDE_SPAN
    except (TypeError, ValueError):
        return False


def _fill_round_rect(
    canvas: tk.Canvas, x0: float, y0: float, x1: float, y1: float, r: int, fill: str
) -> None:
    w = max(0.0, x1 - x0)
    h = max(0.0, y1 - y0)
    r = max(1, min(int(r), int(w / 2), int(h / 2)))
    canvas.create_arc(x0, y0, x0 + r * 2, y0 + r * 2, start=90, extent=90, fill=fill, outline=fill)
    canvas.create_arc(x1 - r * 2, y0, x1, y0 + r * 2, start=0, extent=90, fill=fill, outline=fill)
    canvas.create_arc(x0, y1 - r * 2, x0 + r * 2, y1, start=180, extent=90, fill=fill, outline=fill)
    canvas.create_arc(x1 - r * 2, y1 - r * 2, x1, y1, start=270, extent=90, fill=fill, outline=fill)
    canvas.create_rectangle(x0 + r, y0, x1 - r, y1, fill=fill, outline=fill)
    canvas.create_rectangle(x0, y0 + r, x1, y1 - r, fill=fill, outline=fill)


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
        toggle_favorite(self._name)
        self._favs = load_favorites()
        self._on_toggle()


class EyeToggle(tk.Canvas):
    """Eye button: selected = show all projects; off = favorites only."""

    WIDTH = 32
    HEIGHT = 30

    def __init__(self, parent, selected: bool, on_toggle, **kwargs):
        super().__init__(
            parent,
            width=self.WIDTH,
            height=self.HEIGHT,
            bg=parent["bg"],
            highlightthickness=0,
            bd=0,
            cursor="hand2",
            **kwargs,
        )
        self._selected = selected
        self._on_toggle = on_toggle
        self._hover = False
        self._draw()
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<ButtonRelease-1>", self._click)

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self._draw()

    def _on_enter(self, _event) -> None:
        self._hover = True
        self._draw()

    def _on_leave(self, _event) -> None:
        self._hover = False
        self._draw()

    def _click(self, _event) -> None:
        if self._on_toggle:
            self._on_toggle()

    def _draw(self) -> None:
        self.delete("all")
        w, h = self.WIDTH, self.HEIGHT
        r = RADIUS
        if self._selected:
            fill = ACCENT if not self._hover else HOVER
            ink = BG
        else:
            fill = HOVER if self._hover else SURFACE
            ink = MUTED
        self.create_arc(0, 0, r * 2, r * 2, start=90, extent=90, fill=fill, outline=fill)
        self.create_arc(w - r * 2, 0, w, r * 2, start=0, extent=90, fill=fill, outline=fill)
        self.create_arc(0, h - r * 2, r * 2, h, start=180, extent=90, fill=fill, outline=fill)
        self.create_arc(w - r * 2, h - r * 2, w, h, start=270, extent=90, fill=fill, outline=fill)
        self.create_rectangle(r, 0, w - r, h, fill=fill, outline=fill)
        self.create_rectangle(0, r, w, h - r, fill=fill, outline=fill)

        cx, cy = w / 2, h / 2
        self.create_oval(cx - 9, cy - 5, cx + 9, cy + 5, outline=ink, width=1.5)
        self.create_oval(cx - 3, cy - 3, cx + 3, cy + 3, outline=ink, fill=ink, width=1)
        if not self._selected:
            self.create_line(cx - 8, cy + 7, cx + 8, cy - 7, fill=ink, width=1.5)


# ── app ───────────────────────────────────────────────────────────────────────

def _hint_linux_desktop_file() -> None:
    """Aponta o dock (BAMF/GNOME) para o .desktop antes de criar a janela.

    Sem isso o processo aparece como python3 e a barra lateral nao casa o
    icone de forge-pick.desktop.
    """
    desktop = Path.home() / ".local" / "share" / "applications" / "forge-pick.desktop"
    if not desktop.is_file():
        return
    os.environ["BAMF_DESKTOP_FILE_HINT"] = str(desktop)
    os.environ.setdefault("GIO_LAUNCHED_DESKTOP_FILE", str(desktop))
    os.environ.setdefault("GIO_LAUNCHED_DESKTOP_FILE_PID", str(os.getpid()))


class ForgePick(tk.Tk):
    def __init__(self) -> None:
        # Tk transforma className "ForgePick" em WM_CLASS ("forgePick","Forgepick"),
        # que NAO casa com StartupWMClass=ForgePick (case-sensitive no GNOME).
        # className/baseName "forge-pick" gera ("forge-pick","Forge-pick") e
        # alinha com o id do .desktop. Nao chamar wm_class(): este Tk 8.6 nao
        # expoe o metodo e o `wm class` do Tcl tambem nao existe aqui.
        _hint_linux_desktop_file()
        super().__init__(className="forge-pick", baseName="forge-pick")
        self.title("Forge Pick")
        self.resizable(True, True)
        self.minsize(*BOOT_MINSIZE)
        self.geometry(BOOT_GEOMETRY)
        self.configure(bg=BG)
        self._window_icon = self._install_window_icon()
        self._set_net_wm_pid()
        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", lambda *_: self._load_buttons())
        self._show_all = load_show_all()
        self._fav_rows: list[tk.Frame] = []
        self._favs_container: tk.Frame | None = None
        self._drag: dict | None = None
        self._active_tab: str | None = None
        self._tab_callbacks: dict[str, list] = {tab: [] for tab in TABS}
        self._tab_buttons: dict[str, RoundedButton] = {}
        self._geometry_before_timers: str | None = None
        self._timers_view = None
        self._datatest = DataTestController(
            self,
            button_classes=(RoundedButton, FavDot, EyeToggle),
            on_panel_change=self._on_datatest_panel_change,
        )
        self._build_header()
        self._install_tab_geometry()
        tk.Frame(self, bg=SURFACE, height=1).pack(fill="x", padx=16, pady=(0, 4))
        self._tab_body = tk.Frame(self, bg=BG)
        self._tab_body.pack(fill="both", expand=True)
        self._tab_frames = {
            TAB_FORGE_PICK: tk.Frame(self._tab_body, bg=BG),
            TAB_TIMERS: tk.Frame(self._tab_body, bg=BG),
        }
        register_testid(self._tab_frames[TAB_FORGE_PICK], "fp-tab-forge-pick")
        register_testid(self._tab_frames[TAB_TIMERS], "fp-tab-timers")
        self._build_scrollable_area()
        self._load_buttons()
        self.switch_tab(TAB_FORGE_PICK)
        self._timers_store, self._timers_boot_error = timers_store.boot_timers_store()
        self._timers_view = timers_ui.TimersView(
            self._tab_frames[TAB_TIMERS], self._timers_store, self._timers_boot_error
        )
        self._timers_view.rerender()
        self._timers_view.start_tick()

    def _install_window_icon(self):
        """Set the window/taskbar icon. Keep the PhotoImage alive on the instance."""
        candidates = (
            SCRIPT_DIR / "assets" / "forge-pick.png",
            Path.home() / ".local" / "share" / "icons" / "forge-pick.png",
        )
        icon_path = next((p for p in candidates if p.is_file()), None)
        if icon_path is None:
            return None
        photo = None
        try:
            from PIL import Image, ImageTk

            img = (
                Image.open(icon_path)
                .convert("RGBA")
                .resize((64, 64), Image.Resampling.LANCZOS)
            )
            photo = ImageTk.PhotoImage(img)
        except Exception:
            try:
                photo = tk.PhotoImage(file=str(icon_path))
                if photo.width() > 128:
                    factor = max(1, photo.width() // 64)
                    photo = photo.subsample(factor, factor)
            except tk.TclError:
                return None
        try:
            self.iconphoto(True, photo)
        except tk.TclError:
            return photo
        return photo

    def _set_net_wm_pid(self) -> None:
        """GNOME/BAMF usam _NET_WM_PID para casar janela com o .desktop.

        Este build de Tk nao publica o atom. winfo_id() aponta a janela
        interna (sem WM_CLASS); a janela visivel pelo dock e a irma com
        WM_CLASS=forge-pick — marcar as duas.
        """
        try:
            self.update_idletasks()
            self.update()
        except tk.TclError:
            return
        wids = {str(int(self.winfo_id()))}
        try:
            listed = subprocess.run(
                ["xdotool", "search", "--name", "Forge Pick"],
                check=False,
                capture_output=True,
                text=True,
                timeout=2,
            )
            wids.update(listed.stdout.split())
        except Exception:  # noqa: BLE001
            pass
        pid = str(os.getpid())
        for wid in wids:
            try:
                klass = subprocess.run(
                    ["xprop", "-id", wid, "WM_CLASS"],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=2,
                ).stdout.lower()
            except Exception:  # noqa: BLE001
                continue
            if "forge-pick" not in klass:
                continue
            try:
                subprocess.run(
                    [
                        "xprop",
                        "-id",
                        wid,
                        "-f",
                        "_NET_WM_PID",
                        "32c",
                        "-set",
                        "_NET_WM_PID",
                        pid,
                    ],
                    check=False,
                    capture_output=True,
                    timeout=2,
                )
            except Exception:  # noqa: BLE001
                continue

    # ── header ────────────────────────────────────────────────────────────────

    def _build_header(self) -> None:
        header = tk.Frame(self, bg=BG)
        header.pack(fill="x", padx=16, pady=(12, 6))
        register_testid(header, "fp-header")

        left = tk.Frame(header, bg=BG)
        left.pack(side="left")
        register_testid(left, "fp-navbar")

        # navbar de abas — toggles exclusivos Forge Pick / Timers (D2)
        for index, tab in enumerate(TABS):
            tab_btn = RoundedButton(
                left,
                text=TAB_LABELS[tab],
                command=lambda t=tab: self.switch_tab(t),
            )
            if tab == TAB_FORGE_PICK:
                register_testid(tab_btn, "fp-navbar-tab-forge-pick")
            else:
                register_testid(tab_btn, "fp-navbar-tab-timers")
            if index == 0:
                tab_btn.pack(side="left", padx=(0, 6))
            else:
                tab_btn.pack(side="left")
            self._tab_buttons[tab] = tab_btn

        self._refresh_btn = RoundedButton(
            header,
            text="⟳",
            command=self._load_buttons,
            font=("Ubuntu", 13),
            padx=6,
            pady=3,
            anchor="center",
        )
        register_testid(self._refresh_btn, "fp-header-refresh-button")

        self._eye_btn = EyeToggle(
            header,
            selected=self._show_all,
            on_toggle=self._toggle_show_all,
        )
        register_testid(self._eye_btn, "fp-header-show-all-toggle")

        # search box — filtra a lista de projetos ao vivo
        self._search_wrap = tk.Frame(header, bg=SURFACE, highlightthickness=0, bd=0)
        register_testid(self._search_wrap, "fp-header-search")
        tk.Label(self._search_wrap, text="⌕", font=("Ubuntu", 11), bg=SURFACE, fg=MUTED).pack(
            side="left", padx=(8, 2)
        )
        search_entry = tk.Entry(
            self._search_wrap,
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
        register_testid(search_entry, "fp-header-search-input")
        search_entry.bind("<Escape>", lambda _e: self._search_var.set(""))

        # botao de adicionar timer, visivel so na aba Timers (D2, contrato 008 -> 012)
        self._clock_add_btn = RoundedButton(
            header,
            text="+",
            command=self._on_clock_add_click,
            font=("Ubuntu", 13),
            padx=6,
            pady=3,
            anchor="center",
        )
        register_testid(self._clock_add_btn, "fp-clock-add-button")

        # botao DataTest: fora da tabela por aba, sempre o mais a direita (item 013)
        self._datatest_btn = RoundedButton(
            header, text="DataTest", command=self._toggle_datatest_panel
        )
        register_testid(self._datatest_btn, "fp-datatest-toggle-button")
        self._datatest_btn.pack(side="right", padx=(6, 0))
        self._datatest.anchor_widget = self._datatest_btn

        # fonte unica de argumentos de pack do header por aba (D3)
        self._header_tab_widgets = {
            TAB_FORGE_PICK: [
                (self._refresh_btn, {"side": "right"}),
                (self._eye_btn, {"side": "right", "padx": (0, 6)}),
                (self._search_wrap, {"side": "right", "padx": (0, 8), "pady": 4}),
            ],
            TAB_TIMERS: [
                (self._clock_add_btn, {"side": "right"}),
            ],
        }
        self._apply_header_for_tab(TAB_FORGE_PICK)
        self.add_tab_callback(
            TAB_FORGE_PICK, lambda _previous: self._apply_header_for_tab(TAB_FORGE_PICK)
        )
        self.add_tab_callback(
            TAB_TIMERS, lambda _previous: self._apply_header_for_tab(TAB_TIMERS)
        )
        self.add_tab_callback(TAB_FORGE_PICK, lambda _p: self._datatest.refresh())
        self.add_tab_callback(TAB_TIMERS, lambda _p: self._datatest.refresh())

    def _on_clock_add_click(self) -> None:
        """Abre o modal de cadastro de timer (contrato 008 -> 012)."""
        self._timers_view.open_add_dialog()

    def _toggle_datatest_panel(self) -> None:
        """Abre ou fecha o painel flutuante DataTest (item 013)."""
        self._datatest.toggle_panel()

    def _on_datatest_panel_change(self, aberto: bool) -> None:
        """Reflete o estado do painel DataTest no botao do header."""
        if aberto:
            self._datatest_btn.configure_state("DataTest", ACCENT, BG)
        else:
            self._datatest_btn.configure_state("DataTest", SURFACE, FG)

    # ── scrollable area ───────────────────────────────────────────────────────

    def _build_scrollable_area(self) -> None:
        container = tk.Frame(self._tab_frames[TAB_FORGE_PICK], bg=BG)
        container.pack(fill="both", expand=True, padx=16, pady=(0, 10))
        register_testid(container, "fp-forge-pick-list")
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
        self._scrollbar = ttk.Scrollbar(
            container, orient="vertical",
            command=self._canvas.yview,
            style="FP.Vertical.TScrollbar",
        )
        self._canvas.configure(yscrollcommand=self._scrollbar.set)

        self._canvas.grid(row=0, column=0, sticky="nsew")
        self._scrollbar.grid(row=0, column=1, sticky="ns")

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
        # Esconder/mostrar scrollbar conforme necessidade
        first, last = self._canvas.yview()
        if scroll_needed(first, last):
            self._scrollbar.grid(row=0, column=1, sticky="ns")
        else:
            self._scrollbar.grid_remove()

    def _on_canvas_resize(self, event) -> None:
        self._canvas.itemconfig(self._canvas_window, width=event.width)
        # Esconder/mostrar scrollbar após redimensionar
        first, last = self._canvas.yview()
        if scroll_needed(first, last):
            self._scrollbar.grid(row=0, column=1, sticky="ns")
        else:
            self._scrollbar.grid_remove()

    def _on_mousewheel(self, event) -> None:
        # roda na aba Timers vai para a coluna sob o cursor (D4 do item 010)
        if self._active_tab == TAB_TIMERS:
            if self._timers_view is not None:
                self._timers_view.on_mousewheel(event)
            return
        # scroll da lista so vale na aba Forge Pick (D7)
        if self._active_tab != TAB_FORGE_PICK:
            return
        if event.num == 4:
            self._canvas.yview_scroll(-1, "units")
        elif event.num == 5:
            self._canvas.yview_scroll(1, "units")
        elif hasattr(event, "delta"):
            self._canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    # ── abas ─────────────────────────────────────────────────────────────────

    @property
    def active_tab(self) -> str | None:
        """Aba atualmente visivel (None antes do boot)."""
        return self._active_tab

    def _refresh_tab_buttons(self) -> None:
        """Indica a aba selecionada nos toggles da navbar (D2)."""
        for tab in TABS:
            btn = self._tab_buttons.get(tab)
            if btn is None:
                continue
            if tab == self._active_tab:
                btn.configure_state(TAB_LABELS[tab], ACCENT, BG)
            else:
                btn.configure_state(TAB_LABELS[tab], SURFACE, FG)

    def add_tab_callback(self, tab: str, callback) -> None:
        """Registra callback(previous) chamado ao entrar na aba (contrato 007 -> 008/009)."""
        if tab not in TABS:
            raise ValueError(f"aba desconhecida: {tab!r}")
        if not callable(callback):
            raise TypeError(f"callback nao chamavel para a aba {tab!r}: {callback!r}")
        self._tab_callbacks[tab].append(callback)

    def switch_tab(self, tab: str) -> None:
        """Torna `tab` a aba ativa e dispara os callbacks registrados dela (D5)."""
        if tab not in TABS:
            raise ValueError(f"aba desconhecida: {tab!r}")
        if tab == self._active_tab:
            return
        previous = self._active_tab
        if previous is not None:
            self._tab_frames[previous].pack_forget()
        self._tab_frames[tab].pack(fill="both", expand=True)
        self._active_tab = tab
        self._refresh_tab_buttons()
        for callback in self._tab_callbacks[tab]:
            try:
                callback(previous)
            except Exception as exc:  # noqa: BLE001
                print(f"[forge-pick] callback da aba {tab} falhou: {exc}", file=sys.stderr)

    def _install_tab_geometry(self) -> None:
        """Registra os callbacks de geometria por aba (D6)."""
        self.add_tab_callback(TAB_TIMERS, self._on_enter_timers_geometry)
        self.add_tab_callback(TAB_FORGE_PICK, self._on_enter_forge_pick_geometry)

    def _on_enter_timers_geometry(self, previous) -> None:
        """Guarda a geometria e alarga para no minimo TIMERS_MIN_WIDTH (D4)."""
        if previous == TAB_TIMERS:
            return
        self.update_idletasks()
        saved = self.geometry()
        self._geometry_before_timers = saved
        self.minsize(TIMERS_MIN_WIDTH, BOOT_MINSIZE[1])
        self.geometry(widen_geometry(saved, TIMERS_MIN_WIDTH, BOOT_MINSIZE[1]))

    def _on_enter_forge_pick_geometry(self, previous) -> None:
        """Restaura a geometria guardada e o minsize de boot (D5)."""
        if previous != TAB_TIMERS or self._geometry_before_timers is None:
            return
        self.minsize(*BOOT_MINSIZE)
        self.geometry(self._geometry_before_timers)
        self._geometry_before_timers = None

    def _apply_header_for_tab(self, tab: str) -> None:
        """Aplica a tabela de pack do header da aba `tab` (D4, fonte unica de pack)."""
        if tab not in TABS:
            raise ValueError(f"aba desconhecida: {tab!r}")
        for entries in self._header_tab_widgets.values():
            for widget, _kwargs in entries:
                widget.pack_forget()
        for widget, kwargs in self._header_tab_widgets[tab]:
            widget.pack(**kwargs)

    # ── buttons ───────────────────────────────────────────────────────────────

    def _load_buttons(self) -> None:
        self._clear_fav_drag()
        self._fav_rows = []
        self._favs_container = None
        for widget in self._buttons_frame.winfo_children():
            widget.destroy()

        all_projects = load_projects()
        fav_order = load_favorites_ordered()
        fav_set = set(fav_order)
        proj_map = {p[0]: p for p in all_projects}

        fav_projects = [proj_map[n] for n in fav_order if n in proj_map]
        other_projects = sorted(
            [p for p in all_projects if p[0] not in fav_set],
            key=lambda p: p[0].lower(),
        )

        query = self._search_var.get().strip().lower()
        if query:
            fav_projects = [
                p for p in fav_projects
                if query in p[0].lower() or query in p[1].lower()
            ]
            other_projects = [
                p for p in other_projects
                if query in p[0].lower() or query in p[1].lower()
            ]

        if not self._show_all:
            other_projects = []

        if not fav_projects and not other_projects:
            if query:
                empty = "Nenhum projeto corresponde."
            elif not self._show_all:
                empty = "Nenhum favorito. Clique no olho para ver todos."
            else:
                empty = "Nenhum projeto encontrado."
            tk.Label(
                self._buttons_frame,
                text=empty,
                font=FONT_PATH,
                bg=BG,
                fg=MUTED,
            ).pack(pady=16)
            return

        if fav_projects:
            self._favs_container = tk.Frame(self._buttons_frame, bg=BG)
            self._favs_container.pack(fill="x")
            register_testid(self._favs_container, "fp-forge-pick-favorites")
            for project in fav_projects:
                self._make_row(self._favs_container, project, is_fav=True)

        if fav_projects and other_projects:
            tk.Frame(self._buttons_frame, bg=SURFACE, height=1).pack(
                fill="x", pady=(6, 8)
            )

        for project in other_projects:
            self._make_row(self._buttons_frame, project, is_fav=False)

        self._on_frame_configure()

    def _make_row(self, parent: tk.Frame, project: tuple, is_fav: bool) -> None:
        (
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
        ) = project
        slug = testid_slug(name)

        outer = tk.Frame(parent, bg=BG, highlightthickness=0)
        outer.pack(fill="x", pady=(0, 4))
        register_testid(outer, f"fp-project-row-{slug}")
        outer._fav_name = name  # type: ignore[attr-defined]

        # ── Linha 1: drag handle (favoritos) + fav dot + nome ──
        top = tk.Frame(outer, bg=BG)
        top.pack(fill="x")

        if is_fav:
            handle = tk.Label(
                top,
                text="⠿",
                font=("Ubuntu", 11),
                bg=BG,
                fg=MUTED,
                cursor="sb_v_double_arrow",
            )
            handle.pack(side="left", padx=(0, 4))
            register_testid(handle, f"fp-project-row-{slug}-drag-handle")
            outer._drag_handle = handle  # type: ignore[attr-defined]
            self._fav_rows.append(outer)
            self._bind_fav_drag(outer, handle)

        fav_dot = FavDot(top, name, on_toggle=self._load_buttons)
        fav_dot.pack(side="left", padx=(0, 6), anchor="center")
        register_testid(fav_dot, f"fp-project-row-{slug}-favorite-toggle")

        name_label = tk.Label(
            top,
            text=commercial,
            font=FONT_BTN,
            bg=BG,
            fg=FG,
            anchor="w",
        )
        name_label.pack(side="left", fill="x", expand=True)
        if is_fav:
            name_label.configure(cursor="sb_v_double_arrow")
            self._bind_fav_drag(outer, name_label)

        # ── Linha 2: atalhos que abrem terminal, editor ou pastas ──
        open_btns = tk.Frame(outer, bg=BG)
        open_btns.pack(fill="x", pady=(2, 0))
        register_testid(open_btns, f"fp-project-row-{slug}-open-actions")

        _BTN_PADY = 5
        _BTN_PADX = 8

        ws_dir = _resolve_workspace_dir(workspace)
        ws_disabled = ws_dir is None
        term_btn = RoundedButton(
            open_btns,
            text="Terminal",
            font=FONT_WS,
            bg=SURFACE if not ws_disabled else BG,
            fg=ACCENT if not ws_disabled else MUTED,
            hover_bg=HOVER if not ws_disabled else BG,
            padx=_BTN_PADX,
            pady=_BTN_PADY,
            anchor="center",
            disabled=ws_disabled,
        )
        term_btn.pack(side="left", padx=(0, 4))
        register_testid(term_btn, f"fp-project-row-{slug}-terminal-button")
        if not ws_disabled:
            term_btn.set_command(
                lambda b=term_btn, d=ws_dir: self._open_terminal(b, d)
            )

        vscode_btn = RoundedButton(
            open_btns,
            text="Vs code",
            font=FONT_WS,
            bg=SURFACE if not ws_disabled else BG,
            fg=ACCENT if not ws_disabled else MUTED,
            hover_bg=HOVER if not ws_disabled else BG,
            padx=_BTN_PADX,
            pady=_BTN_PADY,
            anchor="center",
            disabled=ws_disabled,
        )
        vscode_btn.pack(side="left", padx=(0, 4))
        register_testid(vscode_btn, f"fp-project-row-{slug}-vscode-button")
        if not ws_disabled:
            vscode_btn.set_command(
                lambda b=vscode_btn, d=ws_dir: self._on_open_vscode(b, d)
            )

        folder_btn = RoundedButton(
            open_btns,
            text="📁",
            font=FONT_WS,
            bg=SURFACE if not ws_disabled else BG,
            fg=YELLOW if not ws_disabled else MUTED,
            hover_bg=HOVER if not ws_disabled else BG,
            padx=_BTN_PADX,
            pady=_BTN_PADY,
            anchor="center",
            disabled=ws_disabled,
        )
        folder_btn.pack(side="left", padx=(0, 4))
        register_testid(folder_btn, f"fp-project-row-{slug}-folder-button")
        if not ws_disabled:
            folder_btn.set_command(
                lambda b=folder_btn, d=ws_dir: self._on_open_folder(
                    b, d, "📁", YELLOW
                )
            )

        public_dir = ws_dir / "public" if ws_dir is not None else None
        public_disabled = public_dir is None or not public_dir.is_dir()
        public_btn = RoundedButton(
            open_btns,
            text="public/",
            font=FONT_WS,
            bg=SURFACE if not public_disabled else BG,
            fg=CYAN if not public_disabled else MUTED,
            hover_bg=HOVER if not public_disabled else BG,
            padx=_BTN_PADX,
            pady=_BTN_PADY,
            anchor="center",
            disabled=public_disabled,
        )
        public_btn.pack(side="left", padx=(0, 4))
        register_testid(public_btn, f"fp-project-row-{slug}-public-button")
        if not public_disabled:
            public_btn.set_command(
                lambda b=public_btn, d=public_dir: self._on_open_folder(
                    b, d, "public/", CYAN
                )
            )

        env_file = ws_dir / ".env" if ws_dir is not None else None
        env_disabled = env_file is None or not env_file.is_file()
        env_btn = RoundedButton(
            open_btns,
            text=".env",
            font=FONT_WS,
            bg=SURFACE if not env_disabled else BG,
            fg=FG if not env_disabled else MUTED,
            hover_bg=HOVER if not env_disabled else BG,
            padx=_BTN_PADX,
            pady=_BTN_PADY,
            anchor="center",
            disabled=env_disabled,
        )
        env_btn.pack(side="left", padx=(0, 4))
        register_testid(env_btn, f"fp-project-row-{slug}-env-button")
        if not env_disabled:
            env_btn.set_command(
                lambda b=env_btn, f=env_file: self._on_open_vscode(b, f, ".env", FG)
            )

        # ── Linha 3: valores enviados ao terminal via xdotool ──
        value_btns = tk.Frame(outer, bg=BG)
        value_btns.pack(fill="x", pady=(2, 0))
        register_testid(value_btns, f"fp-project-row-{slug}-value-actions")

        for text, value, fg_color in [
            ("JSON",  path,       YELLOW),
            ("WS",    workspace,  GREEN),
            ("wbs",   wbs_root,   VIOLET),
            ("brief", brief_root, CYAN),
            ("docs",  docs_root,  ORANGE),
            ("github", github,    ACCENT),
            (".env.production", env_production_content, FG),
        ]:
            disabled = not bool(value)
            btn = RoundedButton(
                value_btns,
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
            register_testid(btn, f"fp-project-row-{slug}-{testid_slug(text)}-button")
            if not disabled:
                btn.set_command(
                    lambda b=btn, v=value, t=text, f=fg_color: self._click(b, t, v, SURFACE, f)
                )

        tk.Frame(outer, bg=SURFACE, height=1).pack(fill="x", pady=(4, 0))

    def _bind_fav_drag(self, row: tk.Frame, source: tk.Widget) -> None:
        source.bind("<ButtonPress-1>", lambda e, r=row: self._on_fav_press(e, r))

    def _on_fav_press(self, event, row: tk.Frame) -> None:
        if self._drag is not None:
            return
        self._drag = {
            "row": row,
            "start_y": event.y_root,
            "active": False,
        }
        self.bind_all("<B1-Motion>", self._on_fav_motion, add="+")
        self.bind_all("<ButtonRelease-1>", self._on_fav_release, add="+")

    def _clear_fav_drag(self) -> None:
        try:
            self.unbind_all("<B1-Motion>")
            self.unbind_all("<ButtonRelease-1>")
        except tk.TclError:
            pass
        self._drag = None

    def _on_fav_motion(self, event) -> None:
        drag = self._drag
        if drag is None:
            return
        row = drag["row"]
        if not drag["active"]:
            if abs(event.y_root - drag["start_y"]) <= 5:
                return
            drag["active"] = True
            row.configure(
                highlightbackground=ACCENT,
                highlightcolor=ACCENT,
                highlightthickness=1,
            )
            handle = getattr(row, "_drag_handle", None)
            if handle is not None:
                handle.configure(fg=ACCENT)
        self._place_dragged_row(event.y_root, row)

    def _on_fav_release(self, event) -> None:
        drag = self._drag
        if drag is None:
            return
        row = drag["row"]
        active = bool(drag.get("active"))
        self._clear_fav_drag()
        row.configure(highlightthickness=0)
        handle = getattr(row, "_drag_handle", None)
        if handle is not None:
            handle.configure(fg=MUTED)
        if not active:
            return
        self._place_dragged_row(event.y_root, row)
        order = [r._fav_name for r in self._fav_rows]
        self._persist_fav_order(order)

    def _place_dragged_row(self, y_root: int, row: tk.Frame) -> None:
        if self._favs_container is None:
            return
        rows = self._fav_rows
        if row not in rows or len(rows) < 2:
            return

        insert_idx = len(rows)
        for i, candidate in enumerate(rows):
            if candidate is row:
                continue
            mid = candidate.winfo_rooty() + candidate.winfo_height() // 2
            if y_root < mid:
                insert_idx = i
                break

        old = rows.index(row)
        target = insert_idx - 1 if old < insert_idx else insert_idx
        if target == old:
            return

        rows.pop(old)
        rows.insert(target, row)
        for item in rows:
            item.pack_forget()
        for item in rows:
            item.pack(fill="x", pady=(0, 4))

    def _toggle_show_all(self) -> None:
        self._show_all = not self._show_all
        save_show_all(self._show_all)
        self._eye_btn.set_selected(self._show_all)
        self._load_buttons()

    def _persist_fav_order(self, visible_order: list[str]) -> None:
        all_favs = load_favorites_ordered()
        visible_set = set(visible_order)
        hidden = [name for name in all_favs if name not in visible_set]
        save_favorites(visible_order + hidden)

    def _open_terminal(self, btn: RoundedButton, cwd: Path) -> None:
        if _open_linux_terminal(cwd):
            return
        btn.configure_state("erro", ACCENT, BG)
        self.after(
            1500,
            lambda: btn.configure_state("Terminal", SURFACE, ACCENT),
        )

    def _on_open_folder(
        self,
        btn: RoundedButton,
        path: Path,
        original_text: str,
        original_fg: str,
    ) -> None:
        if _open_in_file_manager(path):
            return
        btn.configure_state("erro", ACCENT, BG)
        self.after(
            1500,
            lambda: btn.configure_state(original_text, SURFACE, original_fg),
        )

    def _on_open_vscode(
        self,
        btn: RoundedButton,
        target: Path,
        original_text: str = "Vs code",
        original_fg: str = ACCENT,
    ) -> None:
        if _open_vscode(target):
            return
        btn.configure_state("erro", ACCENT, BG)
        self.after(
            1500,
            lambda: btn.configure_state(original_text, SURFACE, original_fg),
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


def _redirect_crash_log() -> None:
    """Quando nao ha TTY (lancador GNOME), persiste stdout/stderr em arquivo."""
    try:
        if sys.stderr is not None and sys.stderr.isatty():
            return
    except Exception:  # noqa: BLE001
        pass
    log_dir = Path.home() / ".local" / "share" / "forge-pick"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_f = (log_dir / "last-run.log").open("a", encoding="utf-8")
    except OSError:
        return
    sys.stderr = log_f
    sys.stdout = log_f


if __name__ == "__main__":
    _redirect_crash_log()
    try:
        from desktop_entry import ensure_desktop_integration

        ensure_desktop_integration()
    except Exception as exc:  # noqa: BLE001
        print(f"[desktop-entry] Falha nao critica: {exc}", file=sys.stderr)
    ForgePick().mainloop()
