"""Сквозной тест загрузки: синтетические кассеты → конвейер (replay) → SQLite. Без сети."""

import csv
import json
from pathlib import Path

import pytest

from factorminus.db import connect, table_counts
from factorminus.synth.load import expected_errors, load_synth

FIXTURES = Path(__file__).parent / "fixtures" / "synthetic"


def _errors(conn):
    return {(r[0], r[1]) for r in conn.execute("SELECT instrument_id, step FROM ingest_errors")}


def test_replay_fills_db_with_only_expected_errors(tmp_path):
    db = tmp_path / "synth.sqlite"
    s = load_synth(db, FIXTURES)
    conn = connect(db)
    # единственная ожидаемая ошибка — фонд без бренда (как AMIX)
    assert _errors(conn) == expected_errors(FIXTURES) == {("SYN_IDXC", "brand")}
    assert s.errors == 1
    with open(FIXTURES / "candles.csv", encoding="utf-8") as f:
        n_candles = sum(1 for _ in csv.DictReader(f))
    counts = table_counts(conn)
    assert counts["candles"] == n_candles
    assert counts["index_weights"] == 13
    universe_n = sum(
        1
        for ln in (FIXTURES / "universe.yaml").read_text(encoding="utf-8").splitlines()
        if ln.startswith("- id:")
    )
    assert counts["instruments"] == universe_n + 1  # + строка индекса SYNIDX_INDEX
    assert "SYN_ABSENT" not in {r[0] for r in conn.execute("SELECT instrument_id FROM instruments")}
    row = conn.execute(
        "SELECT maturity_date, uid FROM instruments WHERE instrument_id='SYN_OFZL'"
    ).fetchone()
    assert row[0] == "2041-05-15" and row[1] == "syn-uid-syn-ofzl"
    manifest = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))
    rng = conn.execute("SELECT MIN(date), MAX(date) FROM candles").fetchone()
    assert (rng[0], rng[1]) == (manifest["params"]["start"], manifest["params"]["end"])


def test_synthetic_issuers_follow_real_rules(tmp_path):
    db = tmp_path / "synth.sqlite"
    load_synth(db, FIXTURES)
    rows = {
        r[0]: r[1:]
        for r in connect(db).execute(
            "SELECT instrument_id, issuer, issuer_key, brand_uid FROM instruments"
        )
    }
    # ао и ап: эмитент один, бренды разные (как SBER/SBERP)
    assert rows["SYN_BANK1"][1] == rows["SYN_BANK1P"][1] is not None
    assert rows["SYN_BANK1"][2] != rows["SYN_BANK1P"][2]
    # акция и облигация одной компании
    assert rows["SYN_GRPTEL"][1] == rows["SYN_GRPTEL_B"][1]
    assert rows["SYN_GRPTEL"][2] != rows["SYN_GRPTEL_B"][2]
    # облигация через «дочку»: эмитент из universe.yaml, а не company «СинтСтрой-Финанс»
    assert rows["SYN_GRPDEV_B"][0] == "ПАО «СинтСтрой»"
    # фонд без бренда — эмитента нет; у фондов одной УК эмитенты разные
    assert rows["SYN_IDXC"][:2] == (None, None)
    assert rows["SYN_GOLD"][1] != rows["SYN_MONEY"][1]


def test_synthetic_data_quirks_in_db(tmp_path):
    db = tmp_path / "synth.sqlite"
    load_synth(db, FIXTURES)
    conn = connect(db)
    manifest = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))
    end = manifest["params"]["end"]
    # незакрытая последняя свеча не сохранена
    assert (
        conn.execute("SELECT MAX(date) FROM candles WHERE instrument_id='SYN_TECH2'").fetchone()[0]
        < end
    )
    # свечи выходных есть только у заявленных бумаг
    wk = {
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT instrument_id FROM candles WHERE strftime('%w', date) IN ('0','6')"
        )
    }
    assert wk == {"SYN_BANK1", "SYN_OIL1", "SYN_TECH2"}
    # пустой сектор сохраняется как NULL
    nulls = {
        r[0]
        for r in conn.execute(
            "SELECT i.instrument_id FROM instruments i JOIN brands b USING(brand_uid) "
            "WHERE b.sector IS NULL"
        )
    }
    assert nulls == {"SYN_GOLD", "SYN_MONEY", "SYN_BONDF"}
    # индекс: та же схема, что у IMOEX_INDEX
    inst = conn.execute(
        "SELECT kind, source FROM instruments WHERE instrument_id='SYNIDX_INDEX'"
    ).fetchone()
    assert tuple(inst) == ("index", "synthetic")
    assert (
        conn.execute("SELECT COUNT(*) FROM candles WHERE instrument_id='SYNIDX_INDEX'").fetchone()[
            0
        ]
        == manifest["params"]["n_days"]
    )
    # фонд моложе шока
    first = conn.execute("SELECT MIN(date) FROM candles WHERE instrument_id='SYN_IDXB'").fetchone()[
        0
    ]
    assert first > manifest["params"]["shocks"][0]["end"]


def test_replay_rerun_is_idempotent(tmp_path):
    db = tmp_path / "synth.sqlite"
    load_synth(db, FIXTURES)
    before = table_counts(connect(db))
    s = load_synth(db, FIXTURES)
    after = table_counts(connect(db))
    assert s.candles == 0
    for t in ("ingest_runs", "ingest_errors"):
        before.pop(t), after.pop(t)
    assert before == after


def test_replay_missing_cassette_is_logged_not_fatal(tmp_path):
    from factorminus.mcp.cassette import Cassette
    from factorminus.synth.generator import generate, write_cassettes

    cassettes = tmp_path / "cassettes"
    write_cassettes(generate(42), cassettes)
    Cassette(cassettes).path("invest_get_brand", {"id": "syn-brand-oil1"}).unlink()
    s = load_synth(tmp_path / "x.sqlite", FIXTURES, cassettes=cassettes)
    assert s.errors == 2  # SYN_IDXC (ожидаемо) + SYN_OIL1


@pytest.mark.git
def test_synthetic_set_not_in_git():
    """Набор строится из seed (conftest, образ), в git его нет — ни данных, ни кассет."""
    import subprocess

    from factorminus.config import REPO_ROOT

    out = subprocess.run(
        ["git", "ls-files", "tests/fixtures/synthetic"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    assert out == []
