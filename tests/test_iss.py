import httpx
import pytest

from factorminus.db import connect, migrate
from factorminus.iss import fetch_index_weights, parse_iss_analytics, store_index_weights

PAYLOAD = {
    "analytics": {
        "columns": [
            "indexid",
            "tradedate",
            "ticker",
            "shortnames",
            "secids",
            "weight",
            "tradingsession",
        ],
        "data": [
            ["SYNIDX", "2026-11-20", "SYNA", "Синт А", "SYNA", 60.5, 3],
            ["SYNIDX", "2026-11-20", "SYNB", "Синт Б", "SYNB", 39.5, 3],
        ],
    }
}


def test_parse():
    rows = parse_iss_analytics(PAYLOAD)
    assert rows[0] == {
        "trade_date": "2026-11-20",
        "ticker": "SYNA",
        "secids": "SYNA",
        "shortname": "Синт А",
        "weight": 60.5,
    }
    assert len(rows) == 2


def test_parse_empty_and_bad():
    assert parse_iss_analytics({"analytics": {"columns": ["ticker"], "data": []}}) == []
    with pytest.raises(ValueError):
        parse_iss_analytics({"nope": 1})


def test_fetch_uses_url_and_parses():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=PAYLOAD)

    rows = fetch_index_weights("SYNIDX", transport=httpx.MockTransport(handler))
    assert len(rows) == 2
    assert "/analytics/SYNIDX.json" in str(seen[0].url)
    assert "Authorization" not in seen[0].headers


def test_fetch_http_error():
    t = httpx.MockTransport(lambda r: httpx.Response(503))
    with pytest.raises(httpx.HTTPStatusError):
        fetch_index_weights("SYNIDX", transport=t)


def test_store_idempotent(tmp_path):
    conn = connect(tmp_path / "fm.sqlite")
    migrate(conn)
    rows = parse_iss_analytics(PAYLOAD)
    assert store_index_weights(conn, "SYNIDX", rows) == 2
    rows[0]["weight"] = 61.0
    store_index_weights(conn, "SYNIDX", rows)
    got = conn.execute("SELECT ticker, weight FROM index_weights ORDER BY ticker").fetchall()
    assert [tuple(r) for r in got] == [("SYNA", 61.0), ("SYNB", 39.5)]


def test_parse_missing_column_is_value_error():
    with pytest.raises(ValueError):
        parse_iss_analytics({"analytics": {"columns": ["ticker"], "data": [["X"]]}})


@pytest.mark.parametrize("bad", ["imoex", "IMOEX/../x", "IMOEX?a=1", "", "A" * 20])
def test_index_id_validated(bad):
    with pytest.raises(ValueError):
        fetch_index_weights(bad, transport=httpx.MockTransport(lambda r: httpx.Response(200)))
