"""Camada de dados dos timers do Forge Pick.

Copia (nunca import) da camada de timers do task-manager-desktop: modelo
``ClockTimer``, schema ``clock_timers`` e CRUD ``list/create/update/delete``.
Diferencas em relacao a origem:

- sem a coluna/campo ``kind`` (o Forge Pick tem um unico conjunto de timers);
- ``frequency`` aceita ``daily|weekly|monthly`` e ``mode`` aceita
  ``datetime|daily|weekly|monthly``, com a coluna nova ``daily_time`` (HH:MM);
- banco proprio em ``~/.local/share/forge-pick/timers.db`` (parametrizavel);
- recorrencia de horario fixo (diario, semanal, mensal) e ordenacao como
  funcoes puras com ``now`` injetavel, sem Qt;
- toda escrita roda em transacao e qualquer erro de banco e relancado ao
  chamador com uma linha ``[timers-store] ...`` em stderr;
- importacao unica do banco legado do task-manager-desktop (somente leitura,
  marcador na tabela ``meta``), ligada ao boot por ``boot_timers_store``.

O import deste modulo nao toca o disco: pasta e banco so sao criados quando
``TimersStore`` e instanciado.
"""

from __future__ import annotations

import calendar
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

DEFAULT_DB_PATH = Path.home() / ".local" / "share" / "forge-pick" / "timers.db"
# Origem da importacao unica (aberta somente leitura, nunca escrita).
LEGACY_DB_PATH = Path.home() / ".local" / "share" / "task-manager-desktop" / "tasks.db"
# Chave do marcador de importacao na tabela ``meta`` de ``timers.db``.
IMPORT_MARKER_KEY = "timers_imported_at"

# Valores de referencia para os itens de UI e recorrencia. Nao ha CHECK no banco
# (a origem tambem nao tem) e o store nao rejeita valores fora destas tuplas.
FREQUENCIES = ("daily", "weekly", "monthly")
MODES = ("datetime", "daily", "weekly", "monthly")


class ClockTimerNotFoundError(LookupError):
    """``update_clock_timer`` nao encontrou a linha do ``id`` informado."""


class LegacyImportError(sqlite3.DatabaseError):
    """O ``INSERT OR IGNORE`` descartaria linha do legado por constraint.

    ``OR IGNORE`` no SQLite pula em silencio tambem a linha que viola ``CHECK``
    ou ``NOT NULL``; a importacao so aceita o descarte por ``id`` repetido.
    """


@dataclass
class ClockTimer:
    id: str
    title: str
    duration_seconds: int = 0
    remaining_seconds: int = 0
    ends_at: str = ""
    color: str = "#71717A"
    state: str = "running"
    paused: bool = False
    paused_at: str | None = None
    # Modelo de agendamento, exclusivo entre si (radio do modal):
    # "datetime" = data/hora final + duracao (contagem unica, vira done no fim);
    # "daily"    = horario fixo diario (hora), recorrente: ao zerar, reinicia
    #              para a ocorrencia do dia seguinte e nunca entra em done
    #              (ver _next_daily_occurrence).
    # "weekly"   = horario fixo semanal (dia da semana + hora), recorrente: ao
    #              zerar, reinicia para a ocorrencia da semana seguinte e nunca
    #              entra em done.
    # "monthly"  = horario fixo mensal (dia do mes + hora), mesma recorrencia
    #              com passo de um mes.
    mode: str = "datetime"
    # Preenchidos apenas quando mode == "weekly". weekday segue a convencao de
    # datetime.weekday(): 0 = segunda ... 6 = domingo. weekly_time e "HH:MM"
    # em horario local.
    weekly_weekday: int | None = None
    weekly_time: str = ""
    # Preenchido apenas quando mode == "monthly": dia do mes (1..31). O horario
    # do modelo mensal reusa weekly_time ("HH:MM" local do horario fixo).
    monthly_day: int | None = None
    # Preenchido apenas quando mode == "daily": "HH:MM" em horario local.
    daily_time: str = ""
    # Estado do "semaforo" do card em andamento: False = bolinha verde e numeros
    # amarelos; True = bolinha vermelha e numeros vermelhos. Alternado no clique
    # da bolinha, sem relacao com o tempo restante.
    alert: bool = False
    # Frequencia de exibicao: "daily" (diaria), "weekly" (semanal) ou "monthly"
    # (mensal). Controla em qual secao da aba o card aparece. Default "weekly".
    frequency: str = "weekly"
    created_at: str = ""
    updated_at: str = ""


