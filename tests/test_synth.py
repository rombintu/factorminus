import numpy as np
import pytest

from factorminus import db, synth

E = synth.EXPECTED


@pytest.fixture(scope="module")
def conn():
    conn = db.connect(":memory:")
    synth.write(conn)
    return conn


def returns(conn, iid):
    rows = conn.execute(
        "SELECT date, close FROM candles WHERE instrument_id=? ORDER BY date", (iid,)
    )
    dates, closes = zip(*rows)
    return np.array(dates[1:]), np.diff(np.log(closes))


def corr(a, b):
    return np.corrcoef(a, b)[0, 1]


def test_same_seed_same_data_and_rewrite_keeps_real_rows():
    a, b = db.connect(":memory:"), db.connect(":memory:")
    a.execute("INSERT INTO instruments (id, source) VALUES ('SBER_TQBR', 'mcp')")
    synth.write(a, seed=7)
    synth.write(a, seed=7)  # повторная запись заменяет старую синтетику
    synth.write(b, seed=7)
    q = "SELECT * FROM candles ORDER BY instrument_id, date"
    assert [tuple(r) for r in a.execute(q)] == [tuple(r) for r in b.execute(q)]
    n = "SELECT count(*) FROM instruments"
    assert a.execute(n).fetchone()[0] == b.execute(n).fetchone()[0] + 1


def test_index_funds_and_hidden_duplicate(conn):
    twin_a, twin_b = E["index_twins"]
    _, ra = returns(conn, twin_a)
    for other in (twin_b, E["hidden_duplicate"]):
        assert corr(ra, returns(conn, other)[1]) >= E["twin_min_corr"]
    hidden = conn.execute(
        "SELECT i.name, i.asset_name, b.description FROM instruments i "
        "JOIN brands b ON b.uid = i.brand_uid WHERE i.id = ?",
        (E["hidden_duplicate"],),
    ).fetchone()
    assert all("индекс" not in (text or "").lower() for text in hidden)
    weights = conn.execute("SELECT sum(weight) FROM index_weights WHERE index_id='SYNIDX'")
    assert weights.fetchone()[0] == pytest.approx(100)


def test_sectors_and_special_papers(conn):
    oil = [returns(conn, i)[1] for i in E["oil"]]
    lo, hi = E["oil_corr"]
    assert all(lo <= corr(x, y) <= hi for i, x in enumerate(oil) for y in oil[i + 1 :])
    banks = np.mean([returns(conn, i)[1] for i in E["banks"]], axis=0)
    basket = (np.mean(oil, axis=0) + banks) / 2
    assert corr(returns(conn, E["dividend_fund"])[1], basket) > 0.85
    brands = {i: conn.execute("SELECT brand_uid FROM instruments WHERE id=?", (i,)).fetchone()[0]
              for i in E["same_brand"]}  # fmt: skip
    assert len(set(brands.values())) == 1
    market = returns(conn, E["index_twins"][0])[1]
    assert corr(returns(conn, E["gold"])[1], market) <= E["gold_max_market_corr"]
    assert returns(conn, E["money_fund"])[1].std() < E["money_max_daily_vol"]
    short, long_ = (returns(conn, i)[1].std() for i in E["ofz_by_duration"])
    assert long_ > 2 * short
    sid, days = E["short_history"]
    assert (
        conn.execute("SELECT count(*) FROM candles WHERE instrument_id=?", (sid,)).fetchone()[0]
        == days
    )


def test_shock_pair_moves_together_only_in_shocks(conn):
    dates, market = returns(conn, E["index_twins"][0])
    shock = np.zeros(len(dates), bool)
    for first, last in E["shocks"]:
        shock |= (dates >= first) & (dates <= last)
    a, b = (returns(conn, i)[1] for i in E["shock_pair"])
    assert corr(a[shock], b[shock]) > E["shock_corr_min"]
    resid = [x - np.polyfit(market[~shock], x[~shock], 1)[0] * market for x in (a, b)]
    lo, hi = E["normal_resid_corr"]
    assert lo <= corr(resid[0][~shock], resid[1][~shock]) <= hi


def test_group_present_and_missing_id_absent(conn):
    ids = {r[0] for r in conn.execute("SELECT id FROM instruments")}
    group = E["group"]
    assert {group["parent"], *group["members"]} <= ids
    assert E["missing_id"] not in ids


def test_market_follows_index_and_worst_days_fall_in_shocks(conn):
    assert db.market_id(conn, "SYNIDX") == E["market"]
    dates, market = returns(conn, E["market"])
    assert corr(returns(conn, E["index_twins"][0])[1], market) >= 0.99
    worst = np.argsort(market)[: int(len(market) * 0.05)]
    in_shock = [any(a <= dates[i] <= b for a, b in E["shocks"]) for i in worst]
    assert np.mean(in_shock) >= 0.8


def test_issuer_shared_by_same_company(conn):
    issuer = dict(conn.execute("SELECT id, issuer FROM instruments"))
    assert issuer["SYN_SBER"] == issuer["SYN_SBERP"] == "ПАО Синтбанк"
    assert issuer["SYN_HTEL"] == issuer["SYN_HTELB"]
    assert issuer["SYN_OFZ2"] == issuer["SYN_OFZ8"] == "Минфин Синт"
    assert issuer["SYN_IDXA"] is None and issuer[E["market"]] is None


def test_index_members_matched_to_instruments(conn):
    day, members = db.index_members(conn, "SYNIDX")
    assert day == synth.DATES[-1] and len(members) == 12
    assert all(iid == ticker for iid, ticker, _ in members)
    assert sum(w for _, _, w in members) == pytest.approx(100)
