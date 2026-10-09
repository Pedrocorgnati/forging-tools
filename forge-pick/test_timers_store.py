"""Testes da camada de dados dos timers do Forge Pick (``timers_store``).

Toda a suite roda sobre ``tmp_path``: nenhum teste abre os bancos reais em
``~/.local/share/``. O legado e uma fixture sintetica escrita aqui com SQL
inline, e os testes de recorrencia, roll, ordenacao e boot usam ``now``
injetado com o fuso fixado pela fixture ``fixed_tz``.
"""

from __future__ import annotations

import copy
import dataclasses
import hashlib
import itertools
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone

import pytest

import timers_store as ts

# Sabado, 09:00 em America/Sao_Paulo.
NOW = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)

_ids = itertools.count(1)


# --- Fixtures e helpers -----------------------------------------------------


@pytest.fixture(autouse=True)
def _isolar_bancos_reais(tmp_path, monkeypatch):
    """Segunda barreira: chamada sem caminho cai em ``tmp_path``, nunca no real."""
    monkeypatch.setattr(ts, "DEFAULT_DB_PATH", tmp_path / "nao-usar" / "timers.db")
    monkeypatch.setattr(ts, "LEGACY_DB_PATH", tmp_path / "nao-usar" / "tasks.db")


@pytest.fixture
def fixed_tz():
    previous = os.environ.get("TZ")
    os.environ["TZ"] = "America/Sao_Paulo"
    time.tzset()
    yield
    if previous is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = previous
    time.tzset()


@pytest.fixture
def store(tmp_path):
    timers_store = ts.TimersStore(tmp_path / "timers.db")
    yield timers_store
    timers_store.close()


_LEGACY_DDL = """
CREATE TABLE clock_timers (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  duration_seconds INTEGER NOT NULL,
  remaining_seconds INTEGER NOT NULL,
  ends_at TEXT NOT NULL DEFAULT '',
  state TEXT NOT NULL,
  paused INTEGER NOT NULL DEFAULT 0,
  paused_at TEXT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  color TEXT NOT NULL DEFAULT '#71717A',
  kind TEXT NOT NULL DEFAULT 'normal',
  mode TEXT NOT NULL DEFAULT 'datetime',
  weekly_weekday INTEGER NULL,
  weekly_time TEXT NOT NULL DEFAULT '',
  alert INTEGER NOT NULL DEFAULT 0,
  frequency TEXT NOT NULL DEFAULT 'weekly',
  monthly_day INTEGER NULL
)
"""

_LEGACY_COLUMNS = (
    "id",
    "title",
    "duration_seconds",
    "remaining_seconds",
    "ends_at",
    "state",
    "paused",
    "paused_at",
    "created_at",
    "updated_at",
    "color",
    "kind",
    "mode",
    "weekly_weekday",
    "weekly_time",
    "alert",
    "frequency",
    "monthly_day",
)


def _legacy_row(**values) -> dict:
    row = {
        "duration_seconds": 3600,
        "remaining_seconds": 0,
        "state": "running",
        "paused": 0,
        "paused_at": None,
        "color": "#71717A",
        "kind": "normal",
        "mode": "datetime",
        "weekly_weekday": None,
        "weekly_time": "",
        "alert": 0,
        "frequency": "weekly",
        "monthly_day": None,
    }
    row.update(values)
    return row


# L1 vence e rola; L2 tem ends_at no futuro; L3 e "datetime" done e nunca rola.
DEFAULT_LEGACY_ROWS = (
    _legacy_row(
        id="L1",
        title="Semanal vencido",
        ends_at="2026-10-03T11:00:00+00:00",
        mode="weekly",
        weekly_weekday=5,
        weekly_time="08:00",
        alert=1,
        created_at="2026-09-01 10:00:00",
        updated_at="2026-09-01 10:00:00",
    ),
    _legacy_row(
        id="L2",
        title="Mensal futuro",
        ends_at="2026-11-03T12:00:00+00:00",
        mode="monthly",
        monthly_day=3,
        weekly_time="09:00",
        frequency="monthly",
        created_at="2026-09-02 10:00:00",
        updated_at="2026-09-02 10:00:00",
    ),
    _legacy_row(
        id="L3",
        title="Data/hora finalizado",
        ends_at="2026-10-01T12:00:00+00:00",
        state="done",
        frequency="daily",
        created_at="2026-09-03 10:00:00",
        updated_at="2026-09-03 10:00:00",
    ),
)