@dataclass
class LegacyImportResult:
    """Resultado observavel de ``TimersStore.import_legacy_once``.

    ``status``: ``"already-imported"`` (marcador presente, legado nao tocado),
    ``"no-legacy"`` (``tasks.db`` ausente, marcador gravado) ou ``"imported"``.
    """

    status: str
    legacy_rows: int = 0
    inserted: int = 0


# --- Schema de clock_timers -------------------------------------------------
# A tabela e criada sob demanda, entao o CREATE de banco novo e os ALTER de
# banco antigo precisam concordar. Para nao existirem duas listas de colunas
# para manter em sincronia, ambos saem DAQUI: coluna nova se declara em
# _CLOCK_TIMER_ADDITIVE_COLUMNS e mais nada precisa mudar.
_CLOCK_TIMER_BASE_DDL = (
    "id TEXT PRIMARY KEY",
    "title TEXT NOT NULL",
    "duration_seconds INTEGER NOT NULL CHECK(duration_seconds >= 0)",
    "remaining_seconds INTEGER NOT NULL CHECK(remaining_seconds >= 0)",
    "state TEXT NOT NULL CHECK(state IN ('running', 'done'))",
)

# (nome, tipo/default, constraint). O ADD COLUMN do SQLite nao aceita CHECK, por
# isso a constraint fica separada e vale so para bancos criados do zero.
_CLOCK_TIMER_ADDITIVE_COLUMNS = (
    ("ends_at", "TEXT NOT NULL DEFAULT ''", ""),
    ("color", "TEXT NOT NULL DEFAULT '#71717A'", ""),
    ("paused", "INTEGER NOT NULL DEFAULT 0", " CHECK(paused IN (0, 1))"),
    ("paused_at", "TEXT NULL", ""),
    # Timers pre-existentes sao todos de data/hora final -> 'datetime'.
    ("mode", "TEXT NOT NULL DEFAULT 'datetime'", ""),
    ("weekly_weekday", "INTEGER NULL", ""),
    ("weekly_time", "TEXT NOT NULL DEFAULT ''", ""),
    # Semaforo do card: 0 = bolinha verde (default), 1 = vermelha.
    ("alert", "INTEGER NOT NULL DEFAULT 0", " CHECK(alert IN (0, 1))"),
    # Frequencia de exibicao: "daily", "weekly" ou "monthly". Default "weekly".
    ("frequency", "TEXT NOT NULL DEFAULT 'weekly'", ""),
    # Dia do mes (1..31) do horario fixo mensal; NULL nos demais modos.
    ("monthly_day", "INTEGER NULL", ""),
    # "HH:MM" local do horario fixo diario; vazio nos demais modos.
    ("daily_time", "TEXT NOT NULL DEFAULT ''", ""),
)

_CLOCK_TIMER_TAIL_DDL = (
    "created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP",
    "updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP",
)


def _clock_timers_create_sql() -> str:
    columns = (
        *_CLOCK_TIMER_BASE_DDL,
        *(f"{name} {ddl}{check}" for name, ddl, check in _CLOCK_TIMER_ADDITIVE_COLUMNS),
        *_CLOCK_TIMER_TAIL_DDL,
    )
    return "CREATE TABLE IF NOT EXISTS clock_timers (\n  " + ",\n  ".join(columns) + "\n)"


