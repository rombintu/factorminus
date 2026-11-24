import pytest

from factorminus.db import candle_ranges, connect, migrate, table_counts

TABLES = {
    "schema_migrations",
    "instruments",
    "assets",
    "brands",
    "candles",
    "index_weights",
    "ingest_runs",
    "ingest_errors",
}


def test_migrate_idempotent(tmp_path):
    conn = connect(tmp_path / "sub" / "fm.sqlite")
    assert migrate(conn) == [1, 2]
    assert migrate(conn) == []
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert TABLES <= names


def test_migrations_applied_in_order(tmp_path):
    mig = tmp_path / "migs"
    mig.mkdir()
    (mig / "002_b.sql").write_text("CREATE TABLE b(x INTEGER);", encoding="utf-8")
    (mig / "001_a.sql").write_text("CREATE TABLE a(x INTEGER);", encoding="utf-8")
    (mig / "readme.txt").write_text("not a migration", encoding="utf-8")
    conn = connect(tmp_path / "fm.sqlite")
    assert migrate(conn, migrations_dir=mig) == [1, 2]
    (mig / "003_c.sql").write_text("CREATE TABLE c(x INTEGER);", encoding="utf-8")
    assert migrate(conn, migrations_dir=mig) == [3]


def test_failed_migration_rolls_back(tmp_path):
    mig = tmp_path / "migs"
    mig.mkdir()
    (mig / "001_bad.sql").write_text("CREATE TABLE ok(x); CREATE TABLE ok(x);", encoding="utf-8")
    conn = connect(tmp_path / "fm.sqlite")
    try:
        migrate(conn, migrations_dir=mig)
    except Exception:
        pass
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "ok" not in names


def test_stats(tmp_path):
    conn = connect(tmp_path / "fm.sqlite")
    migrate(conn)
    conn.executemany(
        "INSERT INTO candles(instrument_id, date, close) VALUES (?,?,?)",
        [("A", "2024-01-02", 1), ("A", "2024-01-05", 1), ("B", "2024-02-01", 2)],
    )
    counts = table_counts(conn)
    assert counts["candles"] == 3
    assert counts["instruments"] == 0
    r = candle_ranges(conn)
    assert r == {"instruments": 2, "min_date": "2024-01-02", "max_date": "2024-02-01"}


def _seed_index(conn):
    from factorminus.db import now_iso

    rows = [
        ("SBER_TQBR", "SBER", "TQBR"),
        ("SBERP_TQBR", "SBERP", "TQBR"),
        ("SBER_SPBRU", "SBER", "SPBRU"),
        ("SYN_OIL1", "SYN_OIL1", "SYN"),
    ]
    for iid, t, cls in rows:
        conn.execute(
            "INSERT INTO instruments(instrument_id, ticker, class_code, kind, raw_json, source, "
            "updated_at) VALUES (?, ?, ?, 'share', '{}', 't', ?)",
            (iid, t, cls, now_iso()),
        )
    conn.executemany(
        "INSERT INTO index_weights(index_id, trade_date, ticker, weight) VALUES (?, ?, ?, ?)",
        [
            ("IMOEX", "2026-11-20", "SBER", 50.0),
            ("IMOEX", "2026-11-20", "SBERP", 30.0),
            ("IMOEX", "2026-11-20", "CBOM", 20.0),
            ("IMOEX", "2026-01-01", "OLD", 100.0),
            ("SYNIDX", "2025-10-01", "SYN_OIL1", 100.0),
        ],
    )


def test_index_ticker_mapping_prefers_tqbr(tmp_path):
    from factorminus.db import index_coverage, map_index_tickers

    conn = connect(tmp_path / "fm.sqlite")
    migrate(conn)
    _seed_index(conn)
    assert map_index_tickers(conn, "IMOEX") == {
        "SBER": "SBER_TQBR",
        "SBERP": "SBERP_TQBR",
        "CBOM": None,
    }
    assert map_index_tickers(conn, "SYNIDX") == {"SYN_OIL1": "SYN_OIL1"}
    cov = index_coverage(conn, "IMOEX")
    assert cov == {"trade_date": "2026-11-20", "coverage_pct": 80.0, "missing": ["CBOM"]}


def test_quality_stats(tmp_path):
    from factorminus.db import now_iso, quality_stats

    conn = connect(tmp_path / "fm.sqlite")
    migrate(conn)
    conn.execute(
        "INSERT INTO brands(brand_uid, sector, raw_json, updated_at) "
        "VALUES ('b1', 'energy', '{}', ?), ('b2', NULL, '{}', ?)",
        (now_iso(), now_iso()),
    )
    for iid, b in [("A_X", "b1"), ("B_X", "b2"), ("C_X", None)]:
        conn.execute(
            "INSERT INTO instruments(instrument_id, ticker, class_code, kind, brand_uid, raw_json, "
            "source, updated_at) VALUES (?, ?, 'X', 'share', ?, '{}', 't', ?)",
            (iid, iid, b, now_iso()),
        )
    conn.executemany(
        "INSERT INTO candles(instrument_id, date, close) VALUES (?, ?, 1)",
        [("A_X", "2026-11-20"), ("A_X", "2026-11-21"), ("A_X", "2026-11-22")],
    )
    q = quality_stats(conn)
    assert q["weekend_candles"] == 2  # 21 и 22 ноября 2026 — суббота и воскресенье
    assert q["without_sector"] == ["B_X", "C_X"]
    assert q["without_sector_pct"] == pytest.approx(66.7, abs=0.1)