def _make_legacy(path, rows=DEFAULT_LEGACY_ROWS, with_table=True):
    conn = sqlite3.connect(path)
    try:
        with conn:
            if not with_table:
                conn.execute("CREATE TABLE outra (x)")
            else:
                conn.execute(_LEGACY_DDL)
                placeholders = ", ".join("?" for _ in _LEGACY_COLUMNS)
                conn.executemany(
                    f"INSERT INTO clock_timers ({', '.join(_LEGACY_COLUMNS)}) VALUES ({placeholders})",
                    [tuple(row[name] for name in _LEGACY_COLUMNS) for row in rows],
                )
    finally:
        conn.close()
    return path


def _file_fingerprint(path) -> tuple[str, int]:
    return hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns


def _read_only(path) -> sqlite3.Connection:
    conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _rows_by_id(path, columns) -> dict:
    conn = _read_only(path)
    try:
        rows = conn.execute(f"SELECT {', '.join(columns)} FROM clock_timers").fetchall()
    finally:
        conn.close()
    return {row["id"]: tuple(row) for row in rows}


def _count(timers_store) -> int:
    return timers_store._conn.execute("SELECT count(*) FROM clock_timers").fetchone()[0]


def _timer(**overrides) -> ts.ClockTimer:
    values = {
        "id": f"t{next(_ids):03d}",
        "title": "Timer",
        "duration_seconds": 600,
        "remaining_seconds": 600,
        "ends_at": (NOW + timedelta(seconds=600)).isoformat(),
    }
    values.update(overrides)
    return ts.ClockTimer(**values)


# --- CRUD e frequency=daily -------------------------------------------------


def test_crud_banco_novo_vazio_e_criado_em_tmp_path(tmp_path, store):
    assert store.list_clock_timers() == []
    assert (tmp_path / "timers.db").is_file()
    assert not (tmp_path / "nao-usar").exists()


def test_crud_create_e_list_ida_e_volta_de_todos_os_campos(store):
    original = _timer(
        title="Revisar fila",
        duration_seconds=900,
        remaining_seconds=450,
        color="#22C55E",
        paused=True,
        paused_at="2026-10-03T11:55:00+00:00",
        mode="monthly",
        weekly_weekday=None,
        weekly_time="07:30",
        monthly_day=15,
        alert=True,
        frequency="monthly",
    )
    store.create_clock_timer(original)

    (got,) = store.list_clock_timers()

    assert got.created_at and got.updated_at
    assert got == dataclasses.replace(
        original, created_at=got.created_at, updated_at=got.updated_at
    )
    assert got.paused is True and got.alert is True
    assert isinstance(got.monthly_day, int) and got.weekly_weekday is None


def test_crud_weekly_weekday_volta_como_int(store):
    store.create_clock_timer(_timer(mode="weekly", weekly_weekday=2, weekly_time="10:00"))

    (got,) = store.list_clock_timers()

    assert got.weekly_weekday == 2 and isinstance(got.weekly_weekday, int)
    assert got.monthly_day is None
    assert got.paused is False and got.alert is False


def test_frequency_daily_persiste_com_daily_time(store):
    store.create_clock_timer(_timer(mode="daily", daily_time="08:00", frequency="daily"))

    (got,) = store.list_clock_timers()
    columns = {row[1] for row in store._conn.execute("PRAGMA table_info(clock_timers)")}

    assert got.frequency == "daily"
    assert got.mode == "daily"
    assert got.daily_time == "08:00"
    assert "daily_time" in columns


def test_crud_list_ordena_por_created_at_e_depois_id(store):
    store.create_clock_timer(_timer(id="b"))
    store.create_clock_timer(_timer(id="a"))
    with store._conn:
        store._conn.execute("UPDATE clock_timers SET created_at = '2026-01-01 00:00:00'")
    assert [t.id for t in store.list_clock_timers()] == ["a", "b"]

    with store._conn:
        store._conn.execute(
            "UPDATE clock_timers SET created_at = '2025-12-31 23:59:59' WHERE id = 'b'"
        )
    assert [t.id for t in store.list_clock_timers()] == ["b", "a"]


def test_crud_update_persiste_title_e_color(store):
    timer = _timer(title="Antes", color="#71717A")
    store.create_clock_timer(timer)

    store.update_clock_timer(dataclasses.replace(timer, title="Depois", color="#EF4444"))

    (got,) = store.list_clock_timers()
    assert (got.title, got.color) == ("Depois", "#EF4444")


