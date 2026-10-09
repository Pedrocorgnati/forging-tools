"""Unit tests for the Forge Pick testid registry (datatest_overlay)."""

from __future__ import annotations

import ast
import tkinter as tk
from pathlib import Path

import pytest

import datatest_overlay as dto

APP_PATH = Path(__file__).resolve().parent / "app.py"


@pytest.fixture
def tk_root():
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk indisponivel: {exc}")
    root.withdraw()
    try:
        yield root
    finally:
        try:
            root.destroy()
        except tk.TclError:
            pass
        dto._reset_registry()


def test_registro_devolve_widget_e_lista_testid(tk_root) -> None:
    frame = tk.Frame(tk_root)
    assert dto.register_testid(frame, "fp-clock-add-button") is frame
    assert dto.live_testids() == ["fp-clock-add-button"]


@pytest.mark.parametrize(
    "invalido",
    [None, 123, "", "clock-add-button", "fp-", "FP-x", "fp-Upper", "fp-a b", "fp--x", "fp-x-"],
)
def test_registro_rejeita_testid_invalido(tk_root, invalido) -> None:
    frame = tk.Frame(tk_root)
    with pytest.raises(ValueError) as excinfo:
        dto.register_testid(frame, invalido)
    assert repr(invalido) in str(excinfo.value)
    assert dto.live_testids() == []


def test_registro_rejeita_widget_destruido(tk_root) -> None:
    frame = tk.Frame(tk_root)
    frame.destroy()
    with pytest.raises(ValueError):
        dto.register_testid(frame, "fp-morto")


def test_destroy_remove_entrada_do_widget(tk_root) -> None:
    frame = tk.Frame(tk_root)
    dto.register_testid(frame, "fp-alvo")
    frame.destroy()
    assert dto.live_testids() == []
    assert dto._REGISTRY == {}


def test_destroy_do_pai_remove_entradas_dos_filhos(tk_root) -> None:
    parent = tk.Frame(tk_root)
    child_a = tk.Button(parent)
    child_b = tk.Entry(parent)
    dto.register_testid(parent, "fp-pai")
    dto.register_testid(child_a, "fp-filho-a")
    dto.register_testid(child_b, "fp-filho-b")
    parent.destroy()
    assert dto.live_testids() == []
    assert dto._REGISTRY == {}


def test_reregistro_troca_testid_sem_duplicar(tk_root) -> None:
    frame = tk.Frame(tk_root)
    dto.register_testid(frame, "fp-antigo")
    dto.register_testid(frame, "fp-novo")
    assert dto.live_testids() == ["fp-novo"]
    assert len(dto._REGISTRY) == 1
    binds = frame.bind("<Destroy>")
    frame.destroy()
    assert dto._REGISTRY == {}
    # um unico handler do modulo instalado no widget (cada bind add='+' vira uma linha "if {...")
    assert binds.count("if {") == 1


def test_bind_destroy_preexistente_continua_disparando(tk_root) -> None:
    frame = tk.Frame(tk_root)
    chamadas: list[str] = []
    frame.bind("<Destroy>", lambda e: chamadas.append(str(e.widget)))
    dto.register_testid(frame, "fp-com-bind")
    path = str(frame)
    frame.destroy()
    assert chamadas == [path]
    assert dto.live_testids() == []


def test_root_registrado_sobrevive_destroy_de_filho(tk_root) -> None:
    dto.register_testid(tk_root, "fp-root")
    child = tk.Frame(tk_root)
    dto.register_testid(child, "fp-filho")
    child.destroy()
    assert dto.live_testids() == ["fp-root"]
    assert dto.testid_of(tk_root) == "fp-root"


def test_registered_widgets_ordenado_e_so_vivos(tk_root) -> None:
    w_c = tk.Frame(tk_root)
    w_a = tk.Frame(tk_root)
    w_b = tk.Frame(tk_root)
    w_morto = tk.Frame(tk_root)
    dto.register_testid(w_c, "fp-c")
    dto.register_testid(w_a, "fp-a")
    dto.register_testid(w_b, "fp-b")
    dto.register_testid(w_morto, "fp-morto")
    w_morto.destroy()
    pares = dto.registered_widgets()
    assert [t for t, _ in pares] == ["fp-a", "fp-b", "fp-c"]
    assert [w for _, w in pares] == [w_a, w_b, w_c]


