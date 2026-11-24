from datetime import date

import pytest

from factorminus.db import connect, issuer_summary, migrate
from factorminus.ingest.issuer import normalize_issuer
from factorminus.ingest.pipeline import run_ingest
from factorminus.ingest.universe import UniverseEntry
from test_pipeline import FakeMcp


@pytest.mark.parametrize(
    "raw,display,key",
    [
        ("  Сбербанк  ап  ", "Сбербанк ап", "сбербанк ап"),
        ("СберБанк", "СберБанк", "сбербанк"),
        ("МКПАО\tЭталон   Груп", "МКПАО Эталон Груп", "мкпао эталон груп"),
        ("", None, None),
        (None, None, None),
    ],
)
def test_normalize_issuer(raw, display, key):
    assert normalize_issuer(raw) == (display, key)


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "fm.sqlite")
    migrate(c)
    return c


def mcp_with_companies():
    mcp = FakeMcp()
    # как в реальности: у ао и ап разные бренды, но общая company
    mcp.assets["as-2"]["asset"]["brand"] = {"uid": "br-1p"}
    mcp.brands["br-1"]["brand"]["company"] = "  ПАО  Синтбанк "
    mcp.brands["br-1p"] = {
        "brand": {
            "uid": "br-1p",
            "name": "Синтбанк ап",
            "company": "ПАО Синтбанк",
            "sector": "financial",
        }
    }
    mcp.brands["br-2"]["brand"]["company"] = "Синт-Финанс"
    return mcp


def issuers(conn):
    return {
        r[0]: (r[1], r[2], r[3])
        for r in conn.execute(
            "SELECT instrument_id, issuer, issuer_key, brand_uid FROM instruments"
        )
    }


def test_issuer_from_company_not_brand(conn):
    entries = [
        UniverseEntry(id="SYN_A", kind="share", role="share"),
        UniverseEntry(id="SYN_AP", kind="share", role="share"),
        UniverseEntry(id="SYN_BOND", kind="bond", role="corp_bond"),
    ]
    run_ingest(
        conn,
        mcp_with_companies(),
        entries,
        since=date(2024, 1, 1),
        until=date(2024, 1, 10),
        mode="live",
    )
    got = issuers(conn)
    assert got["SYN_A"][0] == "ПАО Синтбанк"
    assert got["SYN_A"][1] == got["SYN_AP"][1] == "пао синтбанк"
    assert got["SYN_A"][2] != got["SYN_AP"][2]  # бренды разные
    assert got["SYN_BOND"][0] == "Синт-Финанс"


def test_universe_issuer_overrides_company(conn):
    entries = [
        UniverseEntry(id="SYN_A", kind="share", role="share"),
        UniverseEntry(id="SYN_BOND", kind="bond", role="corp_bond", issuer="ПАО  Синтбанк"),
    ]
    run_ingest(
        conn,
        mcp_with_companies(),
        entries,
        since=date(2024, 1, 1),
        until=date(2024, 1, 10),
        mode="live",
    )
    got = issuers(conn)
    assert got["SYN_BOND"][1] == got["SYN_A"][1] == "пао синтбанк"


def test_no_brand_means_null_issuer(conn):
    mcp = mcp_with_companies()
    mcp.assets["as-1"]["asset"].pop("brand")
    run_ingest(
        conn,
        mcp,
        [UniverseEntry(id="SYN_A", kind="share", role="share")],
        since=date(2024, 1, 1),
        until=date(2024, 1, 10),
        mode="live",
    )
    assert issuers(conn)["SYN_A"][:2] == (None, None)
    s = issuer_summary(conn)
    assert s == {"issuers": 0, "without_issuer": ["SYN_A"]}


def test_fund_issuer_is_fund_not_management_company(conn):
    """У фондов company — управляющая компания: она не эмитент риска фонда."""
    mcp = mcp_with_companies()
    mcp.cards["SYN_F1"] = {
        "instrument": dict(mcp.cards["SYN_A"]["instrument"], ticker="SYN_F1", assetUid="as-f1")
    }
    mcp.cards["SYN_F2"] = {
        "instrument": dict(mcp.cards["SYN_A"]["instrument"], ticker="SYN_F2", assetUid="as-f2")
    }
    for n in ("1", "2"):
        mcp.assets[f"as-f{n}"] = {"asset": {"uid": f"as-f{n}", "brand": {"uid": f"br-f{n}"}}}
        mcp.brands[f"br-f{n}"] = {
            "brand": {"uid": f"br-f{n}", "name": f"Фонд {n}", "company": "УК Синт"}
        }
        mcp.candle_days[f"SYN_F{n}"] = []
    entries = [
        UniverseEntry(id="SYN_F1", kind="etf", role="gold_fund"),
        UniverseEntry(id="SYN_F2", kind="etf", role="money_fund"),
    ]
    run_ingest(conn, mcp, entries, since=date(2024, 1, 1), until=date(2024, 1, 10), mode="live")
    got = issuers(conn)
    assert got["SYN_F1"][0] == "Фонд 1" and got["SYN_F2"][0] == "Фонд 2"
