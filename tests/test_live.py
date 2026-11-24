"""Живые проверки структуры ответов MCP и ISS. Запуск: make test-live (нужен токен в .env)."""

from datetime import timedelta

import pytest

from factorminus.config import load_settings
from factorminus.ingest.parse import MSK, parse_asset, parse_brand, parse_candles, parse_instrument
from factorminus.ingest.pipeline import candle_args, candle_windows
from factorminus.ingest.universe import UniverseEntry, instrument_args
from factorminus.iss import fetch_index_weights
from factorminus.mcp.client import McpClient

pytestmark = pytest.mark.live

CASES = [
    ("invest_get_share", "share", "SBER_TQBR"),
    ("invest_get_etf", "etf", "TMOS_TQBR"),
    ("invest_get_bond", "bond", "SU26238RMFS4_TQOB"),
]


@pytest.fixture(scope="module")
def client():
    settings = load_settings()
    if not settings.token:
        pytest.skip("TINVEST_TOKEN не задан")
    with McpClient(settings) as c:
        yield c


@pytest.mark.parametrize("tool,kind,iid", CASES, ids=[c[2] for c in CASES])
def test_card_asset_brand_candles(client, tool, kind, iid):
    entry = UniverseEntry(id=iid, kind=kind, role="share" if kind == "share" else "ofz"
                          if kind == "bond" else "money_fund")  # fmt: skip
    row = parse_instrument(client.call_tool(tool, instrument_args(entry)), kind)
    assert row["ticker"] and row["class_code"] and row["asset_uid"] and row["lot"]
    assert row["first_day_candle"] and len(row["first_day_candle"]) == 10
    if kind == "bond":
        assert row["maturity_date"] and len(row["maturity_date"]) == 10
    asset = parse_asset(client.call_tool("invest_get_asset", {"id": row["asset_uid"]}))
    assert asset["brand_uid"]
    brand = parse_brand(client.call_tool("invest_get_brand", {"id": asset["brand_uid"]}))
    assert brand["name"] and brand["sector"]

    from datetime import datetime

    today = datetime.now(MSK).date()
    ((frm, to),) = candle_windows(today - timedelta(days=30), today)
    candles = parse_candles(client.call_tool("invest_get_candles", candle_args(iid, frm, to)))
    assert len(candles) >= 10
    assert all(c["close"] > 0 and len(c["date"]) == 10 for c in candles)


def test_iss_imoex_weights():
    rows = fetch_index_weights("IMOEX", verify=load_settings().ssl_verify())
    assert len(rows) >= 30
    assert sum(r["weight"] for r in rows) == pytest.approx(100, abs=0.5)


def _issuer(client, iid, kind, tool):
    from factorminus.ingest.issuer import pick_issuer

    entry = UniverseEntry(id=iid, kind=kind, role="share" if kind == "share" else "corp_bond")
    row = parse_instrument(client.call_tool(tool, instrument_args(entry)), kind)
    asset = parse_asset(client.call_tool("invest_get_asset", {"id": row["asset_uid"]}))
    brand = parse_brand(client.call_tool("invest_get_brand", {"id": asset["brand_uid"]}))
    return asset["brand_uid"], pick_issuer(
        override=None, kind=kind, brand_name=brand["name"], brand_company=brand["company"]
    )[1]


@pytest.mark.parametrize(
    "a,b",
    [
        (("SBER_TQBR", "share", "invest_get_share"), ("SBERP_TQBR", "share", "invest_get_share")),
        (
            ("MTSS_TQBR", "share", "invest_get_share"),
            ("RU000A1078S8_TQCB", "bond", "invest_get_bond"),
        ),
    ],
    ids=["SBER-SBERP", "MTSS-bond"],
)
def test_same_issuer_different_brand_live(client, a, b):
    brand_a, issuer_a = _issuer(client, *a)
    brand_b, issuer_b = _issuer(client, *b)
    assert brand_a != brand_b
    assert issuer_a == issuer_b is not None


def test_imoex_index_candles_live(client):
    from factorminus.ingest.index_candles import INDEX_SOURCES

    payload = client.call_tool(
        "invest_get_candles",
        candle_args(INDEX_SOURCES["IMOEX"], "2020-01-01T00:00:00Z", "2020-02-01T00:00:00Z"),
    )
    rows = parse_candles(payload)
    assert rows and rows[0]["date"] == "2020-01-03" and rows[0]["close"] > 1000
