from datetime import date, timedelta

import pytest
from conftest import FakeServer, client

from factorminus import db, ingest

ROWS = [
    {"id": "SYNA_TQBR", "kind": "share", "role": "share", "index": "", "note": ""},
    {"id": "SYNAP_TQBR", "kind": "share", "role": "share", "index": "", "note": ""},
    {"id": "SYNF_TQBR", "kind": "etf", "role": "index_fund", "index": "IMOEX", "note": ""},
    {"id": "GONE_TQBR", "kind": "share", "role": "share", "index": "", "note": ""},
]


def card(args):
    iid = args["instrumentId"]
    if iid == "GONE_TQBR":
        return Exception('{"type":"NOT_FOUND","message":"Instrument not found"}')
    ticker, cls = iid.split("_")
    asset = "asset-f" if ticker == "SYNF" else "asset-a"
    return {
        "instrument": {
            "ticker": ticker,
            "classCode": cls,
            "name": f"Бумага {ticker}",
            "lot": 1,
            "assetUid": asset,
            "dlongClient": {"value": "0.25"},
            "first1dayCandleDate": "2020-01-03T07:00:00Z",
        }
    }


def candles(args):
    start = date(2019, 12, 30) if "limit" in args else date.fromisoformat(args["from"][:10])
    days = [start + timedelta(d) for d in range((date.today() - start).days + 1)]
    price = {"units": "100", "nano": 500000000}
    out = [{"time": d.isoformat(), "open": price, "high": price, "low": price,
            "close": {"value": "101.5"}, "volume": "10"} for d in days]  # fmt: skip
    return {"candles": out}


def risk(args):
    rows = [{"instrumentUid": f"uid-{i}", "shortRiskRates": [], "longRiskRates": []}
            for i in args["instrumentId"]]  # fmt: skip
    return {"instrumentRiskRates": rows}


@pytest.fixture
def server():
    return FakeServer(
        {
            "invest_get_share": card,
            "invest_get_etf": card,
            "invest_get_asset": lambda a: {
                "asset": {"name": a["id"], "brand": {"uid": "b-" + a["id"]}}
            },
            "invest_get_brand": lambda a: {"uid": a["id"], "name": "Бренд", "sector": "financial"},
            "invest_get_candles": candles,
            "invest_get_risk_rates": risk,
        }
    )


def counts(conn):
    tables = ("instruments", "brands", "candles")
    return {t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in tables}


def test_ingest_fills_db_and_rerun_does_not_duplicate(server):
    conn = db.connect(":memory:")
    summary = ingest.run(client(server), conn, ROWS, log=lambda *a: None)
    assert summary["instruments"] == 3 and summary["brands"] == 2
    assert len(summary["errors"]) == 1 and "GONE_TQBR" in summary["errors"][0]
    first = counts(conn)
    assert first["instruments"] == 3 and first["brands"] == 2
    assert conn.execute("SELECT min(date) FROM candles").fetchone()[0] == "2020-01-01"
    row = conn.execute("SELECT * FROM instruments WHERE id='SYNA_TQBR'").fetchone()
    assert (
        row["brand_uid"] == "b-asset-a" and row["uid"] == "uid-SYNA_TQBR" and row["dlong"] == 0.25
    )
    assert row["raw_json"] and row["source"] == "mcp"

    ingest.run(client(server), conn, ROWS, log=lambda *a: None)
    assert counts(conn) == first
    brand_calls = [
        b for _, b in server.requests if b.get("params", {}).get("name") == "invest_get_brand"
    ]
    assert len(brand_calls) == 2


@pytest.mark.parametrize(
    "raw, expected",
    [
        ({"units": "12", "nano": 500000000}, 12.5),
        ({"units": -1, "nano": -250000000}, -1.25),
        ({"value": "0.1428"}, 0.1428),
        ("42.5", 42.5),
        (7, 7.0),
        (None, None),
        ({}, None),
    ],
)
def test_num(raw, expected):
    assert ingest.num(raw) == expected
