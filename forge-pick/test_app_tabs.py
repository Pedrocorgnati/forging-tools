"""Testes das abas Forge Pick / Timers (Task 007 — navbar e corpo de abas)."""

from __future__ import annotations

import types

import tkinter as tk

import pytest

import datatest_overlay as dto


def _projeto(name: str, workspace: str) -> tuple:
    """Fabrica de projeto no formato de 10 campos de load_projects."""
    return (
        name,
        name.title(),
        f".claude/projects/{name}.json",
        workspace,
        "wbs",
        "",
        "docs",
        "",
        "",
        "",
    )


def _widgets_por_testid() -> dict:
    return {testid: widget for testid, widget in dto.registered_widgets()}


@pytest.fixture
def app_instance(monkeypatch, tmp_path):
    import app

    projetos = [_projeto("Projeto Alfa", "/tmp"), _projeto("beta_proj", "")]
    monkeypatch.setattr(app.timers_store, "boot_timers_store", lambda: (None, None))
    monkeypatch.setattr(app, "load_projects", lambda: list(projetos))
    monkeypatch.setattr(app, "load_favorites_ordered", lambda: ["Projeto Alfa"])
    monkeypatch.setattr(app, "load_show_all", lambda: True)
    monkeypatch.setattr(app.ForgePick, "_set_net_wm_pid", lambda self: None)
    monkeypatch.setattr(app.ForgePick, "_install_window_icon", lambda self: None)
    monkeypatch.setattr(app, "SETTINGS_FILE", tmp_path / "settings.json")

    try:
        instance = app.ForgePick()
    except tk.TclError as exc:
        pytest.skip(f"Tk indisponivel: {exc}")
    try:
        instance.withdraw()
        instance.update_idletasks()
        yield instance
    finally:
        try:
            instance.destroy()
        except tk.TclError:
            pass
        dto._reset_registry()


def test_aba_boot_abre_em_forge_pick(app_instance) -> None:
    import app

    widgets = _widgets_por_testid()
    assert app_instance.active_tab == app.TAB_FORGE_PICK
    assert widgets["fp-tab-forge-pick"].winfo_manager() == "pack"
    assert widgets["fp-tab-timers"].winfo_manager() == ""


def test_aba_switch_timers_mostra_frame_vazio(app_instance) -> None:
    import app

    widgets = _widgets_por_testid()
    app_instance.switch_tab(app.TAB_TIMERS)
    assert app_instance.active_tab == app.TAB_TIMERS
    assert widgets["fp-tab-timers"].winfo_manager() == "pack"
    assert widgets["fp-tab-forge-pick"].winfo_manager() == ""
    assert widgets["fp-tab-timers"].winfo_children() == [app_instance._timers_view.frame]


def test_aba_ida_e_volta_restaura_forge_pick(app_instance) -> None:
    import app

    app_instance.switch_tab(app.TAB_TIMERS)
    app_instance.switch_tab(app.TAB_FORGE_PICK)
    assert app_instance.active_tab == app.TAB_FORGE_PICK
    vivos = dto.live_testids()
    assert "fp-forge-pick-list" in vivos
    assert "fp-project-row-projeto-alfa" in vivos


def test_aba_indicacao_do_selecionado(app_instance) -> None:
    import app

    botoes = app_instance._tab_buttons
    assert botoes[app.TAB_FORGE_PICK]._bg == app.ACCENT
    assert botoes[app.TAB_TIMERS]._bg == app.SURFACE
    app_instance.switch_tab(app.TAB_TIMERS)
    assert botoes[app.TAB_FORGE_PICK]._bg == app.SURFACE
    assert botoes[app.TAB_TIMERS]._bg == app.ACCENT


def test_aba_clique_no_botao_troca_aba(app_instance) -> None:
    import app

    widgets = _widgets_por_testid()
    # clique deterministico: janela withdrawn nao dispara event_generate
    widgets["fp-navbar-tab-timers"]._on_release(None)
    assert app_instance.active_tab == app.TAB_TIMERS
    widgets["fp-navbar-tab-forge-pick"]._on_release(None)
    assert app_instance.active_tab == app.TAB_FORGE_PICK