def test_crud_update_de_id_inexistente_levanta(store):
    with pytest.raises(ts.ClockTimerNotFoundError):
        store.update_clock_timer(_timer(id="fantasma"))


def test_crud_create_com_id_repetido_levanta_e_avisa_em_stderr(store, capsys):
    store.create_clock_timer(_timer(id="dup"))
    capsys.readouterr()

    with pytest.raises(sqlite3.IntegrityError):
        store.create_clock_timer(_timer(id="dup"))

    assert "[timers-store] create_clock_timer" in capsys.readouterr().err
    assert len(store.list_clock_timers()) == 1


def test_crud_delete_remove_e_id_inexistente_nao_levanta(store):
    store.create_clock_timer(_timer(id="x"))
    store.create_clock_timer(_timer(id="y"))

    store.delete_clock_timer("x")
    store.delete_clock_timer("nao-existe")

    assert [t.id for t in store.list_clock_timers()] == ["y"]


def test_crud_get_meta_de_chave_ausente_devolve_none(store):
    assert store.get_meta("chave-ausente") is None


# --- Recorrencia pura -------------------------------------------------------


@pytest.mark.parametrize(
    ("daily_time", "now", "expected"),
    [
        ("08:00", NOW, "2026-10-04T11:00:00+00:00"),
        ("10:00", NOW, "2026-10-03T13:00:00+00:00"),
        ("09:00", NOW, "2026-10-04T12:00:00+00:00"),
        ("25:00", NOW, None),
        ("", NOW, None),
    ],
    ids=["ja-passou", "futuro-hoje", "igual-a-now", "hora-invalida", "vazio"],
)
def test_recorrencia_next_daily_occurrence(fixed_tz, daily_time, now, expected):
    assert ts._next_daily_occurrence(daily_time, now) == expected


@pytest.mark.parametrize(
    ("weekday", "time_text", "expected"),
    [
        (5, "08:00", "2026-10-10T11:00:00+00:00"),
        (5, "10:00", "2026-10-03T13:00:00+00:00"),
        (0, "08:00", "2026-10-05T11:00:00+00:00"),
        (5, "09:00", "2026-10-10T12:00:00+00:00"),
        (None, "08:00", None),
        (7, "08:00", None),
        (5, "25:00", None),
    ],
    ids=[
        "ja-passou",
        "futuro-hoje",
        "outro-dia",
        "igual-a-now",
        "weekday-none",
        "weekday-7",
        "hora-invalida",
    ],
)
def test_recorrencia_next_weekly_occurrence(fixed_tz, weekday, time_text, expected):
    assert ts._next_weekly_occurrence(weekday, time_text, NOW) == expected


@pytest.mark.parametrize(
    ("day", "time_text", "now", "expected"),
    [
        (3, "09:00", NOW, "2026-11-03T12:00:00+00:00"),
        (3, "10:00", NOW, "2026-10-03T13:00:00+00:00"),
        (2, "08:00", NOW, "2026-11-02T11:00:00+00:00"),
        (31, "08:00", NOW, "2026-10-31T11:00:00+00:00"),
        (
            31,
            "08:00",
            datetime(2026, 2, 10, 12, 0, tzinfo=timezone.utc),
            "2026-02-28T11:00:00+00:00",
        ),
        (0, "08:00", NOW, None),
        (32, "08:00", NOW, None),
        (None, "08:00", NOW, None),
        (3, "", NOW, None),
    ],
    ids=[
        "igual-a-now",
        "futuro-hoje",
        "ja-passou",
        "dia-31-mes-longo",
        "dia-31-fevereiro",
        "dia-0",
        "dia-32",
        "dia-none",
        "hora-vazia",
    ],
)
def test_recorrencia_next_monthly_occurrence(fixed_tz, day, time_text, now, expected):
    assert ts._next_monthly_occurrence(day, time_text, now) == expected


def test_recorrencia_next_fixed_occurrence_despacha_pelo_mode(fixed_tz):
    daily = _timer(mode="daily", daily_time="08:00", weekly_weekday=0, weekly_time="10:00")
    weekly = _timer(mode="weekly", weekly_weekday=0, weekly_time="08:00", daily_time="10:00")
    monthly = _timer(
        mode="monthly", monthly_day=31, weekly_time="08:00", weekly_weekday=5, daily_time="10:00"
    )

    assert ts._next_fixed_occurrence(daily, NOW) == "2026-10-04T11:00:00+00:00"
    assert ts._next_fixed_occurrence(weekly, NOW) == "2026-10-05T11:00:00+00:00"
    assert ts._next_fixed_occurrence(monthly, NOW) == "2026-10-31T11:00:00+00:00"


