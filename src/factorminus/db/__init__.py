"""SQLite: подключение и миграции `migrations/NNN_*.sql`."""

from __future__ import annotations

import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).with_name("migrations")
_MIG_RE = re.compile(r"^(\d{3})_.+\.sql$")


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def connect(path: Path | str) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None)  # транзакции управляются явно
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _migrations(migrations_dir: Path) -> list[tuple[int, Path]]:
    out = []
    for p in migrations_dir.iterdir():
        m = _MIG_RE.match(p.name)
        if m:
            out.append((int(m.group(1)), p))
    return sorted(out)


def migrate(conn: sqlite3.Connection, migrations_dir: Path | None = None) -> list[int]:
    """Применяет новые миграции по порядку, каждую в своей транзакции. Возвращает их версии."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations"
        "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    done = {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}
    applied = []
    for version, path in _migrations(migrations_dir or MIGRATIONS_DIR):
        if version in done:
            continue
        sql = path.read_text(encoding="utf-8")
        conn.execute("BEGIN")
        try:
            for stmt in _split_sql(sql):
                conn.execute(stmt)
            conn.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (version, now_iso()),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        applied.append(version)
    return applied


def _split_sql(sql: str) -> list[str]:
    """Делит скрипт на операторы (executescript делает неявный COMMIT, он не подходит)."""
    lines = [ln for ln in sql.splitlines() if not ln.strip().startswith("--")]
    stmts, buf = [], ""
    for line in lines:
        buf += line + "\n"
        if sqlite3.complete_statement(buf):
            if buf.strip():
                stmts.append(buf.strip())
            buf = ""
    if buf.strip():
        stmts.append(buf.strip())
    return stmts


def table_counts(conn: sqlite3.Connection) -> dict[str, int]:
    names = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
            "ORDER BY name"
        )
    ]
    return {n: conn.execute(f'SELECT COUNT(*) FROM "{n}"').fetchone()[0] for n in names}


def candle_ranges(conn: sqlite3.Connection) -> dict:
    r = conn.execute(
        "SELECT COUNT(DISTINCT instrument_id), MIN(date), MAX(date) FROM candles"
    ).fetchone()
    return {"instruments": r[0], "min_date": r[1], "max_date": r[2]}


def issuer_summary(conn: sqlite3.Connection) -> dict:
    """Число различных эмитентов и бумаги без эмитента."""
    n = conn.execute(
        "SELECT COUNT(DISTINCT issuer_key) FROM instruments WHERE issuer_key IS NOT NULL"
    ).fetchone()[0]
    missing = [
        r[0]
        for r in conn.execute(
            "SELECT instrument_id FROM instruments WHERE issuer_key IS NULL "
            "AND kind != 'index' ORDER BY instrument_id"
        )
    ]
    return {"issuers": n, "without_issuer": missing}


def latest_weights_date(conn: sqlite3.Connection, index_id: str) -> str | None:
    return conn.execute(
        "SELECT MAX(trade_date) FROM index_weights WHERE index_id=?", (index_id,)
    ).fetchone()[0]


def map_index_tickers(conn: sqlite3.Connection, index_id: str) -> dict[str, str | None]:
    """Тикер из весов индекса (SBER) → instrument_id вселенной (SBER_TQBR) на последнюю дату.

    Сначала ищется класс TQBR, затем точное совпадение тикера в любом классе
    (синтетика: тикер = SYN_*). Нет в базе — None.
    """
    d = latest_weights_date(conn, index_id)
    out: dict[str, str | None] = {}
    for (ticker,) in conn.execute(
        "SELECT ticker FROM index_weights WHERE index_id=? AND trade_date=? ORDER BY weight DESC",
        (index_id, d),
    ):
        row = conn.execute(
            "SELECT instrument_id FROM instruments WHERE ticker=? AND kind != 'index' "
            "ORDER BY class_code != 'TQBR', instrument_id LIMIT 1",
            (ticker,),
        ).fetchone()
        out[ticker] = row[0] if row else None
    return out


def index_coverage(conn: sqlite3.Connection, index_id: str) -> dict:
    """Доля веса индекса (на последнюю дату), чьи бумаги есть во вселенной."""
    d = latest_weights_date(conn, index_id)
    weights = dict(
        conn.execute(
            "SELECT ticker, weight FROM index_weights WHERE index_id=? AND trade_date=?",
            (index_id, d),
        ).fetchall()
    )
    mapping = map_index_tickers(conn, index_id)
    total = sum(weights.values()) or 1.0
    covered = sum(w for t, w in weights.items() if mapping.get(t))
    return {
        "trade_date": d,
        "coverage_pct": round(covered / total * 100, 2),
        "missing": sorted(t for t, iid in mapping.items() if iid is None),
    }


def quality_stats(conn: sqlite3.Connection) -> dict:
    """Быстрая проверка качества данных после загрузки."""
    weekend = conn.execute(
        "SELECT COUNT(*) FROM candles WHERE strftime('%w', date) IN ('0', '6')"
    ).fetchone()[0]
    rows = conn.execute(
        "SELECT i.instrument_id, b.sector FROM instruments i LEFT JOIN brands b USING(brand_uid) "
        "WHERE i.kind != 'index' ORDER BY i.instrument_id"
    ).fetchall()
    without = [r[0] for r in rows if not r[1]]
    return {
        "weekend_candles": weekend,
        "without_sector": without,
        "without_sector_pct": round(len(without) / len(rows) * 100, 1) if rows else 0.0,
    }
