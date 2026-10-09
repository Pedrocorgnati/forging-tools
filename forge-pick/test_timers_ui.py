"""Testes de timers_ui (Task 010 — 3 colunas, estados, roda do mouse e tick)."""

from __future__ import annotations

import sqlite3
import types
from datetime import datetime, timedelta, timezone

import tkinter as tk

import pytest

import datatest_overlay as dto
import timers_store
import timers_ui

AGORA = datetime(2025, 6, 2, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def root():
    try:
        raiz = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk indisponivel: {exc}")
    raiz.withdraw()
    try:
        yield raiz
    finally:
        try:
            raiz.destroy()
        except tk.TclError:
            pass
        dto._reset_registry()


@pytest.fixture
def store(tmp_path):
    return timers_store.TimersStore(tmp_path / "timers.db")


def _widgets() -> dict:
    return {testid: widget for testid, widget in dto.registered_widgets()}


def _mk_timer(
    store,
    timer_id: str,
    title: str,
    *,
    now: datetime,
    seconds: int = 60,
    frequency: str = "weekly",
    mode: str = "datetime",
    weekly_weekday: int | None = None,
    weekly_time: str = "",
    monthly_day: int | None = None,
    daily_time: str = "",
) -> timers_store.ClockTimer:
    """Cria e persiste um ClockTimer com ends_at ISO UTC = now + seconds."""
    timer = timers_store.ClockTimer(
        id=timer_id,
        title=title,
        duration_seconds=max(0, seconds),
        remaining_seconds=max(0, seconds),
        ends_at=(now + timedelta(seconds=seconds)).isoformat(),
        mode=mode,
        weekly_weekday=weekly_weekday,
        weekly_time=weekly_time,
        monthly_day=monthly_day,
        daily_time=daily_time,
        frequency=frequency,
    )
    store.create_clock_timer(timer)
    return timer


# ── parte pura (D2) ─────────────────────────────────────────────────────────


def test_group_by_frequency_distribui_e_invalida_vai_para_weekly() -> None:
    def timer(timer_id: str, frequency: str, seconds: int) -> timers_store.ClockTimer:
        return timers_store.ClockTimer(
            id=timer_id,
            title=timer_id,
            ends_at=(AGORA + timedelta(seconds=seconds)).isoformat(),
            frequency=frequency,
        )

    timers = [
        timer("d1", "daily", 5),
        timer("w1", "weekly", 300),
        timer("w2", "weekly", 60),
        timer("m1", "monthly", 100),
        timer("x1", "yearly", 20),
    ]
    grouped = timers_ui.group_by_frequency(timers, AGORA)
    assert sorted(grouped) == ["daily", "monthly", "weekly"]
    assert [t.id for t in grouped["daily"]] == ["d1"]
    assert [t.id for t in grouped["weekly"]] == ["x1", "w2", "w1"]
    assert [t.id for t in grouped["monthly"]] == ["m1"]
    assert timers_ui.group_by_frequency([], AGORA) == {
        "daily": [],
        "weekly": [],
        "monthly": [],
    }


def test_format_remaining_formatos() -> None:
    assert timers_ui.format_remaining(0) == "00:00:00"
    assert timers_ui.format_remaining(3661) == "01:01:01"
    assert timers_ui.format_remaining(90061) == "1d 01:01:01"
    assert timers_ui.format_remaining(-5) == "00:00:00"


# ── layout e estados (D3, D5, D6, D7) ──────────────────────────────────────


def test_tres_sections_nas_colunas_0_1_2(root, store) -> None:
    view = timers_ui.TimersView(root, store, None)
    view.rerender(now=AGORA)
    widgets = _widgets()
    for indice, (freq, titulo) in enumerate(timers_ui.FREQUENCY_COLUMNS):
        section = widgets[f"fp-{freq}-section"]
        info = section.grid_info()
        assert int(info["row"]) == 1
        assert int(info["column"]) == indice
        assert widgets[f"fp-{freq}-section-title"].cget("text") == titulo
        assert view.column_body(freq).master is view._columns[freq]["canvas"]


def test_banco_13_timers_distribui_por_coluna(root, store) -> None:
    seq = 0
    for frequency, mode, quantidade in (
        ("monthly", "datetime", 4),
        ("monthly", "monthly", 3),
        ("weekly", "datetime", 2),
        ("weekly", "weekly", 4),
    ):
        for ordem in range(quantidade):
            seq += 1
            _mk_timer(
                store,
                f"timer-{seq:02d}",
                f"Timer {seq:02d}",
                now=AGORA,
                seconds=60 * seq,
                frequency=frequency,
                mode=mode,
            )
    view = timers_ui.TimersView(root, store, None)
    view.rerender(now=AGORA)

    diarios = view.column_body("daily").winfo_children()
    assert [w.cget("text") for w in diarios] == ["Nenhum temporizador diario"]
    assert len(view.column_body("weekly").winfo_children()) == 6
    assert len(view.column_body("monthly").winfo_children()) == 7
    assert len(view._cards) == 13
    assert "fp-daily-empty" in _widgets()


def test_store_vazio_mostra_textos_de_vazio(root, store) -> None:
    view = timers_ui.TimersView(root, store, None)
    view.rerender(now=AGORA)
    widgets = _widgets()
    for freq, _titulo in timers_ui.FREQUENCY_COLUMNS:
        assert widgets[f"fp-{freq}-empty"].cget("text") == timers_ui.EMPTY_TEXTS[freq]
        assert [w.cget("text") for w in view.column_body(freq).winfo_children()] == [
            timers_ui.EMPTY_TEXTS[freq]
        ]


def test_store_none_mostra_erro_e_tick_nao_inicia(root) -> None:
    view = timers_ui.TimersView(root, None, "falha ao abrir o banco")
    view.rerender(now=AGORA)
    for freq, _titulo in timers_ui.FREQUENCY_COLUMNS:
        filhos = view.column_body(freq).winfo_children()
        assert [w.cget("text") for w in filhos] == [
            "Erro ao ler temporizadores: falha ao abrir o banco"
        ]
    view.start_tick()
    assert view._after_id is None

    sem_mensagem = timers_ui.TimersView(root, None, None)
    sem_mensagem.rerender(now=AGORA)
    assert [w.cget("text") for w in sem_mensagem.column_body("daily").winfo_children()] == [
        "Erro ao ler temporizadores: banco de timers indisponivel"
    ]


def test_erro_de_listagem_mostra_erro_nas_tres_colunas(root, store, monkeypatch) -> None:
    def estoura():
        raise sqlite3.OperationalError("disco cheio")

    monkeypatch.setattr(store, "list_clock_timers", estoura)
    view = timers_ui.TimersView(root, store, None)
    view.rerender(now=AGORA)
    widgets = _widgets()
    for freq, _titulo in timers_ui.FREQUENCY_COLUMNS:
        assert widgets[f"fp-{freq}-error"].cget("text") == (
            "Erro ao ler temporizadores: disco cheio"
        )


def test_boot_error_com_store_mostra_aviso(root, store) -> None:
    _mk_timer(store, "semanal-1", "Semanal", now=AGORA, seconds=600, frequency="weekly")
    view = timers_ui.TimersView(root, store, "importacao interrompida")
    view.rerender(now=AGORA)
    widgets = _widgets()
    assert widgets["fp-timers-warning"].cget("text") == (
        "Aviso ao carregar timers: importacao interrompida"
    )
    assert len(view.column_body("weekly").winfo_children()) == 1
    assert "fp-weekly-empty" not in widgets


# ── roda do mouse (D4) ─────────────────────────────────────────────────────


def test_roda_rola_so_coluna_sob_o_cursor(root, store, monkeypatch) -> None:
    for ordem in range(8):
        _mk_timer(
            store,
            f"semanal-{ordem:02d}",
            f"Semanal {ordem}",
            now=AGORA,
            seconds=60 + ordem,
            frequency="weekly",
        )
    view = timers_ui.TimersView(root, store, None)
    view.rerender(now=AGORA)
    alvo = view._cards["semanal-00"]
    monkeypatch.setattr(view.frame, "winfo_containing", lambda _x, _y: alvo)

    chamadas: list = []
    for freq, _titulo in timers_ui.FREQUENCY_COLUMNS:
        canvas = view._columns[freq]["canvas"]
        janela = (0.0, 0.5) if freq == "weekly" else (0.0, 1.0)
        monkeypatch.setattr(canvas, "yview", lambda _j=janela: _j)
        monkeypatch.setattr(
            canvas, "yview_scroll", lambda *args, _f=freq: chamadas.append((_f, args))
        )

    assert view.on_mousewheel(types.SimpleNamespace(num=5, delta=0, x_root=10, y_root=10)) is True
    assert chamadas == [("weekly", (1, "units"))]

    del chamadas[:]
    assert view.on_mousewheel(types.SimpleNamespace(num=0, delta=120, x_root=10, y_root=10)) is True
    assert chamadas == [("weekly", (-1, "units"))]


def test_roda_fora_das_colunas_ou_sem_x_root_nao_rola(root, store, monkeypatch) -> None:
    view = timers_ui.TimersView(root, store, None)
    view.rerender(now=AGORA)

    chamadas: list = []
    for freq, _titulo in timers_ui.FREQUENCY_COLUMNS:
        canvas = view._columns[freq]["canvas"]
        monkeypatch.setattr(canvas, "yview", lambda: (0.0, 1.0))
        monkeypatch.setattr(
            canvas, "yview_scroll", lambda *args, _f=freq: chamadas.append((_f, args))
        )

    monkeypatch.setattr(view.frame, "winfo_containing", lambda _x, _y: None)
    assert view.on_mousewheel(types.SimpleNamespace(num=5, delta=0, x_root=1, y_root=2)) is False

    monkeypatch.setattr(view.frame, "winfo_containing", lambda _x, _y: view.frame)
    assert view.on_mousewheel(types.SimpleNamespace(num=5, delta=0, x_root=1, y_root=2)) is False

    def estoura(_x, _y):
        raise tk.TclError("sem janela")

    monkeypatch.setattr(view.frame, "winfo_containing", estoura)
    assert view.on_mousewheel(types.SimpleNamespace(num=5, delta=0, x_root=1, y_root=2)) is False

    assert view.on_mousewheel(types.SimpleNamespace(num=5, delta=0)) is False
    assert chamadas == []


# ── tick de 1 Hz (D8) ──────────────────────────────────────────────────────


def test_tick_rola_vencido_persiste_e_atualiza_card(root, store) -> None:
    timer = _mk_timer(
        store,
        "vencido",
        "Timer semanal",
        now=AGORA,
        seconds=-60,
        frequency="weekly",
        mode="weekly",
        weekly_weekday=0,
        weekly_time="10:00",
    )
    view = timers_ui.TimersView(root, store, None)
    view.rerender(now=AGORA)

    assert view.tick(now=AGORA) is True

    recarregado = store.list_clock_timers()[0]
    novo_fim = datetime.fromisoformat(recarregado.ends_at.replace("Z", "+00:00"))
    assert novo_fim > AGORA
    restante = timers_store._remaining_seconds(recarregado, AGORA)
    assert restante > 0
    assert view._cards[timer.id].time_label.cget("text") == timers_ui.format_remaining(restante)


def test_tick_com_erro_para_atualizacao(root, store, monkeypatch) -> None:
    _mk_timer(store, "semanal-1", "Semanal", now=AGORA, seconds=600, frequency="weekly")

    def estoura(now=None):
        raise sqlite3.OperationalError("banco bloqueado")

    monkeypatch.setattr(store, "roll_due_fixed_timers", estoura)
    view = timers_ui.TimersView(root, store, None)
    view.rerender(now=AGORA)

    assert view.tick(now=AGORA) is False

    widgets = _widgets()
    esperado = (
        "Erro ao ler temporizadores: banco bloqueado "
        "(atualizacao automatica pausada; reabra o Forge Pick)"
    )
    for freq, _titulo in timers_ui.FREQUENCY_COLUMNS:
        assert widgets[f"fp-{freq}-error"].cget("text") == esperado


def test_start_tick_agenda_uma_vez_e_destroy_cancela(root, store, monkeypatch) -> None:
    view = timers_ui.TimersView(root, store, None)
    view.rerender(now=AGORA)

    chamadas: list = []

    def agenda(ms, callback):
        chamadas.append((ms, callback))
        return f"after#{len(chamadas)}"

    monkeypatch.setattr(view.frame, "after", agenda)

    view.start_tick()
    view.start_tick()
    assert len(chamadas) == 1
    assert chamadas[0][0] == 1000
    assert view._after_id == "after#1"

    view.frame.destroy()
    assert view._after_id is None


# ── contrato 010 -> 011 ────────────────────────────────────────────────────


def test_rerender_contrato_column_body_e_card_factory(root, store) -> None:
    view = timers_ui.TimersView(root, store, None)
    view.rerender(now=AGORA)
    assert view.column_body("daily") is view._columns["daily"]["body"]

    criados: list = []

    def fabrica(parent, timer, now):
        criados.append(timer.id)
        return tk.Label(parent, text=f"card:{timer.title}", bg="#123456")

    view.card_factory = fabrica
    _mk_timer(store, "diario-1", "Beber agua", now=AGORA, seconds=600, frequency="daily")
    view.rerender(now=AGORA)

    assert criados == ["diario-1"]
    assert [w.cget("text") for w in view.column_body("daily").winfo_children()] == [
        "card:Beber agua"
    ]
    with pytest.raises(ValueError) as excinfo:
        view.column_body("yearly")
    assert "yearly" in str(excinfo.value)


# ── card do timer e acoes (D11) ────────────────────────────────────────────


def test_card_mostra_titulo_tempo_cor_e_testids(root) -> None:
    timer = timers_store.ClockTimer(
        id="azul-1",
        title="Timer azul",
        ends_at=(AGORA + timedelta(seconds=61)).isoformat(),
        color="#3B82F6",
        frequency="weekly",
    )
    card = timers_ui.TimerCard(
        root,
        timer,
        on_edit=lambda: None,
        on_alert=lambda: None,
        on_pause=lambda: None,
        on_plus_one=lambda: None,
        on_delete=lambda: None,
    )
    card.apply(timer, AGORA)

    slug = dto.testid_slug(timer.id)
    assert card.timer_id == "azul-1"
    assert card.title_label.cget("text") == "Timer azul"
    assert card.time_label.cget("text") == timers_ui.format_remaining(61)
    assert card.stripe.cget("bg") == timers_ui.display_timer_color("#3B82F6")
    assert dto.testid_of(card) == f"fp-timer-{slug}"
    assert dto.testid_of(card.stripe) == f"fp-timer-color-{slug}"
    assert dto.testid_of(card.title_label) == f"fp-timer-title-{slug}"
    assert dto.testid_of(card.time_label) == f"fp-timer-time-{slug}"
    assert dto.testid_of(card.edit_btn) == f"fp-timer-edit-{slug}"
    assert dto.testid_of(card.alert_btn) == f"fp-timer-alert-{slug}"
    assert dto.testid_of(card.pause_btn) == f"fp-timer-pause-{slug}"
    assert dto.testid_of(card.plus_one_btn) == f"fp-timer-plus-one-{slug}"
    assert dto.testid_of(card.delete_btn) == f"fp-timer-delete-{slug}"


def test_card_cor_fora_da_paleta_usa_cinza(root) -> None:
    timer = timers_store.ClockTimer(
        id="cor-estranha",
        title="Fora da paleta",
        ends_at=(AGORA + timedelta(seconds=10)).isoformat(),
        color="#ABCDEF",
        frequency="weekly",
    )
    card = timers_ui.TimerCard(
        root,
        timer,
        on_edit=lambda: None,
        on_alert=lambda: None,
        on_pause=lambda: None,
        on_plus_one=lambda: None,
        on_delete=lambda: None,
    )
    card.apply(timer, AGORA)

    assert timers_ui.normalize_timer_color("#ABCDEF") == timers_ui.DEFAULT_TIMER_COLOR
    assert timers_ui.normalize_timer_color("#3B82F6") == "#3B82F6"
    assert card.stripe.cget("bg") == timers_ui.display_timer_color(timers_ui.DEFAULT_TIMER_COLOR)


def test_card_em_andamento_botoes_e_semaforo_verde(root) -> None:
    timer = timers_store.ClockTimer(
        id="rodando-3",
        title="Rodando 3",
        ends_at=(AGORA + timedelta(seconds=120)).isoformat(),
        frequency="weekly",
    )
    card = timers_ui.TimerCard(
        root,
        timer,
        on_edit=lambda: None,
        on_alert=lambda: None,
        on_pause=lambda: None,
        on_plus_one=lambda: None,
        on_delete=lambda: None,
    )
    card.apply(timer, AGORA)

    assert card.time_label.cget("fg") == timers_ui.SEMAPHORE[False][0]
    assert card.alert_btn.cget("fg") == timers_ui.SEMAPHORE[False][1]
    assert card.pause_btn.cget("text") == "⏸"
    assert card.edit_btn.winfo_manager() == "pack"
    assert card.alert_btn.winfo_manager() == "pack"
    assert card.pause_btn.winfo_manager() == "pack"
    assert card.plus_one_btn.winfo_manager() == ""
    assert card.delete_btn.winfo_manager() == ""


def test_pausar_persiste_e_mostra_retomar_e_excluir(root, store) -> None:
    timer = _mk_timer(
        store, "pausavel-4", "Pausavel 4", now=AGORA, seconds=600, frequency="weekly"
    )
    view = timers_ui.TimersView(root, store, None)
    view.rerender(now=AGORA)

    assert view.toggle_pause(timer.id, now=AGORA) is True

    persistido = store.list_clock_timers()[0]
    assert persistido.paused is True
    assert persistido.paused_at == AGORA.isoformat()
    card = view._cards[timer.id]
    assert card.pause_btn.cget("text") == "▶"
    assert card.delete_btn.winfo_manager() == "pack"
    assert card.plus_one_btn.winfo_manager() == ""


def test_retomar_desloca_ends_at_pelo_tempo_pausado(root, store) -> None:
    timer = _mk_timer(
        store, "retomavel-5", "Retomavel 5", now=AGORA, seconds=600, frequency="weekly"
    )
    view = timers_ui.TimersView(root, store, None)
    view.rerender(now=AGORA)

    assert view.toggle_pause(timer.id, now=AGORA) is True
    depois = AGORA + timedelta(seconds=120)
    assert view.toggle_pause(timer.id, now=depois) is True

    persistido = store.list_clock_timers()[0]
    original = datetime.fromisoformat(timer.ends_at.replace("Z", "+00:00"))
    novo = datetime.fromisoformat(persistido.ends_at.replace("Z", "+00:00"))
    assert (novo - original) == timedelta(seconds=120)
    assert persistido.paused is False
    assert persistido.paused_at is None


def test_alerta_alterna_e_persiste_vermelho(root, store) -> None:
    timer = _mk_timer(
        store, "alerta-6", "Alerta 6", now=AGORA, seconds=600, frequency="weekly"
    )
    view = timers_ui.TimersView(root, store, None)
    view.rerender(now=AGORA)

    assert view.toggle_alert(timer.id, now=AGORA) is True
    assert store.list_clock_timers()[0].alert is True
    card = view._cards[timer.id]
    assert card.time_label.cget("fg") == timers_ui.SEMAPHORE[True][0]
    assert card.alert_btn.cget("fg") == timers_ui.SEMAPHORE[True][1]

    assert view.toggle_alert(timer.id, now=AGORA) is True
    assert store.list_clock_timers()[0].alert is False


def test_excluir_confirmado_remove_do_store(root, store, monkeypatch) -> None:
    timer = _mk_timer(
        store,
        "zerado-7",
        "Zerado 7",
        now=AGORA,
        seconds=-60,
        frequency="weekly",
        mode="datetime",
    )
    view = timers_ui.TimersView(root, store, None)
    view.rerender(now=AGORA)

    chamados: list = []

    def confirma(titulo, mensagem, parent=None):
        chamados.append((titulo, mensagem))
        return True

    monkeypatch.setattr(timers_ui.messagebox, "askyesno", confirma)

    assert view.delete_timer(timer.id, now=AGORA) is True

    assert chamados == [("Excluir temporizador", 'Excluir o temporizador "Zerado 7"?')]
    assert store.list_clock_timers() == []


def test_excluir_cancelado_nao_altera_store(root, store, monkeypatch) -> None:
    timer = _mk_timer(
        store,
        "zerado-8",
        "Zerado 8",
        now=AGORA,
        seconds=-60,
        frequency="weekly",
        mode="datetime",
    )
    view = timers_ui.TimersView(root, store, None)
    view.rerender(now=AGORA)

    chamados: list = []

    def cancela(titulo, mensagem, parent=None):
        chamados.append((titulo, mensagem))
        return False

    monkeypatch.setattr(timers_ui.messagebox, "askyesno", cancela)

    assert view.delete_timer(timer.id, now=AGORA) is False

    assert chamados == [("Excluir temporizador", 'Excluir o temporizador "Zerado 8"?')]
    assert [t.id for t in store.list_clock_timers()] == [timer.id]


def test_excluir_e_mais_uma_hora_ignorados_em_timer_rodando(root, store, monkeypatch) -> None:
    timer = _mk_timer(
        store, "rodando-9", "Rodando 9", now=AGORA, seconds=600, frequency="weekly"
    )
    view = timers_ui.TimersView(root, store, None)
    view.rerender(now=AGORA)

    confirmacoes: list = []
    monkeypatch.setattr(
        timers_ui.messagebox,
        "askyesno",
        lambda *args, **kwargs: confirmacoes.append(args) or True,
    )
    antes = [vars(t) for t in store.list_clock_timers()]

    assert view.delete_timer(timer.id, now=AGORA) is False
    assert view.restart_one_hour(timer.id, now=AGORA) is False

    assert confirmacoes == []
    assert [vars(t) for t in store.list_clock_timers()] == antes


def test_mais_uma_hora_reinicia_zerado_com_alerta_verde(root, store) -> None:
    timer = _mk_timer(
        store,
        "zerado-10",
        "Zerado 10",
        now=AGORA,
        seconds=-60,
        frequency="weekly",
        mode="datetime",
    )
    timer.alert = True
    store.update_clock_timer(timer)
    view = timers_ui.TimersView(root, store, None)
    view.rerender(now=AGORA)

    assert view.restart_one_hour(timer.id, now=AGORA) is True

    persistido = store.list_clock_timers()[0]
    assert persistido.duration_seconds == 3600
    assert persistido.remaining_seconds == 3600
    assert persistido.ends_at == (AGORA + timedelta(seconds=3600)).isoformat()
    assert persistido.state == "running"
    assert persistido.paused is False
    assert persistido.paused_at is None
    assert persistido.alert is False


def test_zerado_feedback_so_visual_sem_persistir_done(root, store) -> None:
    timer = _mk_timer(
        store,
        "zerado-11",
        "Zerado 11",
        now=AGORA,
        seconds=-60,
        frequency="weekly",
        mode="datetime",
    )
    view = timers_ui.TimersView(root, store, None)
    view.rerender(now=AGORA)

    card = view._cards[timer.id]
    assert card.time_label.cget("text") == "Finalizado"
    assert card.time_label.cget("fg") == timers_ui.ORANGE
    assert card.edit_btn.winfo_manager() == "pack"
    assert card.plus_one_btn.winfo_manager() == "pack"
    assert card.delete_btn.winfo_manager() == "pack"
    assert card.alert_btn.winfo_manager() == ""
    assert card.pause_btn.winfo_manager() == ""
    assert store.list_clock_timers()[0].state == "running"


def test_falha_ao_persistir_mostra_erro_e_rerenderiza(root, store, monkeypatch) -> None:
    timer = _mk_timer(
        store, "alerta-12", "Alerta 12", now=AGORA, seconds=600, frequency="weekly"
    )
    view = timers_ui.TimersView(root, store, None)
    view.rerender(now=AGORA)
    card_antes = view._cards[timer.id]
    antes = store.list_clock_timers()

    def estoura(_timer):
        raise sqlite3.OperationalError("banco bloqueado")

    monkeypatch.setattr(store, "update_clock_timer", estoura)
    erros: list = []
    monkeypatch.setattr(
        timers_ui.messagebox,
        "showerror",
        lambda titulo, mensagem, parent=None: erros.append((titulo, mensagem)),
    )

    assert view.toggle_alert(timer.id, now=AGORA) is False

    assert erros == [
        (
            "Temporizadores",
            'Nao foi possivel alternar o alerta de "Alerta 12": banco bloqueado',
        )
    ]
    assert [vars(t) for t in store.list_clock_timers()] == [vars(t) for t in antes]
    assert store.list_clock_timers()[0].alert is False
    assert view._cards[timer.id] is not card_antes
    assert view._cards[timer.id].alert_btn.cget("fg") == timers_ui.SEMAPHORE[False][1]


def test_editar_chama_on_edit_com_timer_ou_avisa(root, store, monkeypatch) -> None:
    timer = _mk_timer(
        store, "editavel-13", "Editavel 13", now=AGORA, seconds=600, frequency="weekly"
    )
    view = timers_ui.TimersView(root, store, None)
    view.rerender(now=AGORA)

    recebidos: list = []
    view.on_edit = recebidos.append

    assert view.edit_timer(timer.id) is True
    assert [t.id for t in recebidos] == ["editavel-13"]
    assert [t.title for t in recebidos] == ["Editavel 13"]

    card = view._cards[timer.id]
    root.deiconify()
    root.update()
    card.title_label.event_generate("<Button-1>")
    root.update()
    card.time_label.event_generate("<Button-1>")
    root.update()
    assert [t.id for t in recebidos] == ["editavel-13", "editavel-13", "editavel-13"]

    avisos: list = []
    monkeypatch.setattr(
        timers_ui.messagebox,
        "showinfo",
        lambda titulo, mensagem, parent=None: avisos.append((titulo, mensagem)),
    )
    view.on_edit = None

    assert view.edit_timer(timer.id) is False
    assert avisos == [("Editar timer", "A edicao de timers ainda nao esta disponivel.")]


def test_todo_botao_tem_handler_e_testid_fp(root, store) -> None:
    _mk_timer(store, "completo", "Completo", now=AGORA, seconds=600, frequency="weekly")
    _mk_timer(
        store,
        "completo-zerado",
        "Completo zerado",
        now=AGORA,
        seconds=-60,
        frequency="weekly",
        mode="datetime",
    )
    view = timers_ui.TimersView(root, store, None)
    view.rerender(now=AGORA)

    def descendentes(widget):
        for filho in widget.winfo_children():
            yield filho
            yield from descendentes(filho)

    for timer_id in ("completo", "completo-zerado"):
        card = view._cards[timer_id]
        botoes = [w for w in descendentes(card) if isinstance(w, tk.Button)]
        assert len(botoes) == 5
        for botao in botoes:
            assert botao.cget("command") != ""
            assert (dto.testid_of(botao) or "").startswith("fp-timer-")

    rodando = view._cards["completo"]
    zerado = view._cards["completo-zerado"]
    assert rodando.plus_one_btn.winfo_manager() == ""
    assert rodando.delete_btn.winfo_manager() == ""
    assert zerado.alert_btn.winfo_manager() == ""
    assert zerado.pause_btn.winfo_manager() == ""


def test_tick_atualiza_card_in_place(root, store) -> None:
    timer = _mk_timer(
        store, "in-place-15", "In place 15", now=AGORA, seconds=600, frequency="weekly"
    )
    view = timers_ui.TimersView(root, store, None)
    view.rerender(now=AGORA)

    card = view._cards[timer.id]
    filhos = list(view.column_body("weekly").winfo_children())

    assert view.tick(now=AGORA + timedelta(seconds=5)) is True

    assert view._cards[timer.id] is card
    assert card.time_label.cget("text") == timers_ui.format_remaining(595)
    novos = list(view.column_body("weekly").winfo_children())
    assert len(novos) == len(filhos)
    assert all(novo is antigo for novo, antigo in zip(novos, filhos))


# ── modal de cadastro e edicao (Task 012) ───────────────────────────────────


def _abrir_modal(root, store, timer=None):
    view = timers_ui.TimersView(root, store, None)
    view.rerender(now=AGORA)
    dialogo = view.open_edit_dialog(timer) if timer is not None else view.open_add_dialog()
    return view, dialogo


def _escolher_modo(dialogo, modo: str) -> None:
    dialogo.mode_var.set(modo)
    dialogo._on_mode_change()


def _gravar_erros(monkeypatch) -> list:
    erros: list = []
    monkeypatch.setattr(
        timers_ui.messagebox,
        "showerror",
        lambda titulo, mensagem, parent=None: erros.append((titulo, mensagem)),
    )
    return erros


def test_modal_frequencia_diario_antes_de_semanal_e_mensal(root, store) -> None:
    _view, dialogo = _abrir_modal(root, store)

    assert list(dialogo.frequency_radios) == ["daily", "weekly", "monthly"]
    assert [dialogo.frequency_radios[f].cget("text") for f in dialogo.frequency_radios] == [
        "Diario",
        "Semanal",
        "Mensal",
    ]
    assert dialogo.frequency_var.get() == "weekly"
    assert dialogo.mode_var.get() == "datetime"
    widgets = _widgets()
    for frequencia in ("daily", "weekly", "monthly"):
        assert f"fp-clock-timer-frequency-{frequencia}" in widgets


def test_modal_modo_horario_fixo_diario_presente(root, store) -> None:
    _view, dialogo = _abrir_modal(root, store)

    assert list(dialogo.mode_radios) == ["datetime", "daily", "weekly", "monthly"]
    assert dialogo.mode_radios["daily"].cget("text") == "Horario fixo (diario)"
    assert dto.testid_of(dialogo.mode_radios["daily"]) == "fp-clock-timer-mode-daily"
    assert dialogo.daily_time_var.get() == "09:00"
    assert "fp-clock-timer-daily-time-input" in _widgets()


def test_modal_salvar_diario_fixo_grava_e_aparece_na_coluna_daily(root, store) -> None:
    view, dialogo = _abrir_modal(root, store)
    dialogo.title_var.set("Standup")
    _escolher_modo(dialogo, "daily")

    assert dialogo.save(now=AGORA) is True

    [timer] = store.list_clock_timers()
    assert timer.title == "Standup"
    assert timer.mode == "daily"
    assert timer.frequency == "daily"
    assert timer.daily_time == "09:00"
    assert timer.weekly_weekday is None
    assert timer.monthly_day is None
    assert timer.weekly_time == ""
    assert timer.paused is False
    assert timer.state == "running"
    assert timer.id.startswith("tm-")
    assert timer.alert is False
    assert timer.ends_at == timers_store._next_daily_occurrence("09:00", AGORA)
    assert timer.id in view._cards
    assert view._cards[timer.id].master is view.column_body("daily")
    assert view._dialog is None


def test_modal_diario_fixo_zerado_reinicia_no_dia_seguinte(root, store) -> None:
    _view, dialogo = _abrir_modal(root, store)
    dialogo.title_var.set("Diario")
    _escolher_modo(dialogo, "daily")
    assert dialogo.save(now=AGORA) is True

    [timer] = store.list_clock_timers()
    esperado = timers_store._next_daily_occurrence("09:00", AGORA)
    assert timer.ends_at == esperado

    depois = timers_store._parse_iso(esperado) + timedelta(seconds=1)
    assert timers_store._roll_fixed_timer(timer, now=depois) is True
    assert timer.state == "running"
    assert timer.daily_time == "09:00"
    assert timer.ends_at == timers_store._next_daily_occurrence("09:00", depois)
    assert timers_store._parse_iso(timer.ends_at) > depois


def test_modal_edicao_abre_preenchida_e_grava_update(root, store, monkeypatch) -> None:
    timer = _mk_timer(
        store,
        "mensal-1",
        "Fechamento",
        now=AGORA,
        seconds=3600,
        frequency="monthly",
        mode="monthly",
        monthly_day=20,
        weekly_time="18:30",
    )
    timer.color = "#3B82F6"
    timer.alert = True
    store.update_clock_timer(timer)
    original = store.list_clock_timers()[0]
    view, dialogo = _abrir_modal(root, store, original)

    assert dialogo.title() == "Temporizador"
    assert dialogo.title_var.get() == "Fechamento"
    assert dialogo.mode_var.get() == "monthly"
    assert dialogo.frequency_var.get() == "monthly"
    assert dialogo.monthly_day_var.get() == 20
    assert dialogo.monthly_time_var.get() == "18:30"
    assert dialogo.weekly_time_var.get() == "18:30"  # weekly_time alimenta os dois HH:MM
    assert dialogo.color_var.get() == "#3B82F6"

    atualizacoes: list = []
    criacoes: list = []
    real_update = store.update_clock_timer
    monkeypatch.setattr(
        store, "update_clock_timer", lambda t: (atualizacoes.append(t), real_update(t))[1]
    )
    monkeypatch.setattr(store, "create_clock_timer", lambda t: criacoes.append(t))
    dialogo.title_var.set("Fechamento 2")
    dialogo.monthly_day_var.set(25)

    assert dialogo.save(now=AGORA) is True

    assert criacoes == []
    assert len(atualizacoes) == 1
    [persistido] = store.list_clock_timers()
    assert persistido.id == "mensal-1"
    assert persistido.title == "Fechamento 2"
    assert persistido.monthly_day == 25
    assert persistido.weekly_time == "18:30"
    assert persistido.alert is True
    assert persistido.created_at == original.created_at
    assert persistido.color == "#3B82F6"
    assert view._dialog is None


def test_modal_cancelar_e_esc_nao_gravam(root, store, monkeypatch) -> None:
    criacoes: list = []
    monkeypatch.setattr(store, "create_clock_timer", lambda t: criacoes.append(t))
    view, dialogo = _abrir_modal(root, store)
    dialogo.title_var.set("Nao salva")
    dialogo.cancel_btn.invoke()
    assert view._dialog is None
    assert not dialogo.winfo_exists()

    view, dialogo = _abrir_modal(root, store)
    dialogo.title_var.set("Esc")
    # Script Tcl do proprio binding: prova o <Escape> sem depender de foco do WM.
    script = dialogo.bind("<Escape>")
    assert script
    dialogo.tk.eval(script.replace("%#", "0").replace("%W", dialogo._w))
    assert not dialogo.winfo_exists()
    assert view._dialog is None

    view, dialogo = _abrir_modal(root, store)
    dialogo.title_var.set("Fechar janela")
    protocolo = dialogo.tk.call("wm", "protocol", dialogo._w, "WM_DELETE_WINDOW")
    assert protocolo
    dialogo.tk.call(protocolo)
    assert not dialogo.winfo_exists()
    assert view._dialog is None

    assert criacoes == []
    assert store.list_clock_timers() == []


def test_modal_validacao_inline_mensagens_e_botao_salvar(root, store) -> None:
    _view, dialogo = _abrir_modal(root, store)

    def erro() -> str:
        return dialogo.error_label.cget("text")

    assert erro() == "Informe o nome do temporizador."
    assert str(dialogo.save_btn.cget("state")) == "disabled"

    dialogo.title_var.set("Teste")
    assert erro() == ""
    assert str(dialogo.save_btn.cget("state")) == "normal"

    dialogo.end_var.set("31/02/2030 10:00")
    assert erro() == "Informe a data no formato DD/MM/AAAA HH:MM."
    dialogo.end_var.set("01/01/2000 10:00")
    assert erro() == "Escolha uma data/hora no futuro."
    dialogo.end_var.set("01/01/2999 10:00")
    dialogo.duration_var.set("1:00")
    assert erro() == "Informe a duracao no formato hhh:mm:ss."
    dialogo.duration_var.set("001:00:00")
    assert erro() == ""

    _escolher_modo(dialogo, "daily")
    dialogo.daily_time_var.set("25:99")
    assert erro() == "Informe um horario valido no formato HH:MM."
    assert str(dialogo.save_btn.cget("state")) == "disabled"
    dialogo.daily_time_var.set("07:15")
    assert erro() == ""

    _escolher_modo(dialogo, "weekly")
    assert erro() == "Escolha um dia da semana e um horario validos."
    dialogo.weekday_var.set(2)
    assert erro() == ""

    _escolher_modo(dialogo, "monthly")
    dialogo.monthly_day_var.set(32)
    assert erro() == "Escolha um dia do mes e um horario validos."
    dialogo.monthly_day_var.set(15)
    assert erro() == ""
    assert dialogo.save(now=AGORA) is True


def test_modal_modo_fixo_forca_frequencia(root, store) -> None:
    _view, dialogo = _abrir_modal(root, store)

    _escolher_modo(dialogo, "daily")
    assert dialogo.frequency_var.get() == "daily"
    assert str(dialogo.frequency_radios["weekly"].cget("state")) == "disabled"
    _escolher_modo(dialogo, "monthly")
    assert dialogo.frequency_var.get() == "monthly"
    _escolher_modo(dialogo, "weekly")
    assert dialogo.frequency_var.get() == "weekly"

    _escolher_modo(dialogo, "datetime")
    assert str(dialogo.frequency_radios["weekly"].cget("state")) == "normal"
    dialogo.frequency_var.set("daily")
    dialogo.title_var.set("Livre")
    dialogo.end_var.set("01/01/2999 10:00")
    assert dialogo.save(now=AGORA) is True
    [timer] = store.list_clock_timers()
    assert timer.mode == "datetime"
    assert timer.frequency == "daily"
    assert timer.id in _view._cards
    assert _view._cards[timer.id].master is _view.column_body("daily")


def test_modal_falha_do_store_mantem_dialogo_aberto(root, store, monkeypatch) -> None:
    erros = _gravar_erros(monkeypatch)
    view, dialogo = _abrir_modal(root, store)
    dialogo.title_var.set("Falha")
    _escolher_modo(dialogo, "daily")

    def estoura(_timer):
        raise sqlite3.OperationalError("banco bloqueado")

    monkeypatch.setattr(store, "create_clock_timer", estoura)

    assert dialogo.save(now=AGORA) is False

    assert erros == [
        ("Temporizadores", 'Nao foi possivel salvar "Falha": banco bloqueado')
    ]
    assert dialogo.winfo_exists()
    assert view._dialog is dialogo
    assert store.list_clock_timers() == []
    dialogo.cancel()

    sem_banco = timers_ui.TimersView(root, None, "disco cheio")
    assert sem_banco.open_add_dialog() is None
    assert erros[-1] == ("Temporizadores", "Banco de timers indisponivel: disco cheio")
    assert sem_banco._dialog is None


def test_modal_clock_timer_not_found_fecha_e_rerenderiza(root, store, monkeypatch) -> None:
    erros = _gravar_erros(monkeypatch)
    timer = _mk_timer(store, "sumiu", "Sumiu", now=AGORA, seconds=3600, frequency="weekly")
    view, dialogo = _abrir_modal(root, store, store.list_clock_timers()[0])
    dialogo.title_var.set("Sumiu 2")

    store.delete_clock_timer(timer.id)

    assert dialogo.save(now=AGORA) is False

    assert len(erros) == 1
    assert erros[0][0] == "Temporizadores"
    assert erros[0][1].startswith('Nao foi possivel salvar "Sumiu 2": ')
    assert view._dialog is None
    assert not dialogo.winfo_exists()
    assert "sumiu" not in view._cards
    assert store.list_clock_timers() == []


def test_modal_instancia_unica(root, store) -> None:
    view, primeiro = _abrir_modal(root, store)

    segundo = view.open_add_dialog()
    assert segundo is primeiro
    timer = _mk_timer(store, "outro", "Outro", now=AGORA, seconds=600)
    assert view.open_edit_dialog(timer) is primeiro

    primeiro.cancel()
    assert view._dialog is None
    novo = view.open_add_dialog()
    assert novo is not primeiro
    assert view._dialog is novo
    novo.cancel()


def test_modal_format_e_parse_duration_text() -> None:
    assert timers_ui.format_duration_text(0) == "000:00:00"
    assert timers_ui.format_duration_text(3661) == "001:01:01"
    assert timers_ui.format_duration_text(86400) == "024:00:00"
    assert timers_ui.format_duration_text(-5) == "000:00:00"
    assert timers_ui.format_duration_text(10_000 * 3600) == "999:00:00"
    assert timers_ui.parse_duration_text("001:00:00") == 3600
    assert timers_ui.parse_duration_text("999:59:59") == 999 * 3600 + 59 * 60 + 59
    for invalido in ("", "1:00:00", "001:0:00", "001:60:00", "001:00:60", "abc:de:fg", "001:00", None):
        assert timers_ui.parse_duration_text(invalido) is None


def test_modal_todo_botao_com_handler_e_testid_fp(root, store) -> None:
    _view, dialogo = _abrir_modal(root, store)

    def descendentes(widget):
        for filho in widget.winfo_children():
            yield filho
            yield from descendentes(filho)

    botoes = [w for w in descendentes(dialogo) if isinstance(w, tk.Button)]
    # 2 copiar/renderizar testid + 2 atalhos + 6 cores + salvar + cancelar
    assert len(botoes) == 12
    for botao in botoes:
        assert botao.cget("command") != ""
        assert (dto.testid_of(botao) or "").startswith("fp-clock-timer-")
    for radio in [w for w in descendentes(dialogo) if isinstance(w, tk.Radiobutton)]:
        assert radio.cget("command") != ""
        assert (dto.testid_of(radio) or "").startswith("fp-clock-timer-")
    assert [n for n in (dto.testid_of(b) for b in dialogo.color_buttons.values())] == [
        f"fp-clock-timer-color-{nome}" for nome, _hex in timers_ui.TIMER_COLORS
    ]
    # swatches compactos: imagem quadrada de cor, sem rotulo textual (referencia task-manager-desktop)
    assert [str(b.cget("text")) for b in dialogo.color_buttons.values()] == [
        "" for _nome, _hex in timers_ui.TIMER_COLORS
    ]
    assert all(str(b.cget("image")) != "" for b in dialogo.color_buttons.values())
    # sincronia duracao <-> data final com atalhos
    dialogo.title_var.set("Atalhos")
    dialogo.shortcut_1d_btn.invoke()
    assert dialogo.duration_var.get() == "024:00:00"
    dialogo.shortcut_7d_btn.invoke()
    assert dialogo.duration_var.get() == "168:00:00"
    dialogo.cancel()


# -- paleta Catppuccin Mocha (item 014, D11) ---------------------------------

import ast
import re
from pathlib import Path
from tkinter import ttk

_NOMES_PALETA = ("BG", "MANTLE", "SURFACE", "HOVER", "FG", "MUTED", "ACCENT",
                 "GREEN", "YELLOW", "VIOLET", "CYAN", "ORANGE")
_PALETA = {getattr(timers_ui, n).lower() for n in _NOMES_PALETA}
_OPCOES_COR = ("bg", "fg", "activebackground", "activeforeground",
               "highlightbackground", "highlightcolor", "selectcolor",
               "insertbackground", "disabledforeground", "selectbackground",
               "selectforeground", "readonlybackground", "buttonbackground",
               "disabledbackground", "troughcolor")
_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
_FONTES_OK = ("ubuntu", "ubuntu mono", "dejavu sans")


def _fora_da_paleta(raiz, paleta=_PALETA):
    """(testid/classe, opcao, hex) de toda cor de widget tk fora da paleta (ttk fica de fora)."""
    achados = []

    def visita(w):
        if type(w).__module__ != "tkinter.ttk":
            chaves = set(w.keys())
            for opcao in _OPCOES_COR:
                if opcao not in chaves or not str(w.cget(opcao)):
                    continue
                rgb = w.winfo_rgb(str(w.cget(opcao)))
                # compara no mesmo espaco de cor do display (quantizacao do Tk)
                if rgb not in {w.winfo_rgb(h) for h in paleta}:
                    achados.append((dto.testid_of(w) or w.winfo_class(), opcao, str(w.cget(opcao))))
        for filho in w.winfo_children():
            visita(filho)

    visita(raiz)
    return achados


def _hex_nao_permitidos(caminho: Path, nomes_ok: tuple, extras: tuple = ()) -> list:
    arvore = ast.parse(caminho.read_text(encoding="utf-8"))
    ok: set = set()
    for no in ast.walk(arvore):
        if isinstance(no, ast.Assign) and any(
            isinstance(x, ast.Name) and x.id in nomes_ok for x in no.targets
        ):
            ok |= {id(c) for c in ast.walk(no.value) if isinstance(c, ast.Constant)}
        if isinstance(no, ast.Assign) and any(
            isinstance(x, ast.Name) and x.id == "TIMER_COLOR_DISPLAY" for x in no.targets
        ) and isinstance(no.value, ast.Dict):
            ok |= {id(k) for k in no.value.keys}
    return [
        f"linha {n.lineno}: {n.value}"
        for n in ast.walk(arvore)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
        and _HEX_RE.match(n.value) and id(n) not in ok
    ]


def test_paleta_constantes_espelhadas_batem_com_app() -> None:
    try:
        import app
    except tk.TclError as exc:
        pytest.skip(f"Tk indisponivel: {exc}")
    dif = [n for n in (*_NOMES_PALETA, "RADIUS", "FONT_BTN", "FONT_WS")
           if getattr(timers_ui, n) != getattr(app, n)]
    assert dif == [], f"fora de paridade com app.py: {dif}"
    fonte = Path(timers_ui.__file__).read_text(encoding="utf-8")
    imports = [n for n in ast.walk(ast.parse(fonte))
               if (isinstance(n, ast.Import) and any(a.name == "app" for a in n.names))
               or (isinstance(n, ast.ImportFrom) and n.module == "app")]
    assert imports == []


def test_paleta_mapeamento_das_cores_e_exato_e_distinto() -> None:
    assert timers_ui.TIMER_COLOR_DISPLAY == {
        "#71717A": timers_ui.MUTED, "#3B82F6": timers_ui.ACCENT,
        "#92400E": timers_ui.VIOLET, "#22C55E": timers_ui.GREEN,
        "#FBBF24": timers_ui.YELLOW, "#EF4444": timers_ui.ORANGE,
    }
    assert len(set(timers_ui.TIMER_COLOR_DISPLAY.values())) == 6
    assert set(timers_ui.TIMER_COLOR_DISPLAY) == {h for _n, h in timers_ui.TIMER_COLORS}


def test_paleta_desconhecido_cai_em_muted_e_dado_intacto() -> None:
    assert timers_ui.display_timer_color("#ABCDEF") == timers_ui.MUTED
    assert timers_ui.DEFAULT_TIMER_COLOR == "#71717A"
    assert timers_ui.TIMER_COLORS == (
        ("cinza", "#71717A"), ("azul", "#3B82F6"), ("marrom", "#92400E"),
        ("verde", "#22C55E"), ("amarelo", "#FBBF24"), ("vermelho", "#EF4444"),
    )
    for _n, h in timers_ui.TIMER_COLORS:
        assert timers_ui.normalize_timer_color(h) == h
    assert timers_ui.normalize_timer_color("#ABCDEF") == "#71717A"


def test_paleta_walker_do_card_so_usa_tons_da_paleta(root, store) -> None:
    for i, (_n, hex_code) in enumerate(timers_ui.TIMER_COLORS):
        _mk_timer(store, f"cor-{i}", f"Cor {i}", now=AGORA, seconds=600)
    for chave in store.list_clock_timers():
        pass
    todos = store.list_clock_timers()
    for i, timer in enumerate(todos):
        timer.color = timers_ui.TIMER_COLORS[i][1]
        timer.alert = i % 2 == 1
        store.update_clock_timer(timer)
    view = timers_ui.TimersView(root, store, "aviso de importacao")
    view.rerender(now=AGORA)
    cards = list(view._cards.values())
    assert len(cards) == 6
    for estado in ("normal", "pausado", "finalizado"):
        for card, timer in zip(cards, store.list_clock_timers()):
            if estado == "pausado":
                timer.paused = True
            if estado == "finalizado":
                timer.paused = False
                timer.ends_at = (AGORA - timedelta(seconds=5)).isoformat()
            card.apply(timer, AGORA)
        assert _fora_da_paleta(view.frame) == [], estado
    assert {c.stripe.cget("bg") for c in cards} == set(timers_ui.TIMER_COLOR_DISPLAY.values())
    vazio = timers_ui.TimersView(root, timers_store.TimersStore(":memory:"), None)
    vazio.rerender(now=AGORA)
    assert _fora_da_paleta(vazio.frame) == []


def test_paleta_walker_do_dialogo_nos_4_modos_e_estilo_combobox(root, store) -> None:
    _view, dialogo = _abrir_modal(root, store)
    for modo in ("datetime", "daily", "weekly", "monthly"):
        _escolher_modo(dialogo, modo)
        dialogo.update_idletasks()
        assert _fora_da_paleta(dialogo) == [], modo
    estilo = ttk.Style(dialogo)
    for opcao in ("fieldbackground", "foreground", "background"):
        valor = estilo.lookup("FP.TCombobox", opcao)
        assert dialogo.winfo_rgb(valor) in {dialogo.winfo_rgb(h) for h in _PALETA}, (opcao, valor)
    assert str(dialogo.weekday_combo.cget("style")) == "FP.TCombobox"
    dialogo.cancel()


def test_paleta_salvar_com_azul_persiste_hex_gravado(root, store) -> None:
    _view, dialogo = _abrir_modal(root, store)
    dialogo.title_var.set("Azul")
    _escolher_modo(dialogo, "datetime")
    dialogo.duration_var.set("001:00:00")
    botao = dialogo.color_buttons["#3B82F6"]
    botao.invoke()
    assert botao.cget("bg") == timers_ui.ACCENT
    assert dialogo.save(now=AGORA) is True
    [salvo] = store.list_clock_timers()
    assert salvo.color == "#3B82F6"


def test_paleta_fontes_so_nas_familias_permitidas(root, store) -> None:
    _mk_timer(store, "f-1", "Fonte", now=AGORA, seconds=600)
    view = timers_ui.TimersView(root, store, None)
    view.rerender(now=AGORA)
    dialogo = view.open_add_dialog()
    ruins = []

    def visita(w):
        if type(w).__module__ != "tkinter.ttk" and "font" in w.keys() and w.winfo_class() in (
            "Label", "Button", "Entry", "Radiobutton", "Spinbox"
        ):
            f = str(w.cget("font")).lower().replace("{", "").replace("}", "")
            if not any(fam in f for fam in _FONTES_OK):
                ruins.append((w.winfo_class(), f))
        for filho in w.winfo_children():
            visita(filho)

    visita(view.frame)
    visita(dialogo)
    dialogo.cancel()
    assert ruins == [], ruins


def test_paleta_fonte_sem_literal_hex_fora_da_paleta() -> None:
    achados = _hex_nao_permitidos(
        Path(timers_ui.__file__), (*_NOMES_PALETA, "DEFAULT_TIMER_COLOR", "TIMER_COLORS")
    )
    assert achados == [], achados


def test_paleta_scrollbar_das_colunas_em_todos_os_estados(root, store) -> None:
    """DX1: o thumb das colunas fica na paleta em normal, disabled, active e pressed."""
    ttk.Style(root).theme_use("clam")  # mesma ordem do app.py: tema antes da TimersView
    view = timers_ui.TimersView(root, store, None)
    view.rerender(now=AGORA)
    root.update_idletasks()
    barras = [w for w in _descendentes(view.frame) if isinstance(w, ttk.Scrollbar)]
    assert len(barras) == 3
    assert {str(b.cget("style")) for b in barras} == {timers_ui.TIMERS_SCROLLBAR_STYLE}
    estilo = ttk.Style(view.frame)
    paleta_rgb = {view.frame.winfo_rgb(h) for h in _PALETA}
    for estado in ([], ["disabled"], ["active"], ["pressed"]):
        for opcao in ("background", "arrowcolor", "troughcolor", "bordercolor",
                      "lightcolor", "darkcolor"):
            valor = estilo.lookup(timers_ui.TIMERS_SCROLLBAR_STYLE, opcao, estado)
            assert view.frame.winfo_rgb(valor) in paleta_rgb, (estado, opcao, valor)


def _descendentes(w):
    for filho in w.winfo_children():
        yield filho
        yield from _descendentes(filho)
