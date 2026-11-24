from datetime import date

import pytest

from factorminus.db import connect, migrate
from factorminus.ingest.pipeline import candle_windows, run_ingest
from factorminus.ingest.universe import UniverseEntry
from factorminus.mcp.errors import McpToolError


def test_candle_windows_split_and_bounds():
    assert candle_windows(date(2024, 1, 1), date(2024, 1, 10)) == [
        ("2024-01-01T00:00:00Z", "2024-01-11T00:00:00Z")
    ]
    w = candle_windows(date(2024, 1, 1), date(2025, 6, 30))
    assert w[0] == ("2024-01-01T00:00:00Z", "2024-12-31T00:00:00Z")
    assert w[1] == ("2024-12-31T00:00:00Z", "2025-07-01T00:00:00Z")
    assert candle_windows(date(2024, 2, 1), date(2024, 1, 31)) == []


def card(ticker, asset, cls="SYN", **extra):
    d = {
        "ticker": ticker,
        "classCode": cls,
        "name": ticker,
        "assetUid": asset,
        "lot": 1,
        "currency": "rub",
        "dlongClient": {"value": "0.2"},
        "apiTradeAvailableFlag": True,
    }
    d.update(extra)
    return {"instrument": d}


def candles(*days, complete=True):
    return {
        "candles": [
            {
                "time": d,
                "open": {"value": "1"},
                "high": {"value": "1"},
                "low": {"value": "1"},
                "close": {"value": str(1 + i / 10)},
                "volume": "10",
                "isComplete": complete,
            }
            for i, d in enumerate(days)
        ]
    }


class FakeMcp:
    def __init__(self):
        self.calls = []
        self.cards = {
            "SYN_A": card("SYN_A", "as-1"),
            "SYN_AP": card("SYN_AP", "as-2"),
            "SYN_BOND": card("SYN_BOND", "as-3", maturityDate="2030-01-01"),
            "SYN_NOASSET": card("SYN_NOASSET", None),
        }
        self.assets = {
            "as-1": {"asset": {"uid": "as-1", "name": "ПАО А", "brand": {"uid": "br-1"}}},
            "as-2": {"asset": {"uid": "as-2", "name": "ПАО А (преф)", "brand": {"uid": "br-1"}}},
            "as-3": {"asset": {"uid": "as-3", "name": "Облигация", "brand": {"uid": "br-2"}}},
        }
        self.brands = {
            "br-1": {
                "brand": {"uid": "br-1", "name": "А", "sector": "financial", "description": "Банк"}
            },
            "br-2": {"brand": {"uid": "br-2", "name": "Б", "sector": None}},
        }
        self.candle_days = {
            "SYN_A": ["2024-01-02", "2024-01-03"],
            "SYN_AP": ["2024-01-02"],
            "SYN_BOND": ["2024-01-03"],
            "SYN_NOASSET": [],
        }
        self.fail = set()

    def call_tool(self, name, args):
        self.calls.append((name, args))
        iid = args.get("instrumentId")
        if name in ("invest_get_share", "invest_get_etf", "invest_get_bond"):
            if iid in self.fail or iid not in self.cards:
                raise McpToolError(name, "Instrument not found")
            return self.cards[iid]
        if name == "invest_get_asset":
            return self.assets[args["id"]]
        if name == "invest_get_brand":
            return self.brands[args["id"]]
        if name == "invest_get_candles":
            lo, hi = args["from"][:10], args["to"][:10]
            return candles(*[d for d in self.candle_days[iid] if lo <= d < hi])
        if name == "invest_get_risk_rates":
            out = []
            for i in iid:
                out.append(
                    {
                        "instrumentUid": f"uid-{i}",
                        "longRiskRates": [{"riskLevelCode": "STD", "value": {"value": "0.2"}}],
                        "shortRiskRates": [{"riskLevelCode": "STD", "value": {"value": "0.3"}}],
                    }
                )
            return {"instrumentRiskRates": out}
        raise AssertionError(name)


ENTRIES = [
    UniverseEntry(id="SYN_A", kind="share", role="share"),
    UniverseEntry(id="SYN_AP", kind="share", role="share"),
    UniverseEntry(id="SYN_BOND", kind="bond", role="corp_bond"),
]


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "fm.sqlite")
    migrate(c)
    return c