def _row_to_clock_timer(row: sqlite3.Row) -> ClockTimer:
    ends_at = str(row["ends_at"] or "")
    remaining = int(row["remaining_seconds"] or 0)
    if not ends_at:
        ends_at = datetime.now(timezone.utc).isoformat()
    # row.keys() reconstroi a lista de colunas a cada chamada, e a lista inteira
    # pode ser relida a 1 Hz pela UI: resolve uma vez so.
    keys = set(row.keys())
    return ClockTimer(
        id=row["id"],
        title=row["title"],
        duration_seconds=int(row["duration_seconds"] or 0),
        remaining_seconds=remaining,
        ends_at=ends_at,
        color=str(row["color"] or "#71717A"),
        state=str(row["state"] or "running"),
        paused=bool(int(row["paused"] or 0)),
        paused_at=row["paused_at"],
        mode=(str(row["mode"]) if ("mode" in keys and row["mode"]) else "datetime"),
        weekly_weekday=(
            int(row["weekly_weekday"])
            if ("weekly_weekday" in keys and row["weekly_weekday"] is not None)
            else None
        ),
        weekly_time=(str(row["weekly_time"] or "") if "weekly_time" in keys else ""),
        monthly_day=(
            int(row["monthly_day"])
            if ("monthly_day" in keys and row["monthly_day"] is not None)
            else None
        ),
        daily_time=(str(row["daily_time"] or "") if "daily_time" in keys else ""),
        alert=bool(int(row["alert"] or 0)) if "alert" in keys else False,
        frequency=(str(row["frequency"]) if ("frequency" in keys and row["frequency"]) else "weekly"),
        created_at=str(row["created_at"] or ""),
        updated_at=str(row["updated_at"] or ""),
    )


# --- Recorrencia de horario fixo e ordenacao --------------------------------
# Copia (nunca import) dos metodos da ClockPane do task-manager-desktop, como
# funcoes puras de modulo. Toda funcao recebe ``now`` opcional (None = agora em
# UTC) e repassa o mesmo ``now`` as que chama, para que uma chamada nunca
# misture dois instantes. Nenhuma funcao daqui grava ``state = "done"``: o roll
# so escreve ``state = "running"``; a transicao de timer "datetime" para done e
# do tick.

# Modos de horario fixo recorrente: ao zerar, reiniciam na proxima ocorrencia.
_FIXED_MODES = ("daily", "weekly", "monthly")


def _normalize_mode(mode: str) -> str:
    return mode if mode in MODES else "datetime"


def _is_fixed_schedule(timer: ClockTimer) -> bool:
    return _normalize_mode(getattr(timer, "mode", "")) in _FIXED_MODES


def _parse_weekly_time(text: str) -> tuple[int, int] | None:
    """Converte "HH:MM" em (hora, minuto); None se invalido."""
    parts = str(text or "").strip().split(":")
    if len(parts) != 2:
        return None
    try:
        hour, minute = (int(part) for part in parts)
    except ValueError:
        return None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return hour, minute


def _next_weekly_occurrence(
    weekday: int | None, time_text: str, now: datetime | None = None
) -> str | None:
    """ISO UTC da proxima ocorrencia de ``weekday`` as ``time_text`` (local).

    ``weekday`` segue datetime.weekday() (0 = segunda ... 6 = domingo). O
    alvo e sempre estritamente futuro: cair exatamente sobre o horario atual
    agenda a semana seguinte, que e o comportamento de recorrencia desejado
    (o timer zera no horario e ja recomeca para a proxima semana).
    """
    parsed = _parse_weekly_time(time_text)
    if parsed is None or weekday is None or not (0 <= int(weekday) <= 6):
        return None
    hour, minute = parsed
    now_local = (now or datetime.now(timezone.utc)).astimezone()
    target = now_local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    target += timedelta(days=(int(weekday) - target.weekday()) % 7)
    if target <= now_local:
        target += timedelta(days=7)
    return target.astimezone(timezone.utc).isoformat()


def _next_monthly_occurrence(
    day: int | None, time_text: str, now: datetime | None = None
) -> str | None:
    """ISO UTC da proxima ocorrencia do dia ``day`` do mes as ``time_text``.

    ``day`` vai de 1 a 31; em meses mais curtos o alvo cai no ultimo dia do
    mes (dia 31 em fevereiro -> 28/29). Como no semanal, o alvo e sempre
    estritamente futuro.
    """
    parsed = _parse_weekly_time(time_text)
    if parsed is None or day is None or not (1 <= int(day) <= 31):
        return None
    hour, minute = parsed
    now_local = (now or datetime.now(timezone.utc)).astimezone()
    year, month = now_local.year, now_local.month
    for _ in range(2):
        last_day = calendar.monthrange(year, month)[1]
        target = now_local.replace(
            year=year,
            month=month,
            day=min(int(day), last_day),
            hour=hour,
            minute=minute,
            second=0,
            microsecond=0,
        )
        if target > now_local:
            return target.astimezone(timezone.utc).isoformat()
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return None