# --- Roll dos tres modos ----------------------------------------------------


def _due_timers() -> list[ts.ClockTimer]:
    past = (NOW - timedelta(hours=1)).isoformat()
    return [
        _timer(
            id="r-diario",
            mode="daily",
            daily_time="08:00",
            frequency="daily",
            ends_at=past,
            remaining_seconds=0,
            alert=True,
        ),
        _timer(
            id="r-semanal",
            mode="weekly",
            weekly_weekday=5,
            weekly_time="08:00",
            ends_at=past,
            remaining_seconds=0,
        ),
        _timer(
            id="r-mensal-done",
            mode="monthly",
            monthly_day=3,
            weekly_time="09:00",
            frequency="monthly",
            ends_at=past,
            remaining_seconds=0,
            state="done",
        ),
        _timer(
            id="r-semanal-pausado",
            mode="weekly",
            weekly_weekday=5,
            weekly_time="08:00",
            ends_at=past,
            remaining_seconds=0,
            paused=True,
            paused_at=past,
        ),
        _timer(id="r-datetime", mode="datetime", ends_at=past, remaining_seconds=0),
    ]


_ROLLED_ENDS_AT = {
    "r-diario": "2026-10-04T11:00:00+00:00",
    "r-semanal": "2026-10-10T11:00:00+00:00",
    "r-mensal-done": "2026-11-03T12:00:00+00:00",
}


def test_roll_tres_modos_reagenda_e_ignora_pausado_e_datetime(fixed_tz):
    timers = _due_timers()
    before = {t.id: copy.deepcopy(t) for t in timers}

    rolled = ts._roll_due_fixed_timers(timers, NOW)

    assert [t.id for t in rolled] == ["r-diario", "r-semanal", "r-mensal-done"]
    for timer in rolled:
        assert timer.ends_at == _ROLLED_ENDS_AT[timer.id]
        assert timer.state == "running"
        assert timer.paused is False
        assert timer.paused_at is None
        assert timer.alert is False
        remaining = ts._remaining_seconds(timer, NOW)
        assert remaining > 0
        assert timer.duration_seconds == timer.remaining_seconds == remaining
    by_id = {t.id: t for t in timers}
    assert by_id["r-semanal-pausado"] == before["r-semanal-pausado"]
    assert by_id["r-datetime"] == before["r-datetime"]
    assert all(t.state != "done" for t in rolled)


def test_roll_timer_fixo_com_ends_at_futuro_nao_rola(fixed_tz):
    timer = _timer(mode="daily", daily_time="08:00", state="running")
    before = copy.deepcopy(timer)

    assert ts._roll_due_fixed_timers([timer], NOW) == []
    assert timer == before


def test_roll_horario_invalido_nao_rola_nem_levanta(fixed_tz):
    timer = _timer(
        mode="weekly",
        weekly_weekday=5,
        weekly_time="xx",
        ends_at=(NOW - timedelta(hours=1)).isoformat(),
        remaining_seconds=0,
    )
    before = copy.deepcopy(timer)

    assert ts._roll_due_fixed_timers([timer], NOW) == []
    assert timer == before


def test_roll_store_persiste_e_segunda_chamada_nao_rola(fixed_tz, store):
    for timer in _due_timers():
        store.create_clock_timer(timer)

    rolled = store.roll_due_fixed_timers(NOW)

    assert sorted(t.id for t in rolled) == sorted(_ROLLED_ENDS_AT)
    persisted = {t.id: t for t in store.list_clock_timers()}
    for timer_id, ends_at in _ROLLED_ENDS_AT.items():
        assert persisted[timer_id].ends_at == ends_at
        assert persisted[timer_id].state == "running"
        assert persisted[timer_id].alert is False
    assert persisted["r-semanal-pausado"].paused is True
    assert persisted["r-datetime"].ends_at == (NOW - timedelta(hours=1)).isoformat()
    assert store.roll_due_fixed_timers(NOW) == []


# --- Ordenacao --------------------------------------------------------------


