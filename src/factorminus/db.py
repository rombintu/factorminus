"""SQLite: одна база data/fm.sqlite, реальные и синтетические данные в одних таблицах."""

import sqlite3
from pathlib import Path

SCHEMA = Path(__file__).with_name("schema.sql")
# Ключевая колонка таблицы: по префиксу SYN отличаем синтетику от реальных данных.
KEYS = {
    "instruments": "id",
    "brands": "uid",
    "candles": "instrument_id",
    "index_weights": "ticker",
}


def connect(path) -> sqlite3.Connection:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA.read_text())
    return conn


def upsert(conn: sqlite3.Connection, table: str, row: dict) -> None:
    cols = ", ".join(row)
    marks = ", ".join("?" * len(row))
    # Пустое новое значение не затирает старое: uid и ставки риска приходят отдельным вызовом.
    keep = ", ".join(f"{c} = coalesce(excluded.{c}, {c})" for c in row)
    sql = f"INSERT INTO {table} ({cols}) VALUES ({marks}) ON CONFLICT DO UPDATE SET {keep}"
    conn.execute(sql, list(row.values()))


def market_id(conn: sqlite3.Connection, index_id: str) -> str | None:
    """Рынок для индекса: строка instruments с kind='index' и этим index_id."""
    sql = "SELECT id FROM instruments WHERE kind = 'index' AND index_id = ?"
    row = conn.execute(sql, (index_id,)).fetchone()
    return row[0] if row else None


def index_members(conn: sqlite3.Connection, index_id: str) -> tuple[str | None, list[tuple]]:
    """Веса на последнюю дату: (дата, [(instrument_id или None, ticker, weight)]).

    Вес сопоставляется с акцией по instruments.ticker; бумаги нет во вселенной — None.
    """
    day = conn.execute(
        "SELECT max(date) FROM index_weights WHERE index_id = ?", (index_id,)
    ).fetchone()[0]
    rows = conn.execute(
        "SELECT i.id, w.ticker, w.weight FROM index_weights w "
        "LEFT JOIN instruments i ON i.ticker = w.ticker AND i.kind = 'share' "
        "WHERE w.index_id = ? AND w.date = ? ORDER BY w.weight DESC",
        (index_id, day),
    )
    return day, [tuple(r) for r in rows]


def stats(conn: sqlite3.Connection) -> list[str]:
    """Строки по таблицам отдельно для real и synth, диапазон дат свечей и весов."""
    lines = []
    for table, key in KEYS.items():
        has_date = table in ("candles", "index_weights")
        dates = "min(date), max(date)" if has_date else "NULL, NULL"
        sql = (
            f"SELECT CASE WHEN {key} LIKE 'SYN\\_%' ESCAPE '\\' THEN 'synth' ELSE 'real' END AS src, "
            f"count(*), {dates} FROM {table} GROUP BY src ORDER BY src"
        )
        rows = conn.execute(sql).fetchall() or [("-", 0, None, None)]
        for src, n, lo, hi in rows:
            span = f"  {lo} … {hi}" if lo else ""
            lines.append(f"{table:<14} {src:<6} {n:>8}{span}")
    markets = conn.execute(
        "SELECT i.id, count(c.date), min(c.date), max(c.date) FROM instruments i "
        "LEFT JOIN candles c ON c.instrument_id = i.id WHERE i.kind = 'index' GROUP BY i.id"
    )
    for iid, n, lo, hi in markets:
        lines.append(f"рынок {iid:<14} {n:>8}  {lo} … {hi}")
    return lines