def _next_daily_occurrence(daily_time: str, now: datetime | None = None) -> str | None:
    """ISO UTC da proxima ocorrencia de ``daily_time`` ("HH:MM" local).

    Mesmo esqueleto do semanal, sem o passo de dia da semana. O alvo e sempre
    estritamente futuro: cair exatamente sobre o horario atual agenda o dia
    seguinte (o timer zera no horario e ja recomeca para amanha).
    """
    parsed = _parse_weekly_time(daily_time)
    if parsed is None:
        return None
    hour, minute = parsed
    now_local = (now or datetime.now(timezone.utc)).astimezone()
    target = now_local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now_local:
        target += timedelta(days=1)
    return target.astimezone(timezone.utc).isoformat()


def _next_fixed_occurrence(timer: ClockTimer, now: datetime | None = None) -> str | None:
    mode = _normalize_mode(getattr(timer, "mode", ""))
    time_text = getattr(timer, "weekly_time", "")
    if mode == "monthly":
        return _next_monthly_occurrence(getattr(timer, "monthly_day", None), time_text, now)
    if mode == "daily":
        return _next_daily_occurrence(getattr(timer, "daily_time", ""), now)
    return _next_weekly_occurrence(getattr(timer, "weekly_weekday", None), time_text, now)


def _parse_iso(value: str) -> datetime | None:
    if not value:
        return None
    # Python 3.10 fromisoformat rejeita o sufixo "Z" gerado pelo Qt ISODate.
    normalized = value.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _seconds_until_iso(value: str, now: datetime | None = None) -> int:
    end = _parse_iso(value)
    if end is None:
        return 0
    now = now or datetime.now(timezone.utc)
    return max(0, int((end - now).total_seconds()))


def _remaining_seconds(timer: ClockTimer, now: datetime | None = None) -> int:
    if timer.paused:
        return max(0, int(timer.remaining_seconds))
    return _seconds_until_iso(timer.ends_at, now)


def _reset_alert(timer: ClockTimer) -> None:
    """Devolve o semaforo do card ao verde (estado default).

    Verde e o estado de nascimento de todo timer; o vermelho so existe
    enquanto alguem o ligou no clique da bolinha. Zerar e recomecar (roll
    semanal, +1h de um card finalizado) apaga esse sinal manual: ele se
    referia ao ciclo que acabou de terminar, nao ao que comeca agora.
    """
    timer.alert = False


def _roll_fixed_timer(timer: ClockTimer, now: datetime | None = None) -> bool:
    """Reagenda um timer de horario fixo zerado para a proxima ocorrencia.

    Retorna True se reagendou. Timer de horario fixo (diario, semanal ou
    mensal) nunca vira "done": ele volta a contar assim que cruza o horario.
    Todo recomeco reseta o semaforo para verde (ver _reset_alert).
    """
    now = now or datetime.now(timezone.utc)
    ends_at = _next_fixed_occurrence(timer, now)
    if ends_at is None:
        return False
    remaining = _seconds_until_iso(ends_at, now)
    timer.ends_at = ends_at
    timer.duration_seconds = remaining
    timer.remaining_seconds = remaining
    timer.state = "running"
    timer.paused = False
    timer.paused_at = None
    _reset_alert(timer)
    return True


def _roll_due_fixed_timers(
    timers: list[ClockTimer], now: datetime | None = None
) -> list[ClockTimer]:
    """Reagenda os timers de horario fixo vencidos e devolve os alterados.

    Ponto unico da condicao "fixo, nao pausado, zerado", chamado apos a
    importacao do banco legado e pelo tick de 1 Hz. Muta os timers em memoria
    e nao persiste nada (ver ``TimersStore.roll_due_fixed_timers``). Pausados,
    timers "datetime" e fixos com horario invalido ficam intactos e fora da
    lista devolvida.
    """
    now = now or datetime.now(timezone.utc)
    rolled: list[ClockTimer] = []
    for timer in timers:
        if timer.paused or not _is_fixed_schedule(timer):
            continue
        if _remaining_seconds(timer, now) > 0 and timer.state != "done":
            continue
        if _roll_fixed_timer(timer, now):
            rolled.append(timer)
    return rolled


