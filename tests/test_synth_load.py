"""Сквозной тест загрузки: синтетические кассеты → конвейер (replay) → SQLite. Без сети."""

import csv
import json
import shutil
from pathlib import Path

from factorminus.db import connect, table_counts
from factorminus.synth.load import load_synth

FIXTURES = Path(__file__).parent / "fixtures" / "synthetic"


def test_replay_fills_db_without_errors(tmp_path):
    db = tmp_path / "synth.sqlite"
    s = load_synth(db, FIXTURES)
    assert s.errors == 0
    with open(FIXTURES / "candles.csv", encoding="utf-8") as f:
        n_candles = sum(1 for _ in csv.DictReader(f))
    conn = connect(db)
    counts = table_counts(conn)
    assert counts["candles"] == n_candles
    assert counts["ingest_errors"] == 0
    assert counts["index_weights"] == 13
    universe_n = sum(
        1
        for ln in (FIXTURES / "universe.yaml").read_text(encoding="utf-8").splitlines()
        if ln.startswith("- id:")
    )
    assert counts["instruments"] == universe_n
    # бренд общий у обыкновенной и привилегированной акции
    brands = {r[0]: r[1] for r in conn.execute("SELECT instrument_id, brand_uid FROM instruments")}
    assert brands["SYN_BANK1"] == brands["SYN_BANK1P"]
    assert "SYN_ABSENT" not in brands
    sectors = conn.execute(
        "SELECT COUNT(*) FROM instruments i JOIN brands b USING(brand_uid) WHERE b.sector IS NULL"
    ).fetchone()[0]
    assert sectors == 0
    row = conn.execute(
        "SELECT maturity_date, uid FROM instruments WHERE instrument_id='SYN_OFZL'"
    ).fetchone()
    assert row[0] == "2041-05-15" and row[1] == "syn-uid-syn-ofzl"
    manifest = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))
    rng = conn.execute("SELECT MIN(date), MAX(date) FROM candles").fetchone()
    assert (rng[0], rng[1]) == (manifest["params"]["start"], manifest["params"]["end"])


def test_replay_rerun_is_idempotent(tmp_path):
    db = tmp_path / "synth.sqlite"
    load_synth(db, FIXTURES)
    before = table_counts(connect(db))
    s = load_synth(db, FIXTURES)
    after = table_counts(connect(db))
    assert s.errors == 0 and s.candles == 0
    before.pop("ingest_runs"), after.pop("ingest_runs")
    assert before == after


def test_replay_missing_cassette_is_logged_not_fatal(tmp_path):
    fixtures = tmp_path / "fx"
    shutil.copytree(FIXTURES, fixtures)
    from factorminus.mcp.cassette import Cassette

    Cassette(fixtures / "cassettes").path("invest_get_brand", {"id": "syn-brand-oil1"}).unlink()
    s = load_synth(tmp_path / "x.sqlite", fixtures)
    assert s.errors == 1
