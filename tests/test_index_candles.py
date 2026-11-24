import json
from datetime import date

import pytest

from factorminus.db import connect, migrate
from factorminus.ingest.index_candles import (
    INDEX_SOURCES,
    index_instrument_id,
    ingest_index_candles,
)
from factorminus.mcp.errors import McpToolError


class FakeIndexMcp:
    def __init__(self, days):
        self.days = days
        self.calls = []

    def call_tool(self, name, args):
        self.calls.append((name, args))
        assert name == "invest_get_candles"
        if args["instrumentId"] != "IMOEX_TQBR":
            raise McpToolError(name, "not found")
        lo, hi = args["from"][:10], args["to"][:10]
        return {
            "candles": [
                {
                    "time": d,
                    "open": {"value": "1"},
                    "high": {"value": "2"},
                    "low": {"value": "1"},
                    "close": {"value": str(3000 + i)},
                    "volume": "0",
                    "isComplete": True,
                }
                for i, d in enumerate(self.days)
                if lo <= d < hi
            ]
        }


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "fm.sqlite")
    migrate(c)
    return c


def test_index_sources():
    assert INDEX_SOURCES["IMOEX"] == "IMOEX_TQBR"
    assert index_instrument_id("IMOEX") == "IMOEX_INDEX"
    assert index_instrument_id("SYNIDX") == "SYNIDX_INDEX"


def test_ingest_index_candles_and_source(conn):
    mcp = FakeIndexMcp(["2020-01-03", "2020-01-06", "2021-03-01"])
    n = ingest_index_candles(conn, mcp, "IMOEX", since=date(2020, 1, 1), until=date(2021, 6, 1))
    assert n == 3
    rows = conn.execute(
        "SELECT date, close FROM candles WHERE instrument_id='IMOEX_INDEX' ORDER BY date"
    ).fetchall()
    assert [r[0] for r in rows] == ["2020-01-03", "2020-01-06", "2021-03-01"]
    inst = conn.execute("SELECT * FROM instruments WHERE instrument_id='IMOEX_INDEX'").fetchone()
    assert inst["kind"] == "index" and inst["index_id"] == "IMOEX" and inst["source"] == "mcp"
    assert json.loads(inst["raw_json"])["mcp_instrument_id"] == "IMOEX_TQBR"
    # окна по 365 дней
    assert len([c for c in mcp.calls]) == 2


def test_index_candles_incremental(conn):
    mcp = FakeIndexMcp(["2020-01-03", "2020-01-06"])
    ingest_index_candles(conn, mcp, "IMOEX", since=date(2020, 1, 1), until=date(2020, 1, 6))
    mcp.days.append("2020-01-07")
    mcp.calls.clear()
    n = ingest_index_candles(conn, mcp, "IMOEX", since=date(2020, 1, 1), until=date(2020, 1, 8))
    assert n == 1
    assert [a["from"] for _, a in mcp.calls] == ["2020-01-06T00:00:00Z"]
    assert (
        ingest_index_candles(conn, mcp, "IMOEX", since=date(2020, 1, 1), until=date(2020, 1, 7))
        == 0
    )


def test_unknown_index_is_value_error(conn):
    with pytest.raises(ValueError):
        ingest_index_candles(
            conn, FakeIndexMcp([]), "NOPE", since=date(2020, 1, 1), until=date(2020, 1, 2)
        )