def _sort_key(timer: ClockTimer, now: datetime | None = None) -> tuple[int, int, str]:
    remaining = _remaining_seconds(timer, now)
    done = remaining <= 0
    # Zerados: primeiro campo 1 (bloco final) e tempo neutralizado, para nao
    # influenciar a posicao dentro do proprio bloco.
    return (1, 0, timer.id) if done else (0, remaining, timer.id)


def _sorted_timers(timers: list[ClockTimer], now: datetime | None = None) -> list[ClockTimer]:
    """Timers ordenados por tempo restante.

    Cards zerados saem da contagem de posicionamento e vao para o fim da
    fila: a ordenacao por menor tempo restante vale apenas entre os timers
    em andamento. Entre os zerados, o desempate e so pelo id (estavel).
    """
    now = now or datetime.now(timezone.utc)
    return sorted(timers, key=lambda timer: _sort_key(timer, now))


# --- Importacao unica do banco legado ---------------------------------------
# Colunas copiadas cruas do ``clock_timers`` do legado, na ordem do INSERT.
# ``kind`` fica de fora por construcao; ``daily_time`` nao existe no legado e
# recebe o default ``''`` da coluna.
_LEGACY_COPY_COLUMNS = (
    "id",
    "title",
    "duration_seconds",
    "remaining_seconds",
    "ends_at",
    "color",
    "state",
    "paused",
    "paused_at",
    "mode",
    "weekly_weekday",
    "weekly_time",
    "alert",
    "frequency",
    "monthly_day",
    "created_at",
    "updated_at",
)