def test_aba_callback_por_aba_recebe_previous(app_instance) -> None:
    import app

    chamadas_timers = []
    chamadas_forge = []
    app_instance.add_tab_callback("timers", lambda previous: chamadas_timers.append(previous))
    app_instance.add_tab_callback("forge_pick", lambda previous: chamadas_forge.append(previous))

    app_instance.switch_tab(app.TAB_TIMERS)
    assert chamadas_timers == ["forge_pick"]
    assert chamadas_forge == []

    app_instance.switch_tab(app.TAB_TIMERS)  # no-op: mesma aba
    assert chamadas_timers == ["forge_pick"]

    app_instance.switch_tab(app.TAB_FORGE_PICK)
    assert chamadas_forge == ["timers"]
    assert chamadas_timers == ["forge_pick"]


def test_aba_callback_com_excecao_nao_interrompe(app_instance, capsys) -> None:
    chamadas = []

    def quebra(_previous) -> None:
        raise RuntimeError("falha proposital")

    def registra(previous) -> None:
        chamadas.append(previous)

    app_instance.add_tab_callback("timers", quebra)
    app_instance.add_tab_callback("timers", registra)
    app_instance.switch_tab("timers")
    assert chamadas == ["forge_pick"]
    err = capsys.readouterr().err
    assert "[forge-pick] callback da aba timers falhou: falha proposital" in err


def test_aba_switch_e_callback_validam_aba(app_instance) -> None:
    import app

    with pytest.raises(ValueError) as excinfo_switch:
        app_instance.switch_tab("xyz")
    assert "xyz" in str(excinfo_switch.value)
    with pytest.raises(ValueError) as excinfo_callback:
        app_instance.add_tab_callback("xyz", lambda previous: None)
    assert "xyz" in str(excinfo_callback.value)
    with pytest.raises(TypeError):
        app_instance.add_tab_callback("timers", 123)
    assert app_instance.active_tab == app.TAB_FORGE_PICK


def test_aba_nao_persiste_selecao(app_instance) -> None:
    import app

    app_instance.switch_tab(app.TAB_TIMERS)
    assert not app.SETTINGS_FILE.exists()
    try:
        app_instance.destroy()
    except tk.TclError:
        pass
    dto._reset_registry()

    try:
        segunda = app.ForgePick()
    except tk.TclError as exc:
        pytest.skip(f"Tk indisponivel: {exc}")
    try:
        segunda.withdraw()
        segunda.update_idletasks()
        assert segunda.active_tab == app.TAB_FORGE_PICK
        assert not app.SETTINGS_FILE.exists()
    finally:
        try:
            segunda.destroy()
        except tk.TclError:
            pass


def test_aba_scroll_ignorado_na_aba_timers(app_instance, monkeypatch) -> None:
    import app

    chamadas: list = []

    def gravador(*args) -> None:
        chamadas.append(args)

    monkeypatch.setattr(app_instance._canvas, "yview_scroll", gravador)
    evento = types.SimpleNamespace(num=5, delta=0)

    app_instance.switch_tab(app.TAB_TIMERS)
    app_instance._on_mousewheel(evento)
    assert chamadas == []

    app_instance.switch_tab(app.TAB_FORGE_PICK)
    app_instance._on_mousewheel(evento)
    assert chamadas == [(1, "units")]


def test_aba_testids_da_navbar_vivos(app_instance) -> None:
    vivos = set(dto.live_testids())
    esperados = {
        "fp-navbar",
        "fp-navbar-tab-forge-pick",
        "fp-navbar-tab-timers",
        "fp-tab-forge-pick",
        "fp-tab-timers",
    }
    assert esperados <= vivos, sorted(esperados - vivos)