def test_registered_widgets_mesmo_testid_ordena_por_path(tk_root) -> None:
    w1 = tk.Frame(tk_root)
    w2 = tk.Frame(tk_root)
    dto.register_testid(w2, "fp-igual")
    dto.register_testid(w1, "fp-igual")
    pares = dto.registered_widgets()
    assert [str(w) for _, w in pares] == sorted([str(w1), str(w2)])
    assert dto.live_testids() == ["fp-igual"]


def test_testid_of_registrado_reregistro_ausente_e_destruido(tk_root) -> None:
    frame = tk.Frame(tk_root)
    nunca = tk.Frame(tk_root)
    dto.register_testid(frame, "fp-primeiro")
    assert dto.testid_of(frame) == "fp-primeiro"
    dto.register_testid(frame, "fp-segundo")
    assert dto.testid_of(frame) == "fp-segundo"
    assert dto.testid_of(nunca) is None
    frame.destroy()
    assert dto.testid_of(frame) is None


def test_reset_registry_esvazia_registro(tk_root) -> None:
    dto.register_testid(tk.Frame(tk_root), "fp-um")
    dto.register_testid(tk.Frame(tk_root), "fp-dois")
    assert dto.live_testids() == ["fp-dois", "fp-um"]
    dto._reset_registry()
    assert dto.live_testids() == []
    assert dto.registered_widgets() == []


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("Vs code", "vs-code"),
        (".env.production", "env-production"),
        ("Meu_Projeto 2", "meu-projeto-2"),
        ("---", "sem-nome"),
    ],
)
def test_testid_slug_normaliza_texto(texto, esperado) -> None:
    assert dto.testid_slug(texto) == esperado


def _call_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def test_app_register_testid_usa_literal_fp() -> None:
    tree = ast.parse(APP_PATH.read_text(encoding="utf-8"))
    chamadas = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call) and _call_name(n) == "register_testid"
    ]
    assert len(chamadas) >= 7
    for call in chamadas:
        assert len(call.args) >= 2, f"linha {call.lineno}: register_testid sem testid"
        arg = call.args[1]
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            ok = arg.value.startswith(dto.TESTID_PREFIX)
        elif isinstance(arg, ast.JoinedStr):
            first = arg.values[0] if arg.values else None
            ok = (
                isinstance(first, ast.Constant)
                and isinstance(first.value, str)
                and first.value.startswith(dto.TESTID_PREFIX)
            )
        else:
            ok = False
        assert ok, f"linha {call.lineno}: testid nao comeca com literal 'fp-'"


def test_integracao_aba_forge_pick_registra_e_limpa(monkeypatch) -> None:
    import app

    def _projeto(name: str, workspace: str) -> tuple:
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

    projetos = [_projeto("Projeto Alfa", "/tmp"), _projeto("beta_proj", "")]
    monkeypatch.setattr(app.timers_store, "boot_timers_store", lambda: (None, None))
    monkeypatch.setattr(app, "load_projects", lambda: list(projetos))
    monkeypatch.setattr(app, "load_favorites_ordered", lambda: ["Projeto Alfa"])
    monkeypatch.setattr(app, "load_show_all", lambda: True)
    monkeypatch.setattr(app.ForgePick, "_set_net_wm_pid", lambda self: None)
    monkeypatch.setattr(app.ForgePick, "_install_window_icon", lambda self: None)

    try:
        instance = app.ForgePick()
    except tk.TclError as exc:
        pytest.skip(f"Tk indisponivel: {exc}")
    try:
        instance.withdraw()
        instance.update_idletasks()
        vivos = set(dto.live_testids())
        esperados = {
            "fp-header",
            "fp-header-refresh-button",
            "fp-header-show-all-toggle",
            "fp-header-search",
            "fp-header-search-input",
            "fp-forge-pick-list",
            "fp-forge-pick-favorites",
            "fp-project-row-projeto-alfa",
            "fp-project-row-projeto-alfa-drag-handle",
            "fp-project-row-projeto-alfa-favorite-toggle",
            "fp-project-row-projeto-alfa-terminal-button",
            "fp-project-row-projeto-alfa-vscode-button",
            "fp-project-row-projeto-alfa-folder-button",
            "fp-project-row-projeto-alfa-public-button",
            "fp-project-row-projeto-alfa-env-button",
            "fp-project-row-projeto-alfa-open-actions",
            "fp-project-row-projeto-alfa-value-actions",
            "fp-project-row-projeto-alfa-json-button",
            "fp-project-row-projeto-alfa-env-production-button",
            "fp-project-row-beta-proj",
            "fp-project-row-beta-proj-favorite-toggle",
            "fp-project-row-beta-proj-terminal-button",
            "fp-project-row-beta-proj-ws-button",
        }
        assert esperados <= vivos, sorted(esperados - vivos)
        assert "fp-project-row-beta-proj-drag-handle" not in vivos
        assert all(t.startswith(dto.TESTID_PREFIX) for t in vivos)

        instance._search_var.set("zzz-nenhum-projeto")
        instance.update_idletasks()
        vivos = dto.live_testids()
        assert not [t for t in vivos if t.startswith("fp-project-row-")]
        assert "fp-forge-pick-favorites" not in vivos
        assert "fp-header" in vivos
    finally:
        instance.destroy()
        dto._reset_registry()