def counts(conn):
    return {
        t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        for t in ("instruments", "assets", "brands", "candles")
    }


def run(conn, mcp, entries=ENTRIES, until=date(2024, 1, 10)):
    return run_ingest(conn, mcp, entries, since=date(2024, 1, 1), until=until, mode="replay")


def test_fills_tables(conn):
    mcp = FakeMcp()
    s = run(conn, mcp)
    assert (s.instruments, s.brands, s.candles, s.errors) == (3, 2, 4, 0)
    assert counts(conn) == {"instruments": 3, "assets": 3, "brands": 2, "candles": 4}
    row = conn.execute("SELECT * FROM instruments WHERE instrument_id='SYN_A'").fetchone()
    assert row["brand_uid"] == "br-1"
    assert row["role"] == "share"
    assert row["source"] == "mcp"
    assert row["uid"] == "uid-SYN_A"
    assert row["dlong"] == 0.2 and row["dshort"] == 0.3  # dshort дополнен из risk rates
    bond = conn.execute("SELECT maturity_date FROM instruments WHERE instrument_id='SYN_BOND'")
    assert bond.fetchone()[0] == "2030-01-01"
    run_row = conn.execute("SELECT * FROM ingest_runs").fetchone()
    assert run_row["ok_count"] == 3 and run_row["error_count"] == 0
    assert run_row["mode"] == "replay"


def test_brand_requested_once(conn):
    mcp = FakeMcp()
    run(conn, mcp)
    brand_calls = [a["id"] for n, a in mcp.calls if n == "invest_get_brand"]
    assert sorted(brand_calls) == ["br-1", "br-2"]


def test_error_on_one_paper_does_not_stop(conn):
    mcp = FakeMcp()
    mcp.fail.add("SYN_AP")
    entries = ENTRIES + [UniverseEntry(id="SYN_NOASSET", kind="share", role="share")]
    s = run(conn, mcp, entries)
    assert s.instruments == 3  # A, BOND, NOASSET
    errs = conn.execute("SELECT instrument_id, step FROM ingest_errors").fetchall()
    assert sorted(tuple(r) for r in errs) == [("SYN_AP", "card"), ("SYN_NOASSET", "asset")]
    assert s.errors == 2
    # бумага без assetUid всё равно в instruments
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM instruments WHERE instrument_id='SYN_NOASSET'"
        ).fetchone()[0]
        == 1
    )


def test_rerun_is_idempotent(conn):
    run(conn, FakeMcp())
    before = counts(conn)
    s = run(conn, FakeMcp())
    assert counts(conn) == before
    assert s.candles == 0


def test_incremental_candles_from_last_date(conn):
    mcp = FakeMcp()
    run(conn, mcp)
    mcp.calls.clear()
    mcp.candle_days["SYN_A"].append("2024-01-15")
    s = run(conn, mcp, until=date(2024, 1, 20))
    froms = {a["instrumentId"]: a["from"] for n, a in mcp.calls if n == "invest_get_candles"}
    assert froms["SYN_A"] == "2024-01-04T00:00:00Z"
    assert froms["SYN_BOND"] == "2024-01-04T00:00:00Z"
    assert froms["SYN_AP"] == "2024-01-03T00:00:00Z"
    assert s.candles == 1


def test_incomplete_candles_skipped(conn):
    mcp = FakeMcp()
    orig = mcp.call_tool

    def call(name, args):
        if name == "invest_get_candles":
            return candles("2024-01-02", complete=False)
        return orig(name, args)

    mcp.call_tool = call
    s = run(conn, mcp)
    assert s.candles == 0


def test_risk_rates_length_mismatch_is_error_not_crash(conn):
    mcp = FakeMcp()
    orig = mcp.call_tool

    def call(name, args):
        if name == "invest_get_risk_rates":
            return {"instrumentRiskRates": []}
        return orig(name, args)

    mcp.call_tool = call
    s = run(conn, mcp)
    assert s.errors == 1
    assert conn.execute("SELECT step FROM ingest_errors").fetchone()[0] == "risk_rates"