def test_card_separa_atalhos_de_abertura_dos_valores(app_instance) -> None:
    widgets = _widgets_por_testid()
    prefix = "fp-project-row-projeto-alfa"
    open_actions = widgets[f"{prefix}-open-actions"]
    value_actions = widgets[f"{prefix}-value-actions"]

    open_ids = [dto.testid_of(widget) for widget in open_actions.pack_slaves()]
    assert open_ids == [
        f"{prefix}-terminal-button",
        f"{prefix}-vscode-button",
        f"{prefix}-folder-button",
        f"{prefix}-public-button",
        f"{prefix}-env-button",
    ]

    value_ids = [dto.testid_of(widget) for widget in value_actions.pack_slaves()]
    assert value_ids == [
        f"{prefix}-json-button",
        f"{prefix}-ws-button",
        f"{prefix}-wbs-button",
        f"{prefix}-brief-button",
        f"{prefix}-docs-button",
        f"{prefix}-github-button",
        f"{prefix}-env-production-button",
    ]
    assert widgets[f"{prefix}-folder-button"]._text == "📁"
    assert widgets[f"{prefix}-public-button"]._text == "public/"
    assert widgets[f"{prefix}-env-button"]._text == ".env"


def test_open_in_file_manager_usa_xdg_open(monkeypatch, tmp_path) -> None:
    import app

    calls = []
    monkeypatch.setattr(
        app.shutil,
        "which",
        lambda binary: f"/usr/bin/{binary}" if binary == "xdg-open" else None,
    )
    monkeypatch.setattr(
        app.subprocess,
        "Popen",
        lambda args, **kwargs: calls.append((args, kwargs)),
    )

    assert app._open_in_file_manager(tmp_path) is True
    assert calls[0][0] == ["xdg-open", str(tmp_path)]
    assert calls[0][1]["cwd"] == str(tmp_path)


def test_open_vscode_arquivo_usa_workspace_como_cwd(monkeypatch, tmp_path) -> None:
    import app

    env_file = tmp_path / ".env"
    env_file.write_text("KEY=value\n", encoding="utf-8")
    calls = []
    monkeypatch.setattr(
        app.shutil,
        "which",
        lambda binary: f"/usr/bin/{binary}" if binary == "code" else None,
    )
    monkeypatch.setattr(
        app.subprocess,
        "Popen",
        lambda args, **kwargs: calls.append((args, kwargs)),
    )

    assert app._open_vscode(env_file) is True
    assert calls[0][0] == ["code", str(env_file)]
    assert calls[0][1]["cwd"] == str(tmp_path)


# ── header condicional por aba (Task 008 — D9) ──────────────────────────────


def test_header_boot_mostra_controles_forge_pick(app_instance) -> None:
    widgets = _widgets_por_testid()
    assert widgets["fp-header-refresh-button"].winfo_manager() == "pack"
    assert widgets["fp-header-show-all-toggle"].winfo_manager() == "pack"
    assert widgets["fp-header-search"].winfo_manager() == "pack"
    assert widgets["fp-clock-add-button"].winfo_manager() == ""


def test_header_timers_mostra_so_botao_adicionar(app_instance) -> None:
    import app

    widgets = _widgets_por_testid()
    app_instance.switch_tab(app.TAB_TIMERS)
    assert widgets["fp-header-refresh-button"].winfo_manager() == ""
    assert widgets["fp-header-show-all-toggle"].winfo_manager() == ""
    assert widgets["fp-header-search"].winfo_manager() == ""
    botao = widgets["fp-clock-add-button"]
    assert botao.winfo_manager() == "pack"
    # mesmo lugar: o botao mora no mesmo fp-header do "⟳" (D2)
    assert botao.winfo_parent() == widgets["fp-header-refresh-button"].winfo_parent()
    assert botao.pack_info()["side"] == "right"