# ── painel DataTest (item 013) ───────────────────────────────────────────────


def _visivel(tk_root, testid: str, cls=tk.Frame, **pack):
    widget = cls(tk_root)
    widget.pack(**pack)
    dto.register_testid(widget, testid)
    return widget


def test_painel_is_button_widget_nativos_e_injetados(tk_root) -> None:
    class FakeBtn(tk.Canvas):
        pass

    for cls in (tk.Button, tk.Checkbutton, tk.Radiobutton):
        assert dto.is_button_widget(cls(tk_root), ()) is True
    injetado = FakeBtn(tk_root)
    assert dto.is_button_widget(injetado, ()) is False
    assert dto.is_button_widget(injetado, (FakeBtn,)) is True
    assert dto.is_button_widget(injetado, [FakeBtn]) is True
    assert dto.is_button_widget(tk.Label(tk_root), (FakeBtn,)) is False
    assert dto.is_button_widget(tk.Frame(tk_root), (FakeBtn,)) is False


def test_painel_select_targets_main_so_structurais(tk_root) -> None:
    candidatos = [
        ("fp-header", tk.Frame(tk_root)),
        ("fp-project-row-x", tk.Frame(tk_root)),
        ("fp-daily-section", tk.Frame(tk_root)),
    ]
    alvos = dto.select_targets(dto.MODE_MAIN, candidatos, ())
    assert [t for t, _w in alvos] == ["fp-header", "fp-daily-section"]
    assert all(t in dto.MAIN_TESTIDS for t, _w in alvos)
    assert dto.select_targets(dto.MODE_OFF, candidatos, ()) == []
    with pytest.raises(ValueError) as excinfo:
        dto.select_targets("zzz", candidatos, ())
    assert "zzz" in str(excinfo.value)


def test_painel_body_e_buttons_particionam_candidatos(tk_root) -> None:
    candidatos = [
        ("fp-a-frame", tk.Frame(tk_root)),
        ("fp-b-button", tk.Button(tk_root)),
        ("fp-c-label", tk.Label(tk_root)),
        ("fp-d-check", tk.Checkbutton(tk_root)),
    ]
    body = dto.select_targets(dto.MODE_BODY, candidatos, ())
    botoes = dto.select_targets(dto.MODE_BUTTONS, candidatos, ())
    ids_body = {t for t, _w in body}
    ids_botoes = {t for t, _w in botoes}
    assert ids_body.isdisjoint(ids_botoes)
    assert ids_body | ids_botoes == {t for t, _w in candidatos}
    assert ids_botoes == {"fp-b-button", "fp-d-check"}


def test_painel_overlay_candidates_exclui_escondido_e_outro_toplevel(tk_root) -> None:
    visivel = _visivel(tk_root, "fp-visivel", side="top")
    escondido = tk.Frame(tk_root)
    escondido.pack()
    filho = tk.Frame(escondido)
    filho.pack()
    dto.register_testid(filho, "fp-filho-escondido")
    escondido.pack_forget()
    outro = tk.Toplevel(tk_root)
    interno = tk.Frame(outro)
    interno.pack()
    dto.register_testid(interno, "fp-em-outro-toplevel")

    ids = [t for t, _w in dto.overlay_candidates(tk_root)]
    assert "fp-visivel" in ids
    assert "fp-filho-escondido" not in ids
    assert "fp-em-outro-toplevel" not in ids
    assert visivel in [w for _t, w in dto.overlay_candidates(tk_root)]


