"""Живые проверки структуры ответов MCP и ISS. Запуск: make test-live (нужен токен в .env)."""

from datetime import timedelta

import pytest

from factorminus.config import load_settings
from factorminus.ingest.parse import (
    MSK,
    parse_asset,
    parse_brand,
    parse_candles,
    parse_instrument,
    parse_risk_rates,
)
from factorminus.ingest.pipeline import candle_args, candle_windows
from factorminus.ingest.universe import UniverseEntry, instrument_args
from factorminus.iss import fetch_index_weights
from factorminus.mcp.client import McpClient
from factorminus.mcp.errors import McpError

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


# --- smoke каждого инструмента белого списка ---
# Минимальные аргументы. "{asset_uid}", "{brand_uid}", "{from}", "{to}" подставляет фикстура
# `smoke_ids` (uid берутся из ответа для SBER_TQBR, даты — последние 30 дней).
# Ответы не печатаются и не сохраняются: проверяется только наличие одного поля.
SMOKE_ARGS: dict[str, dict] = {
    "invest_find_instrument": {"query": "SBER", "responseView": ["IDENTIFIERS"]},
    "invest_get_share": instrument_args(UniverseEntry(id="SBER_TQBR", kind="share", role="share")),
    "invest_get_etf": instrument_args(
        UniverseEntry(id="TMOS_TQBR", kind="etf", role="index_fund", index="MOEXBC")
    ),
    "invest_get_bond": instrument_args(
        UniverseEntry(id="SU26238RMFS4_TQOB", kind="bond", role="ofz")
    ),
    "invest_get_currency": instrument_args(
        UniverseEntry(id="USD000UTSTOM_CETS", kind="currency", role="money_fund")
    ),
    "invest_get_asset": {"id": "{asset_uid}"},
    "invest_get_brand": {"id": "{brand_uid}"},
    "invest_get_candles": candle_args("SBER_TQBR", "{from}", "{to}"),
    "invest_get_risk_rates": {"instrumentId": ["SBER_TQBR"]},
}


def _risk_levels(payload):
    rates = parse_risk_rates(payload)
    return rates and (rates[0]["long"] or rates[0]["short"])


# Одно характерное поле ответа; пустое значение — провал (так ловится пустой ответ).
SMOKE_FIELD = {
    "invest_find_instrument": lambda p: (p.get("instruments") or [{}])[0].get("ticker"),
    "invest_get_share": lambda p: parse_instrument(p, "share")["asset_uid"],
    "invest_get_etf": lambda p: parse_instrument(p, "etf")["asset_uid"],
    "invest_get_bond": lambda p: parse_instrument(p, "bond")["maturity_date"],
    "invest_get_currency": lambda p: parse_instrument(p, "currency")["ticker"],
    "invest_get_asset": lambda p: parse_asset(p)["brand_uid"],
    "invest_get_brand": lambda p: parse_brand(p)["name"],
    "invest_get_candles": lambda p: parse_candles(p),
    "invest_get_risk_rates": _risk_levels,
}


@pytest.fixture(scope="module")
def smoke_ids(client):
    from datetime import datetime

    share = parse_instrument(
        client.call_tool("invest_get_share", SMOKE_ARGS["invest_get_share"]), "share"
    )
    asset = parse_asset(client.call_tool("invest_get_asset", {"id": share["asset_uid"]}))
    today = datetime.now(MSK).date()
    ((frm, to),) = candle_windows(today - timedelta(days=30), today)
    return {"asset_uid": share["asset_uid"], "brand_uid": asset["brand_uid"], "from": frm, "to": to}


def _fill(value, ids):
    if isinstance(value, str) and value.startswith("{") and value.endswith("}"):
        return ids[value[1:-1]]
    return value


@pytest.mark.parametrize("tool", sorted(SMOKE_ARGS))
def test_tool_smoke(client, smoke_ids, tool):
    args = {k: _fill(v, smoke_ids) for k, v in SMOKE_ARGS[tool].items()}
    try:
        payload = client.call_tool(tool, args)
    except McpError as e:  # сообщение сервера об ошибке, без данных ответа
        pytest.fail(f"{tool}: {type(e).__name__}: {e}", pytrace=False)
    try:
        ok = bool(SMOKE_FIELD[tool](payload))
    except (KeyError, TypeError, ValueError, AttributeError, IndexError) as e:
        pytest.fail(f"{tool}: ответ не разобран ({type(e).__name__})", pytrace=False)
    if not ok:
        pytest.fail(f"{tool}: характерное поле пустое", pytrace=False)


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