def test_header_volta_restaura_ordem_e_pack(app_instance) -> None:
    import app

    widgets = _widgets_por_testid()
    header = widgets["fp-header"]
    controles = (
        "fp-header-refresh-button",
        "fp-header-show-all-toggle",
        "fp-header-search",
    )

    def estado() -> tuple:
        packs = {
            testid: {
                chave: widgets[testid].pack_info().get(chave)
                for chave in ("side", "padx", "pady")
            }
            for testid in controles
        }
        return (header.pack_slaves(), packs)

    boot = estado()
    app_instance.switch_tab(app.TAB_TIMERS)
    app_instance.switch_tab(app.TAB_FORGE_PICK)
    assert estado() == boot


def test_header_clique_adicionar_abre_modal(app_instance, monkeypatch, tmp_path) -> None:
    import app
    import timers_store
    import timers_ui

    chamadas = []

    def gravador(*args, **kwargs) -> None:
        chamadas.append((args, kwargs))

    monkeypatch.setattr(timers_ui.messagebox, "showinfo", gravador)
    monkeypatch.setattr(timers_ui.messagebox, "showerror", gravador)
    app_instance._timers_view.store = timers_store.TimersStore(tmp_path / "timers.db")
    app_instance.switch_tab(app.TAB_TIMERS)
    app_instance._clock_add_btn._on_release(None)
    assert chamadas == []
    dialogo = app_instance._timers_view._dialog
    assert dialogo is not None and dialogo.winfo_exists()
    assert dto.testid_of(dialogo) == "fp-clock-timer-dialog"
    dialogo.cancel()


def test_header_botao_adicionar_tem_ponto_unico(app_instance) -> None:
    assert app_instance._clock_add_btn._command == app_instance._on_clock_add_click


def test_header_apply_idempotente(app_instance) -> None:
    import app

    widgets = _widgets_por_testid()
    header = widgets["fp-header"]

    app_instance._apply_header_for_tab(app.TAB_TIMERS)
    app_instance._apply_header_for_tab(app.TAB_TIMERS)
    assert header.pack_slaves().count(widgets["fp-clock-add-button"]) == 1

    app_instance._apply_header_for_tab(app.TAB_FORGE_PICK)
    app_instance._apply_header_for_tab(app.TAB_FORGE_PICK)
    for testid in (
        "fp-header-refresh-button",
        "fp-header-show-all-toggle",
        "fp-header-search",
    ):
        assert header.pack_slaves().count(widgets[testid]) == 1

    with pytest.raises(ValueError) as excinfo:
        app_instance._apply_header_for_tab("xyz")
    assert "xyz" in str(excinfo.value)


def test_header_busca_preservada_entre_abas(app_instance) -> None:
    import app

    app_instance._search_var.set("alfa")
    app_instance.switch_tab(app.TAB_TIMERS)
    app_instance.switch_tab(app.TAB_FORGE_PICK)
    assert app_instance._search_var.get() == "alfa"


def test_header_testid_adicionar_vivo(app_instance) -> None:
    assert "fp-clock-add-button" in dto.live_testids()


# -- largura da janela por aba (Task 009, D8) ---------------------------------


@pytest.fixture
def geometry_calls(monkeypatch):
    import app

    calls: list = []

    def spy(self, new_geometry=None):
        calls.append(new_geometry)
        return tk.Tk.wm_geometry(self, new_geometry)

    monkeypatch.setattr(app.ForgePick, "geometry", spy)
    return calls


def _tamanho_geometry(geometry: str) -> tuple[int, int]:
    """Extrai (largura, altura) de uma string de geometria, sem a posicao."""
    largura, resto = geometry.split("x", 1)
    altura = resto.split("+")[0].split("-")[0]
    return int(largura), int(altura)


def test_janela_boot_constantes_e_minsize(app_instance) -> None:
    import app

    assert app.BOOT_GEOMETRY == "628x520"
    assert app.BOOT_MINSIZE == (573, 200)
    assert app.TIMERS_MIN_WIDTH == 900
    assert app_instance.wm_minsize() == (573, 200)
    assert app_instance._geometry_before_timers is None