def test_painel_toggle_abre_e_fecha_toplevel(tk_root) -> None:
    ctrl = dto.DataTestController(tk_root)
    ctrl.toggle_panel()
    assert ctrl.is_panel_open
    assert isinstance(ctrl.panel, tk.Toplevel)
    assert ctrl.panel.overrideredirect()
    assert "fp-datatest-floating-panel" in dto.live_testids()
    assert ctrl.open_panel() is ctrl.panel
    ctrl.toggle_panel()
    assert not ctrl.is_panel_open
    assert "fp-datatest-floating-panel" not in dto.live_testids()


def test_painel_controles_tem_command_e_testid_fp(tk_root) -> None:
    ctrl = dto.DataTestController(tk_root)
    ctrl.open_panel()
    por_testid = dict((t, w) for t, w in dto.registered_widgets())
    for testid in (
        "fp-datatest-mode-main",
        "fp-datatest-mode-body",
        "fp-datatest-mode-btn",
        "fp-datatest-px-ruler-toggle",
    ):
        assert testid.startswith(dto.TESTID_PREFIX)
        assert str(por_testid[testid].cget("command")) != ""
    assert "fp-datatest-panel-handle" in por_testid
    ctrl.close_panel()


def test_painel_modos_exclusivos_e_clique_repetido_desliga(tk_root) -> None:
    _visivel(tk_root, "fp-um", side="top")
    ctrl = dto.DataTestController(tk_root)
    tk_root.deiconify()
    tk_root.update()
    ctrl.on_mode_click("body")
    assert ctrl.mode == "body"
    ctrl.on_mode_click("buttons")
    assert ctrl.mode == "buttons"
    ctrl.on_mode_click("buttons")
    assert ctrl.mode == "off"
    assert ctrl.overlay_labels() == []
    with pytest.raises(ValueError):
        ctrl.set_mode("inexistente")
    with pytest.raises(ValueError):
        ctrl.on_mode_click("inexistente")


def test_painel_px_ruler_independente_com_larguras_10_50_100(tk_root) -> None:
    ctrl = dto.DataTestController(tk_root)
    tk_root.geometry("400x300")
    tk_root.deiconify()
    tk_root.update()
    assert ctrl.mode == "off"
    ctrl.toggle_px_ruler()
    tk_root.update()
    reguas = ctrl.ruler_labels()
    assert [r.winfo_width() for r in reguas] == [10, 50, 100]
    assert all(r.winfo_height() == 20 for r in reguas)
    assert [r.cget("text") for r in reguas] == ["10px", "50px", "100px"]
    assert dto.live_testids() == []
    ctrl.toggle_px_ruler()
    assert ctrl.ruler_labels() == []


def test_painel_etiquetas_texto_igual_testid_sobre_alvos(tk_root) -> None:
    _visivel(tk_root, "fp-corpo", tk.Frame, side="top")
    _visivel(tk_root, "fp-botao", tk.Button, side="top")
    tk_root.geometry("400x300")
    tk_root.deiconify()
    tk_root.update()
    ctrl = dto.DataTestController(tk_root)
    ctrl.set_mode(dto.MODE_BODY)
    assert [t for t, _l in ctrl.overlay_labels()] == ["fp-corpo"]
    assert all(lb.cget("text") == t for t, lb in ctrl.overlay_labels())
    ctrl.set_mode(dto.MODE_BUTTONS)
    assert [t for t, _l in ctrl.overlay_labels()] == ["fp-botao"]
    assert all(lb.cget("text") == t for t, lb in ctrl.overlay_labels())
    assert "fp-botao" in dto.live_testids() and len(dto.live_testids()) == 2


