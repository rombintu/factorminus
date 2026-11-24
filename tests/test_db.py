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
    assert migrate(conn) == [1]
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