def test_janela_boot_chama_geometry_628x520(geometry_calls, app_instance) -> None:
    calls = geometry_calls
    assert [c for c in calls if c is not None] == ["628x520"]


def test_janela_timers_alarga_e_guarda(app_instance) -> None:
    import app

    app_instance.geometry("700x600+5+5")
    app_instance.deiconify()
    app_instance.update()
    app_instance.switch_tab(app.TAB_TIMERS)
    app_instance.update()

    assert app_instance._geometry_before_timers == "700x600+5+5"
    largura, altura = _tamanho_geometry(app_instance.geometry())
    assert largura >= 900
    assert altura == 600
    assert app_instance.geometry().endswith("+5+5")
    assert app_instance.wm_minsize() == (900, 200)


def test_janela_volta_restaura_geometria_e_minsize(app_instance) -> None:
    import app

    app_instance.geometry("700x600+5+5")
    app_instance.deiconify()
    app_instance.update()
    app_instance.switch_tab(app.TAB_TIMERS)
    app_instance.update()
    app_instance.switch_tab(app.TAB_FORGE_PICK)
    app_instance.update()

    assert app_instance.geometry() == "700x600+5+5"
    assert app_instance.wm_minsize() == (573, 200)
    assert app_instance._geometry_before_timers is None


def test_janela_ja_larga_nao_encolhe(app_instance) -> None:
    import app

    app_instance.geometry("1000x500+0+0")
    app_instance.deiconify()
    app_instance.update()
    app_instance.switch_tab(app.TAB_TIMERS)
    app_instance.update()

    largura, altura = _tamanho_geometry(app_instance.geometry())
    assert largura == 1000
    assert altura == 500


def test_janela_resize_em_timers_descartado_na_volta(app_instance) -> None:
    import app

    app_instance.geometry("700x600+5+5")
    app_instance.deiconify()
    app_instance.update()
    app_instance.switch_tab(app.TAB_TIMERS)
    app_instance.update()
    app_instance.geometry("1200x700")
    app_instance.update()
    app_instance.switch_tab(app.TAB_FORGE_PICK)
    app_instance.update()

    assert app_instance.geometry() == "700x600+5+5"


def test_janela_ida_e_volta_repetida_idempotente(app_instance) -> None:
    import app

    app_instance.geometry("700x600+5+5")
    app_instance.deiconify()
    app_instance.update()

    resultados = []
    for _ciclo in range(2):
        app_instance.switch_tab(app.TAB_TIMERS)
        app_instance.update()
        largura, altura = _tamanho_geometry(app_instance.geometry())
        app_instance.switch_tab(app.TAB_FORGE_PICK)
        app_instance.update()
        resultados.append((largura, altura, app_instance.geometry()))

    assert resultados[0] == resultados[1]
    largura, altura, geom_volta = resultados[0]
    assert largura >= 900
    assert altura == 600
    assert geom_volta == "700x600+5+5"


def test_widen_geometry_pura() -> None:
    import app

    assert app.widen_geometry("628x520+10+20", 900, 200) == "900x520"
    assert app.widen_geometry("1000x150", 900, 200) == "1000x200"
    assert app.widen_geometry("1x1+0+0", 900, 200) == "900x200"
    assert app.widen_geometry("700x600-5-5", 900, 200) == "900x600"
    with pytest.raises(ValueError) as excinfo:
        app.widen_geometry("abc", 900, 200)
    assert "abc" in str(excinfo.value)


# -- TimersView na aba Timers (Task 010, D9/D11) -----------------------------


def test_timers_view_monta_tres_sections_no_boot(app_instance) -> None:
    assert app_instance._timers_view is not None
    vivos = set(dto.live_testids())
    assert {"fp-daily-section", "fp-weekly-section", "fp-monthly-section"} <= vivos


def test_timers_view_boot_falho_mostra_erro_nas_colunas(app_instance) -> None:
    widgets = _widgets_por_testid()
    for freq in ("daily", "weekly", "monthly"):
        assert "banco de timers indisponivel" in widgets[f"fp-{freq}-error"].cget("text")