def test_painel_clique_copia_testid_puro_e_flash_600ms(tk_root, monkeypatch) -> None:
    _visivel(tk_root, "fp-copiavel", tk.Button, side="top")
    tk_root.geometry("400x300")
    tk_root.deiconify()
    tk_root.update()
    ctrl = dto.DataTestController(tk_root)
    ctrl.set_mode(dto.MODE_BUTTONS)
    testid, label = ctrl.overlay_labels()[0]
    cor_original = label.cget("bg")
    agendados: list = []
    monkeypatch.setattr(tk_root, "after", lambda delay, cb=None, *a: agendados.append((delay, cb)) or "after#x")

    assert ctrl.copy_testid(testid, label) is True
    assert tk_root.clipboard_get() == "fp-copiavel"
    assert "data-testid" not in tk_root.clipboard_get()
    assert label.cget("text") == "copiado"
    assert len(agendados) == 1 and agendados[0][0] == dto.COPY_FLASH_MS == 600
    agendados[0][1]()
    assert label.cget("text") == "fp-copiavel"
    assert label.cget("bg") == cor_original


def test_painel_clique_duplo_durante_flash_restaura_texto_original(tk_root, monkeypatch) -> None:
    ctrl = dto.DataTestController(tk_root)
    label = tk.Label(tk_root, text="fp-duplo", bg="#89b4fa")
    agendados: dict = {}
    cancelados: list = []

    def _after(delay, cb=None, *a):
        after_id = f"after#{len(agendados)}"
        agendados[after_id] = cb
        return after_id

    monkeypatch.setattr(tk_root, "after", _after)
    monkeypatch.setattr(tk_root, "after_cancel", cancelados.append)

    assert ctrl.copy_testid("fp-duplo", label) is True
    assert ctrl.copy_testid("fp-duplo", label) is True
    assert label.cget("text") == "copiado"
    assert cancelados == ["after#0"]
    agendados["after#1"]()
    assert label.cget("text") == "fp-duplo"
    assert label.cget("bg") == "#89b4fa"


def test_painel_clique_duplo_com_falha_nao_prende_mensagem(tk_root, monkeypatch, capsys) -> None:
    ctrl = dto.DataTestController(tk_root)
    label = tk.Label(tk_root, text="fp-y", bg="#89b4fa")
    agendados: list = []

    def _falha(_texto):
        raise tk.TclError("clipboard indisponivel")

    monkeypatch.setattr(tk_root, "clipboard_append", _falha)
    monkeypatch.setattr(tk_root, "after", lambda delay, cb=None, *a: agendados.append(cb) or f"after#{len(agendados)}")
    monkeypatch.setattr(tk_root, "after_cancel", lambda _id: None)

    assert ctrl.copy_testid("fp-y", label) is False
    assert ctrl.copy_testid("fp-y", label) is False
    assert label.cget("text") == "falhou ao copiar"
    agendados[-1]()
    assert label.cget("text") == "fp-y"
    assert "[forge-pick] DataTest: falha ao copiar" in capsys.readouterr().err


def test_painel_falha_de_clipboard_mostra_mensagem_e_loga(tk_root, monkeypatch, capsys) -> None:
    ctrl = dto.DataTestController(tk_root)
    label = tk.Label(tk_root, text="fp-x", bg="#89b4fa")

    def _falha(_texto):
        raise tk.TclError("clipboard indisponivel")

    monkeypatch.setattr(tk_root, "clipboard_append", _falha)
    assert ctrl.copy_testid("fp-x", label) is False
    assert label.cget("text") == "falhou ao copiar"
    assert "[forge-pick] DataTest: falha ao copiar" in capsys.readouterr().err


def test_painel_close_zera_modo_regua_e_etiquetas(tk_root) -> None:
    _visivel(tk_root, "fp-corpo", tk.Frame, side="top")
    tk_root.geometry("400x300")
    tk_root.deiconify()
    tk_root.update()
    avisos: list = []
    ctrl = dto.DataTestController(tk_root, on_panel_change=avisos.append)
    ctrl.open_panel()
    ctrl.on_mode_click("body")
    ctrl.toggle_px_ruler()
    assert ctrl.overlay_labels() and ctrl.ruler_labels()
    ctrl.close_panel()
    assert ctrl.mode == "off"
    assert ctrl.ruler_labels() == []
    assert ctrl.overlay_labels() == []
    assert ctrl.is_panel_open is False
    assert avisos == [True, False]


# -- paleta Catppuccin Mocha (item 014, D11) ---------------------------------