def test_ordenacao_menor_restante_primeiro_e_zerados_no_fim(fixed_tz):
    past = (NOW - timedelta(minutes=5)).isoformat()
    timers = [
        _timer(id="r300", ends_at=(NOW + timedelta(seconds=300)).isoformat()),
        _timer(id="b-zero", ends_at=past),
        _timer(id="r060", ends_at=(NOW + timedelta(seconds=60)).isoformat()),
        _timer(id="c-vazio", ends_at=""),
        _timer(id="p120", paused=True, remaining_seconds=120, ends_at=past),
        _timer(id="a-zero", ends_at=past),
    ]

    ordered = ts._sorted_timers(timers, NOW)

    assert [t.id for t in ordered] == ["r060", "p120", "r300", "a-zero", "b-zero", "c-vazio"]


def test_ordenacao_sort_key_de_zerado(fixed_tz):
    timer = _timer(id="z", ends_at=(NOW - timedelta(seconds=1)).isoformat())

    assert ts._sort_key(timer, NOW) == (1, 0, "z")
    assert ts._sort_key(_timer(id="v", ends_at=""), NOW) == (1, 0, "v")


# --- Importacao do legado e boot --------------------------------------------


def test_importacao_primeira_copia_tudo_sem_kind(fixed_tz, tmp_path, store):
    legacy = _make_legacy(tmp_path / "tasks.db")
    fingerprint = _file_fingerprint(legacy)

    result = store.import_legacy_once(legacy, NOW)

    assert result == ts.LegacyImportResult("imported", 3, 3)
    assert _count(store) == 3
    columns = {row[1] for row in store._conn.execute("PRAGMA table_info(clock_timers)")}
    assert "kind" not in columns
    assert _rows_by_id(store.db_path, ts._LEGACY_COPY_COLUMNS) == _rows_by_id(
        legacy, ts._LEGACY_COPY_COLUMNS
    )
    daily_times = [
        row[0] for row in store._conn.execute("SELECT daily_time FROM clock_timers")
    ]
    assert daily_times == ["", "", ""]
    assert [t.id for t in store.list_clock_timers()] == ["L1", "L2", "L3"]
    assert store.get_meta(ts.IMPORT_MARKER_KEY) == NOW.isoformat()
    assert _file_fingerprint(legacy) == fingerprint


def test_importacao_idempotente_nao_duplica_nem_sobrescreve(fixed_tz, tmp_path, store):
    legacy = _make_legacy(tmp_path / "tasks.db")
    fingerprint = _file_fingerprint(legacy)
    store.import_legacy_once(legacy, NOW)

    assert store.import_legacy_once(legacy, NOW).status == "already-imported"

    with store._conn:
        store._conn.execute("DELETE FROM meta WHERE key = ?", (ts.IMPORT_MARKER_KEY,))
    rolled = store.roll_due_fixed_timers(NOW)
    assert [t.id for t in rolled] == ["L1"]

    again = store.import_legacy_once(legacy, NOW)

    assert again == ts.LegacyImportResult("imported", 3, 0)
    assert _count(store) == 3
    by_id = {t.id: t for t in store.list_clock_timers()}
    assert by_id["L1"].ends_at == "2026-10-10T11:00:00+00:00"
    assert store.get_meta(ts.IMPORT_MARKER_KEY) == NOW.isoformat()
    assert _file_fingerprint(legacy) == fingerprint


def test_importacao_legado_ausente_grava_marcador(tmp_path, store):
    missing = tmp_path / "inexistente.db"

    result = store.import_legacy_once(missing, NOW)

    assert result.status == "no-legacy"
    assert store.get_meta(ts.IMPORT_MARKER_KEY) == NOW.isoformat()
    assert store.list_clock_timers() == []
    assert not missing.exists()


def test_importacao_rollback_em_violacao_de_constraint(tmp_path, store, capsys):
    rows = (
        DEFAULT_LEGACY_ROWS[0],
        _legacy_row(
            id="L-ruim",
            title="Estado fora do CHECK",
            ends_at="2026-10-03T11:00:00+00:00",
            state="paused",
            created_at="2026-09-04 10:00:00",
            updated_at="2026-09-04 10:00:00",
        ),
    )
    legacy = _make_legacy(tmp_path / "tasks.db", rows)
    fingerprint = _file_fingerprint(legacy)

    with pytest.raises(ts.LegacyImportError):
        store.import_legacy_once(legacy, NOW)

    assert _count(store) == 0
    assert store.get_meta(ts.IMPORT_MARKER_KEY) is None
    assert "[timers-store] import_legacy" in capsys.readouterr().err
    assert _file_fingerprint(legacy) == fingerprint