class TimersStore:
    """Persistencia dos timers do Forge Pick em SQLite.

    ``db_path=None`` usa ``DEFAULT_DB_PATH``; testes passam um caminho proprio.
    A pasta do banco e criada se ausente.
    """

    def __init__(self, db_path: Path | str | None = None) -> None:
        self.db_path: Path = Path(db_path) if db_path is not None else DEFAULT_DB_PATH
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self.db_path)
        except (OSError, sqlite3.Error) as exc:
            print(f"[timers-store] falha ao abrir {self.db_path}: {exc}", file=sys.stderr)
            raise
        self._conn.row_factory = sqlite3.Row
        self._clock_timer_table_ready = False
        self._meta_table_ready = False

    def _fail(self, operation: str, exc: Exception) -> None:
        print(f"[timers-store] {operation} falhou em {self.db_path}: {exc}", file=sys.stderr)

    def _ensure_clock_timers_table(self) -> None:
        if self._clock_timer_table_ready:
            return
        try:
            with self._conn:
                self._conn.execute(_clock_timers_create_sql())
                cols = {row[1] for row in self._conn.execute("PRAGMA table_info(clock_timers)")}
                for name, ddl, _check in _CLOCK_TIMER_ADDITIVE_COLUMNS:
                    if name in cols:
                        continue
                    self._conn.execute(f"ALTER TABLE clock_timers ADD COLUMN {name} {ddl}")
                self._conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_clock_timers_state ON clock_timers(state)"
                )
        except sqlite3.Error as exc:
            self._fail("ensure clock_timers", exc)
            raise
        self._clock_timer_table_ready = True

    def _ensure_meta_table(self) -> None:
        if self._meta_table_ready:
            return
        try:
            with self._conn:
                self._conn.execute(
                    "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
                )
        except sqlite3.Error as exc:
            self._fail("ensure meta", exc)
            raise
        self._meta_table_ready = True

    def get_meta(self, key: str) -> str | None:
        self._ensure_meta_table()
        try:
            row = self._conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        except sqlite3.Error as exc:
            self._fail("get_meta", exc)
            raise
        return None if row is None else str(row["value"])

    def _set_meta(self, key: str, value: str) -> None:
        self._ensure_meta_table()
        try:
            with self._conn:
                self._conn.execute(
                    "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value)
                )
        except sqlite3.Error as exc:
            self._fail("set_meta", exc)
            raise

    def import_legacy_once(
        self, legacy_path: Path | str | None = None, now: datetime | None = None
    ) -> LegacyImportResult:
        """Copia uma unica vez os ``clock_timers`` do banco legado.

        Com marcador presente, devolve ``"already-imported"`` sem tocar o
        legado. Sem ``tasks.db``, grava o marcador e devolve ``"no-legacy"``.
        Senao le o legado somente leitura (``mode=ro``), insere tudo numa
        transacao com ``INSERT OR IGNORE`` por ``id`` (sem ``kind``) e grava o
        marcador so depois do commit. Qualquer falha reverte a importacao, sai
        em stderr, e relancada e nao grava marcador (o proximo boot tenta de
        novo). Queda entre o commit e o marcador e segura: a reimportacao nao
        duplica nem sobrescreve, porque o ``id`` ja existente e ignorado.
        """
        legacy = Path(legacy_path) if legacy_path is not None else LEGACY_DB_PATH
        if self.get_meta(IMPORT_MARKER_KEY):
            return LegacyImportResult("already-imported")
        instant = (now or datetime.now(timezone.utc)).isoformat()
        if not legacy.is_file():
            self._set_meta(IMPORT_MARKER_KEY, instant)
            return LegacyImportResult("no-legacy")

        columns = ", ".join(_LEGACY_COPY_COLUMNS)
        conn = None
        try:
            uri = legacy.resolve().as_uri() + "?mode=ro"
            conn = sqlite3.connect(uri, uri=True)
            conn.row_factory = sqlite3.Row
            legacy_rows = conn.execute(f"SELECT {columns} FROM clock_timers").fetchall()
        except sqlite3.Error as exc:
            self._fail("import_legacy (leitura)", exc)
            raise
        finally:
            if conn is not None:
                conn.close()

        rows = [tuple(row[name] for name in _LEGACY_COPY_COLUMNS) for row in legacy_rows]
        total = len(rows)
        self._ensure_clock_timers_table()
        placeholders = ", ".join("?" for _ in _LEGACY_COPY_COLUMNS)
        try:
            with self._conn:
                # BEGIN explicito: a contagem e o insert vivem na mesma transacao.
                self._conn.execute("BEGIN")
                existing = sum(
                    1
                    for row in rows
                    if self._conn.execute(
                        "SELECT 1 FROM clock_timers WHERE id = ?", (row[0],)
                    ).fetchone()
                )
                inserted = 0
                if rows:
                    cursor = self._conn.executemany(
                        f"INSERT OR IGNORE INTO clock_timers ({columns}) VALUES ({placeholders})",
                        rows,
                    )
                    inserted = cursor.rowcount
                rejected = (total - existing) - inserted
                if rejected != 0:
                    raise LegacyImportError(
                        f"{rejected} linha(s) do legado rejeitada(s) por constraint"
                    )
        except sqlite3.Error as exc:
            self._fail("import_legacy", exc)
            raise

        self._set_meta(IMPORT_MARKER_KEY, instant)
        print(
            f"[timers-store] importacao do legado: {inserted} de {total} linhas inseridas",
            file=sys.stderr,
        )
        return LegacyImportResult("imported", total, inserted)

    def list_clock_timers(self) -> list[ClockTimer]:
        self._ensure_clock_timers_table()
        try:
            rows = self._conn.execute(
                "SELECT * FROM clock_timers ORDER BY created_at ASC, id ASC"
            ).fetchall()
        except sqlite3.Error as exc:
            self._fail("list_clock_timers", exc)
            raise
        return [_row_to_clock_timer(row) for row in rows]

    def create_clock_timer(self, timer: ClockTimer) -> None:
        self._ensure_clock_timers_table()
        try:
            with self._conn:
                self._conn.execute(
                    """
                    INSERT INTO clock_timers
                        (id, title, duration_seconds, remaining_seconds, ends_at, color, state, paused, paused_at,
                         mode, weekly_weekday, weekly_time, alert, frequency, monthly_day, daily_time)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        timer.id,
                        timer.title,
                        int(timer.duration_seconds),
                        int(timer.remaining_seconds),
                        timer.ends_at,
                        timer.color,
                        timer.state,
                        1 if timer.paused else 0,
                        timer.paused_at,
                        timer.mode or "datetime",
                        timer.weekly_weekday,
                        timer.weekly_time or "",
                        1 if timer.alert else 0,
                        timer.frequency or "weekly",
                        timer.monthly_day,
                        timer.daily_time or "",
                    ),
                )
        except sqlite3.Error as exc:
            self._fail("create_clock_timer", exc)
            raise

    def _update_clock_timer_row(self, timer: ClockTimer) -> int:
        """Executa o UPDATE de ``timer`` e devolve o rowcount.

        Nao abre transacao nem trata erro: o chamador faz as duas coisas.
        """
        cursor = self._conn.execute(
            """
            UPDATE clock_timers
            SET title = ?, duration_seconds = ?, remaining_seconds = ?, ends_at = ?, color = ?,
                state = ?, paused = ?, paused_at = ?,
                mode = ?, weekly_weekday = ?, weekly_time = ?, alert = ?, frequency = ?,
                monthly_day = ?, daily_time = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                timer.title,
                int(timer.duration_seconds),
                int(timer.remaining_seconds),
                timer.ends_at,
                timer.color,
                timer.state,
                1 if timer.paused else 0,
                timer.paused_at,
                timer.mode or "datetime",
                timer.weekly_weekday,
                timer.weekly_time or "",
                1 if timer.alert else 0,
                timer.frequency or "weekly",
                timer.monthly_day,
                timer.daily_time or "",
                timer.id,
            ),
        )
        return cursor.rowcount

    def update_clock_timer(self, timer: ClockTimer) -> None:
        self._ensure_clock_timers_table()
        try:
            with self._conn:
                rowcount = self._update_clock_timer_row(timer)
        except sqlite3.Error as exc:
            self._fail("update_clock_timer", exc)
            raise
        if rowcount == 0:
            raise ClockTimerNotFoundError(f"ClockTimer {timer.id!r} nao encontrado")

    def roll_due_fixed_timers(self, now: datetime | None = None) -> list[ClockTimer]:
        """Reagenda e persiste os timers de horario fixo vencidos.

        Chamado apos a importacao do banco legado e pelo tick. Todos os timers
        rolados sao gravados numa unica transacao; nada venceu = nenhuma
        escrita. Erro de banco vai para stderr e e relancado (a origem engolia
        a falha; aqui a UI decide a mensagem). Timer apagado entre a leitura e
        a escrita levanta ``ClockTimerNotFoundError`` e reverte a transacao.
        """
        timers = self.list_clock_timers()
        rolled = _roll_due_fixed_timers(timers, now)
        if not rolled:
            return []
        try:
            with self._conn:
                for timer in rolled:
                    if self._update_clock_timer_row(timer) == 0:
                        raise ClockTimerNotFoundError(f"ClockTimer {timer.id!r} nao encontrado")
        except sqlite3.Error as exc:
            self._fail("roll_due_fixed_timers", exc)
            raise
        return rolled

    def delete_clock_timer(self, timer_id: str) -> None:
        self._ensure_clock_timers_table()
        try:
            with self._conn:
                self._conn.execute("DELETE FROM clock_timers WHERE id = ?", (timer_id,))
        except sqlite3.Error as exc:
            self._fail("delete_clock_timer", exc)
            raise

    def close(self) -> None:
        self._conn.close()


