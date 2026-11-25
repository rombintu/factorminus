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


def test_fixtures_match_generator(tmp_path):
    """Набор в tests/fixtures/synthetic (из conftest или из образа) — это seed 42."""
    write_dataset(generate(42), tmp_path / "gen")
    assert _dirs_equal(tmp_path / "gen", FIXTURES), "пересоберите образ или: make synth"


@pytest.fixture(scope="module")
def closes():
    series = defaultdict(dict)
    with open(FIXTURES / "candles.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            series[row["instrument_id"]][row["date"]] = float(row["close"])
    return series


@pytest.fixture(scope="module")
def manifest():
    return json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))


def regime_days(manifest) -> dict[str, set[str]]:
    """Даты (день доходности) по режимам: shock = эпизоды и дни падения."""
    p = manifest["params"]
    shock = set(p["drop_days"])
    episodes = {}
    for e in p["shocks"]:
        days = {d for d in _all_days(manifest) if e["start"] <= d <= e["end"]}
        episodes[e["id"]] = days
        shock |= days
    return {"shock": shock, **episodes}


def _all_days(manifest):
    from datetime import date

    from factorminus.synth.generator import business_days

    p = manifest["params"]
    return [d.isoformat() for d in business_days(date.fromisoformat(p["start"]), p["n_days"])]


def returns(closes, ids, regime=None, regimes=None):
    """Лог-доходности по общим датам; день доходности = дата закрытия."""
    days = sorted(set.intersection(*(set(closes[i]) for i in ids)))
    out = {i: np.diff(np.log([closes[i][d] for d in days])) for i in ids}
    ret_days = days[1:]
    if regime is not None:
        mask = np.array([(d in regimes["shock"]) == (regime == "shock") for d in ret_days])
        out = {i: r[mask] for i, r in out.items()}
    return out


def corr(closes, a, b, regime=None, regimes=None):
    r = returns(closes, [a, b], regime, regimes)
    return float(np.corrcoef(r[a], r[b])[0, 1])


def resid_corr(closes, a, b, market, regime, regimes):
    r = returns(closes, [a, b, market], regime, regimes)
    m = r[market]

    def resid(x):
        beta = np.cov(x, m)[0, 1] / np.var(m, ddof=1)
        return x - beta * m

    return float(np.corrcoef(resid(r[a]), resid(r[b]))[0, 1])


def _fixture_json(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _csv_rows():
    with open(FIXTURES / "candles.csv", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def check(p, closes, manifest, regimes, universe_ids) -> tuple[bool, float | None]:
    t, a, reg = p["type"], p["a"], p.get("regime")
    instruments = {i["ticker"]: i for i in _fixture_json("instruments.json")}
    brands = {b["uid"]: b for b in _fixture_json("brands.json").values()}
    if t == "same_issuer_different_brand":
        ba, bb = instruments[a]["brandUid"], instruments[p["b"]]["brandUid"]
        return ba != bb and brands[ba]["company"] == brands[bb]["company"], None
    if t == "issuer_override":
        text = (FIXTURES / "universe.yaml").read_text(encoding="utf-8")
        company = brands[instruments[a]["brandUid"]]["company"]
        return f"issuer: {p['value']}" in text and company != p["value"], None
    if t == "weekend_candles":
        from datetime import date as _d

        rows = _csv_rows()
        wk = [r for r in rows if _d.fromisoformat(r["date"]).weekday() >= 5]
        ids = {r["instrument_id"] for r in wk}
        ok = ids == set(a) and all(r["date"] >= p["from"] for r in wk)
        ok = ok and all(int(r["volume"]) <= p["max_volume"] for r in wk)
        return ok, len(wk)
    if t == "incomplete_last_candle":
        # корректный загрузчик не сохраняет незакрытую свечу: в CSV последней даты нет
        return max(closes[a]) < manifest["params"]["end"], None
    if t == "no_brand":
        return instruments[a]["brandUid"] is None, None
    if t == "empty_sector":
        return all(brands[instruments[x]["brandUid"]]["sector"] == "" for x in a), None
    if t == "starts_after_episode":
        ep = next(e for e in manifest["params"]["shocks"] if e["id"] == p["episode"])
        return min(closes[a]) > ep["end"], None
    if t == "index_candles":
        return len(closes[a]) == p["value"], len(closes[a])
    if t == "corr_gte":
        v = corr(closes, a, p["b"], reg, regimes)
        return v >= p["value"], v
    if t == "corr_lte":
        v = corr(closes, a, p["b"], reg, regimes)
        return v <= p["value"], v
    if t == "corr_between":
        v = corr(closes, a, p["b"], reg, regimes)
        return p["low"] <= v <= p["high"], v
    if t == "resid_corr_between":
        v = resid_corr(closes, a, p["b"], p["market"], reg, regimes)
        return p["low"] <= v <= p["high"], v
    if t == "calm_trend_opposite":
        r = returns(closes, [a, p["b"]], "normal", regimes)
        va, vb = float(r[a].sum()), float(r[p["b"]].sum())
        return va > 0 > vb, va - vb
    if t == "episode_drawdown_lte":
        days = sorted(regimes[p["episode"]])
        prev = max(d for d in closes[a] if d < days[0])
        v = closes[a][days[-1]] / closes[a][prev] - 1
        return v <= p["value"], v
    if t == "vol_lte":
        v = float(np.std(returns(closes, [a])[a]))
        return v <= p["value"], v
    if t == "vol_gt":
        r = returns(closes, [a, p["b"]])
        return bool(np.std(r[a]) > np.std(r[p["b"]])), None
    if t == "history_days_eq":
        return len(closes[a]) == p["value"], len(closes[a])
    if t == "not_in_universe":
        return a not in universe_ids and a not in closes, None
    raise AssertionError(f"неизвестный тип свойства {t}")


def test_manifest_expected_properties(closes, manifest):
    assert manifest["seed"] == 42
    regimes = regime_days(manifest)
    universe_ids = {
        line.split(":", 1)[1].strip()
        for line in (FIXTURES / "universe.yaml").read_text(encoding="utf-8").splitlines()
        if line.startswith("- id:")
    }
    failures = []
    for p in manifest["expected"]:
        ok, value = check(p, closes, manifest, regimes, universe_ids)
        if not ok:
            failures.append((p, value))
    assert not failures, failures
    assert len(manifest["expected"]) >= 35


def test_manifest_describes_shocks_and_groups(manifest):
    p = manifest["params"]
    assert p["n_days"] == 1500
    assert [(e["id"], e["days"]) for e in p["shocks"]] == [
        ("SHOCK_A", 30),
        ("SHOCK_B", 20),
        ("SHOCK_C", 150),
    ]
    assert len(p["drop_days"]) >= 5
    group = manifest["groups"][0]
    assert len(group["member_brands"]) + 1 >= 3
    kinds = {i["id"]: i["kind"] for i in manifest["instruments"]}
    assert sum(kinds[i] == "bond" for i in group["instruments"]) >= 2


def test_index_weights_sum_100():
    assert sum(INDEX_WEIGHTS.values()) == pytest.approx(100.0, abs=0.01)
    with open(FIXTURES / "index_weights.csv", encoding="utf-8") as f:
        assert sum(float(r["weight"]) for r in csv.DictReader(f)) == pytest.approx(100, abs=0.01)


def test_no_real_tickers(closes):
    manifest = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))
    assert all(i["id"].startswith("SYN_") for i in manifest["instruments"])
    assert all(i.startswith("SYN_") or i == "SYNIDX_INDEX" for i in closes)
    assert len(closes["SYN_IDXA"]) == N_DAYS