def test_importacao_rollback_em_legado_sem_tabela(tmp_path, store, capsys):
    legacy = _make_legacy(tmp_path / "tasks.db", with_table=False)
    fingerprint = _file_fingerprint(legacy)

    with pytest.raises(sqlite3.OperationalError):
        store.import_legacy_once(legacy, NOW)

    assert store.get_meta(ts.IMPORT_MARKER_KEY) is None
    assert store.list_clock_timers() == []
    assert "[timers-store] import_legacy" in capsys.readouterr().err
    assert _file_fingerprint(legacy) == fingerprint


def test_importacao_marcador_presente_nao_reabre_o_legado(tmp_path, store):
    store.import_legacy_once(tmp_path / "inexistente.db", NOW)
    not_a_db = tmp_path / "nao-e-banco.db"
    not_a_db.write_text("isto nao e um banco sqlite\n", encoding="utf-8")
    fingerprint = _file_fingerprint(not_a_db)

    result = store.import_legacy_once(not_a_db, NOW)

    assert result.status == "already-imported"
    assert _file_fingerprint(not_a_db) == fingerprint


def test_boot_importa_e_rola_sem_mensagem(fixed_tz, tmp_path):
    legacy = _make_legacy(tmp_path / "tasks.db")
    fingerprint = _file_fingerprint(legacy)

    timers_store, message = ts.boot_timers_store(tmp_path / "b.db", legacy, NOW)
    try:
        assert message is None
        assert timers_store is not None
        by_id = {t.id: t for t in timers_store.list_clock_timers()}
        assert sorted(by_id) == ["L1", "L2", "L3"]
        assert by_id["L1"].ends_at == "2026-10-10T11:00:00+00:00"
        assert by_id["L2"].ends_at == "2026-11-03T12:00:00+00:00"
        assert by_id["L3"].state == "done"
    finally:
        timers_store.close()
    assert _file_fingerprint(legacy) == fingerprint


def test_boot_com_falha_de_importacao_devolve_store_e_mensagem(fixed_tz, tmp_path):
    rows = (
        _legacy_row(
            id="L-ruim",
            title="Estado fora do CHECK",
            ends_at="2026-10-03T11:00:00+00:00",
            state="paused",
            created_at="2026-09-04 10:00:00",
            updated_at="2026-09-04 10:00:00",
        ),
    )
    legacy = _make_legacy(tmp_path / "tasks.db", rows)
    fingerprint = _file_fingerprint(legacy)

    timers_store, message = ts.boot_timers_store(tmp_path / "b.db", legacy, NOW)
    try:
        assert timers_store is not None
        assert message is not None and "import_legacy" in message
        assert timers_store.list_clock_timers() == []
        assert timers_store.get_meta(ts.IMPORT_MARKER_KEY) is None
    finally:
        timers_store.close()
    assert _file_fingerprint(legacy) == fingerprint


def test_boot_com_pasta_impossivel_devolve_none_e_mensagem(fixed_tz, tmp_path):
    blocker = tmp_path / "arquivo-comum"
    blocker.write_text("nao e pasta\n", encoding="utf-8")

    timers_store, message = ts.boot_timers_store(
        blocker / "b.db", tmp_path / "inexistente.db", NOW
    )

    assert timers_store is None
    assert message is not None and message.startswith("abrir ")


def test_fixture_legada_inalterada_apos_importar_reimportar_e_boot(fixed_tz, tmp_path):
    legacy = _make_legacy(tmp_path / "tasks.db")
    fingerprint = _file_fingerprint(legacy)

    first = ts.TimersStore(tmp_path / "um.db")
    try:
        assert first.import_legacy_once(legacy, NOW).status == "imported"
        assert first.import_legacy_once(legacy, NOW).status == "already-imported"
        with first._conn:
            first._conn.execute("DELETE FROM meta WHERE key = ?", (ts.IMPORT_MARKER_KEY,))
        assert first.import_legacy_once(legacy, NOW).inserted == 0
    finally:
        first.close()
    timers_store, message = ts.boot_timers_store(tmp_path / "dois.db", legacy, NOW)
    timers_store.close()

    assert message is None
    assert _file_fingerprint(legacy) == fingerprint
