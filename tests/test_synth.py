import csv
import filecmp
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
import pytest

from factorminus.synth.generator import INDEX_WEIGHTS, N_DAYS, generate, write_dataset

FIXTURES = Path(__file__).parent / "fixtures" / "synthetic"


def _dirs_equal(a: Path, b: Path) -> bool:
    fa = sorted(p.relative_to(a) for p in a.rglob("*") if p.is_file())
    fb = sorted(p.relative_to(b) for p in b.rglob("*") if p.is_file())
    if fa != fb:
        return False
    return all(filecmp.cmp(a / f, b / f, shallow=False) for f in fa)


def test_same_seed_byte_identical(tmp_path):
    write_dataset(generate(42), tmp_path / "a")
    write_dataset(generate(42), tmp_path / "b")
    assert _dirs_equal(tmp_path / "a", tmp_path / "b")


def test_different_seed_differs(tmp_path):
    write_dataset(generate(42), tmp_path / "a")
    write_dataset(generate(7), tmp_path / "b")
    assert (tmp_path / "a" / "candles.csv").read_bytes() != (
        tmp_path / "b" / "candles.csv"
    ).read_bytes()


def test_committed_fixtures_match_generator(tmp_path):
    """Фикстуры в git совпадают с тем, что даёт `fm synth generate --seed 42`."""
    write_dataset(generate(42), tmp_path / "gen")
    assert _dirs_equal(tmp_path / "gen", FIXTURES), "перегенерируйте: make synth"


@pytest.fixture(scope="module")
def closes():
    series = defaultdict(dict)
    with open(FIXTURES / "candles.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            series[row["instrument_id"]][row["date"]] = float(row["close"])
    return series


def _returns(closes, a, b=None):
    days = sorted(closes[a]) if b is None else sorted(set(closes[a]) & set(closes[b]))
    ra = np.diff(np.log([closes[a][d] for d in days]))
    if b is None:
        return ra
    rb = np.diff(np.log([closes[b][d] for d in days]))
    return ra, rb


def _corr(closes, a, b):
    ra, rb = _returns(closes, a, b)
    return float(np.corrcoef(ra, rb)[0, 1])


def test_manifest_expected_properties(closes):
    manifest = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["seed"] == 42
    universe_ids = {
        line.split(":", 1)[1].strip()
        for line in (FIXTURES / "universe.yaml").read_text(encoding="utf-8").splitlines()
        if line.startswith("- id:")
    }
    failures = []
    for p in manifest["expected"]:
        t, a = p["type"], p["a"]
        if t == "corr_gte":
            ok = _corr(closes, a, p["b"]) >= p["value"]
        elif t == "corr_lte":
            ok = _corr(closes, a, p["b"]) <= p["value"]
        elif t == "corr_between":
            ok = p["low"] <= _corr(closes, a, p["b"]) <= p["high"]
        elif t == "vol_lte":
            ok = float(np.std(_returns(closes, a))) <= p["value"]
        elif t == "vol_gt":
            ok = np.std(_returns(closes, a)) > np.std(_returns(closes, p["b"]))
        elif t == "history_days_eq":
            ok = len(closes[a]) == p["value"]
        elif t == "not_in_universe":
            ok = a not in universe_ids and a not in closes
        else:
            raise AssertionError(f"неизвестный тип свойства {t}")
        if not ok:
            failures.append(p)
    assert not failures, failures
    assert len(manifest["expected"]) >= 15


def test_index_weights_sum_100():
    assert sum(INDEX_WEIGHTS.values()) == pytest.approx(100.0, abs=0.01)
    with open(FIXTURES / "index_weights.csv", encoding="utf-8") as f:
        assert sum(float(r["weight"]) for r in csv.DictReader(f)) == pytest.approx(100, abs=0.01)


def test_no_real_tickers(closes):
    manifest = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))
    assert all(i["id"].startswith("SYN_") for i in manifest["instruments"])
    assert all(i.startswith("SYN_") for i in closes)
    assert len(closes["SYN_IDXA"]) == N_DAYS