def boot_timers_store(
    db_path: Path | str | None = None,
    legacy_path: Path | str | None = None,
    now: datetime | None = None,
) -> tuple[TimersStore | None, str | None]:
    """Abre o store, importa o legado uma vez e rola os timers vencidos.

    Ponto unico chamado no boot do ``app.py``. Nunca levanta: cada etapa
    (abrir, importar, rolar) captura ``sqlite3.Error``, ``OSError`` e
    ``ClockTimerNotFoundError`` e devolve ``(store ou None, mensagem)``, com
    ``None`` na mensagem quando tudo deu certo. O roll roda em todo boot,
    inclusive quando a importacao falhou, espelhando o painel de origem, que
    rola os timers vencidos ao montar. O log em stderr ja saiu por ``_fail``.
    """
    target = Path(db_path) if db_path is not None else DEFAULT_DB_PATH
    try:
        store = TimersStore(target)
    except (sqlite3.Error, OSError) as exc:
        return None, f"abrir {target}: {exc}"
    errors: list[str] = []
    try:
        store.import_legacy_once(legacy_path, now)
    except (sqlite3.Error, OSError, ClockTimerNotFoundError) as exc:
        errors.append(f"import_legacy: {exc}")
    try:
        store.roll_due_fixed_timers(now)
    except (sqlite3.Error, OSError, ClockTimerNotFoundError) as exc:
        errors.append(f"roll_due_fixed_timers: {exc}")
    return store, "; ".join(errors) or None