import re

_NOMES_PALETA = ("BG", "MANTLE", "SURFACE", "HOVER", "FG", "MUTED", "ACCENT",
                 "GREEN", "YELLOW", "VIOLET", "CYAN", "ORANGE")
_PALETA = {getattr(dto, n).lower() for n in _NOMES_PALETA}
_OPCOES_COR = ("bg", "fg", "activebackground", "activeforeground",
               "highlightbackground", "highlightcolor", "selectcolor",
               "insertbackground", "disabledforeground", "selectbackground",
               "selectforeground", "readonlybackground", "buttonbackground",
               "disabledbackground", "troughcolor")


def _fora_da_paleta(raiz):
    achados = []

    def visita(w):
        chaves = set(w.keys())
        for opcao in _OPCOES_COR:
            if opcao not in chaves or not str(w.cget(opcao)):
                continue
            rgb = w.winfo_rgb(str(w.cget(opcao)))
            # compara no mesmo espaco de cor do display (quantizacao do Tk)
            if rgb not in {w.winfo_rgb(h) for h in _PALETA}:
                achados.append((dto.testid_of(w) or w.winfo_class(), opcao, str(w.cget(opcao))))
        for filho in w.winfo_children():
            visita(filho)

    visita(raiz)
    return achados


def test_paleta_constantes_espelhadas_e_overlay_dentro_da_paleta() -> None:
    try:
        import app
    except tk.TclError as exc:
        pytest.skip(f"Tk indisponivel: {exc}")
    dif = [n for n in (*_NOMES_PALETA, "RADIUS") if getattr(dto, n) != getattr(app, n)]
    assert dif == [], f"fora de paridade com app.py: {dif}"
    assert dto.MODE_COLORS == {"main": dto.GREEN, "body": dto.VIOLET,
                               "buttons": dto.ACCENT, "px": dto.YELLOW}
    fora = [n for n in ("PANEL_BG", "LABEL_INK", "BTN_ACTIVE_FG", "BTN_INACTIVE_BG",
                        "BTN_INACTIVE_FG", "COPY_OK_BG", "COPY_FAIL_BG")
            if getattr(dto, n).lower() not in _PALETA]
    assert fora == [], fora
    arvore = ast.parse(Path(dto.__file__).read_text(encoding="utf-8"))
    ok: set = set()
    for no in ast.walk(arvore):
        if isinstance(no, ast.Assign) and any(
            isinstance(x, ast.Name) and x.id in _NOMES_PALETA for x in no.targets
        ):
            ok |= {id(c) for c in ast.walk(no.value)}
    ruins = [f"linha {n.lineno}: {n.value}" for n in ast.walk(arvore)
             if isinstance(n, ast.Constant) and isinstance(n.value, str)
             and re.match(r"^#[0-9a-fA-F]{6}$", n.value) and id(n) not in ok]
    assert ruins == [], ruins
    imports = [n for n in ast.walk(arvore)
               if (isinstance(n, ast.Import) and any(a.name == "app" for a in n.names))
               or (isinstance(n, ast.ImportFrom) and n.module == "app")]
    assert imports == []


def test_paleta_walker_do_painel_em_cada_modo_com_px_ruler(tk_root) -> None:
    _visivel(tk_root, "fp-corpo", tk.Frame, side="top")
    _visivel(tk_root, "fp-botao", tk.Button, side="top")
    tk_root.geometry("400x300")
    tk_root.deiconify()
    tk_root.update()
    ctrl = dto.DataTestController(tk_root)
    ctrl.open_panel()
    ctrl.toggle_px_ruler()
    tk_root.update()
    ruins = []
    for modo in (dto.MODE_MAIN, dto.MODE_BODY, dto.MODE_BUTTONS):
        ctrl.set_mode(modo)
        tk_root.update()
        ruins += [(modo, *i) for i in _fora_da_paleta(ctrl.panel)]
        for _t, label in ctrl.overlay_labels():
            ruins += [(modo, *i) for i in _fora_da_paleta(label)]
        for label in ctrl.ruler_labels():
            ruins += [(modo, "px", *i) for i in _fora_da_paleta(label)]
    assert ctrl.ruler_labels() != []
    assert ruins == [], ruins
    ctrl.close_panel()