def test_aba_timers_mousewheel_delega_para_timers_view(app_instance, monkeypatch) -> None:
    import app

    chamadas_view: list = []
    chamadas_canvas: list = []
    monkeypatch.setattr(
        app_instance._timers_view,
        "on_mousewheel",
        lambda event: chamadas_view.append(event),
    )
    monkeypatch.setattr(
        app_instance._canvas, "yview_scroll", lambda *args: chamadas_canvas.append(args)
    )
    evento = types.SimpleNamespace(num=5, delta=0)

    app_instance.switch_tab(app.TAB_TIMERS)
    app_instance._on_mousewheel(evento)
    assert chamadas_view == [evento]
    assert chamadas_canvas == []


# ── botao DataTest (item 013) ────────────────────────────────────────────────


def test_datatest_botao_no_header_visivel_nas_duas_abas(app_instance) -> None:
    import app

    widgets = _widgets_por_testid()
    botao = widgets["fp-datatest-toggle-button"]
    header = widgets["fp-header"]
    assert botao.master is header
    assert botao.pack_info()["side"] == "right"
    por_aba = {
        app.TAB_FORGE_PICK: [
            widgets["fp-header-refresh-button"],
            widgets["fp-header-show-all-toggle"],
            widgets["fp-header-search"],
        ],
        app.TAB_TIMERS: [widgets["fp-clock-add-button"]],
    }
    for tab in (app.TAB_TIMERS, app.TAB_FORGE_PICK, app.TAB_TIMERS):
        app_instance.switch_tab(tab)
        slaves = header.pack_slaves()
        assert botao in slaves
        assert botao.winfo_manager() == "pack"
        for outro in por_aba[tab]:
            assert slaves.index(botao) < slaves.index(outro)


def test_datatest_clique_abre_e_segundo_clique_fecha(app_instance) -> None:
    ctrl = app_instance._datatest
    assert ctrl.is_panel_open is False
    app_instance._datatest_btn._on_release(None)
    assert ctrl.is_panel_open is True
    app_instance._datatest_btn._on_release(None)
    assert ctrl.is_panel_open is False


def test_datatest_modo_body_reflete_troca_de_aba(app_instance) -> None:
    import app

    app_instance.deiconify()
    app_instance.update()
    ctrl = app_instance._datatest
    ctrl.set_mode(dto.MODE_BODY)
    ids = [t for t, _l in ctrl.overlay_labels()]
    assert "fp-header-search-input" in ids
    app_instance.switch_tab(app.TAB_TIMERS)
    app_instance.update()
    ctrl.refresh()
    ids = [t for t, _l in ctrl.overlay_labels()]
    assert "fp-header-search-input" not in ids
    assert "fp-daily-section" in ids


def test_datatest_sem_atalho_sem_bind_all_sem_terminal() -> None:
    import ast
    from pathlib import Path

    base = Path(__file__).resolve().parent
    proibidas = ("<Control", "<Key", "<Alt", "<Shift")

    def _varre(nome: str, estrito: bool) -> None:
        arvore = ast.parse((base / nome).read_text(encoding="utf-8"))
        for no in ast.walk(arvore):
            if isinstance(no, ast.Constant) and isinstance(no.value, str):
                if estrito:
                    assert not any(p in no.value for p in proibidas), (nome, no.value)
                else:
                    assert "<Control" not in no.value, (nome, no.value)
            if estrito and isinstance(no, ast.Call) and isinstance(no.func, ast.Attribute):
                assert no.func.attr not in {"bind_all", "bind_class"}, nome
            if estrito and isinstance(no, ast.Import):
                assert not {a.name for a in no.names} & {"subprocess", "os"}, nome
            if estrito and isinstance(no, ast.ImportFrom):
                assert no.module not in {"subprocess", "os"}, nome

    _varre("datatest_overlay.py", estrito=True)
    _varre("app.py", estrito=False)
