import re
import sqlite3
import subprocess
from pathlib import Path

import httpx
import pytest

from factorminus import cli, config, iss, mcp

ROOT = Path(__file__).parents[1]


@pytest.fixture
def no_network(monkeypatch):
    def refuse(*a, **kw):
        raise AssertionError("тест не должен ходить в сеть")

    monkeypatch.setattr(httpx.Client, "send", refuse)


def test_demo_works_without_token_and_network(tmp_path, capsys, no_network):
    assert cli.main(["demo"]) == 0
    assert (tmp_path / "data" / "fm.sqlite").exists()
    out = capsys.readouterr().out
    assert "candles" in out and "synth" in out and "SYN_MARKET" in out


def test_missing_token_is_friendly_error(capsys, no_network):
    assert cli.main(["ingest"]) == 1
    err = capsys.readouterr().err
    assert "TINVEST_TOKEN" in err and "Traceback" not in err


def test_call_outside_whitelist_is_rejected(monkeypatch, capsys, no_network):
    monkeypatch.setenv("TINVEST_TOKEN", "t.fake")
    assert cli.main(["call", "invest_create_order", "{}"]) == 1
    assert "белом списке" in capsys.readouterr().err


def test_empty_iss_weights_is_friendly_error(monkeypatch, capsys, no_network):
    monkeypatch.setattr(iss, "fetch_weights", lambda: [])
    assert cli.main(["weights"]) == 1
    assert "ISS" in capsys.readouterr().err


def test_db_error_is_friendly_error(monkeypatch, capsys, no_network):
    def locked():
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(cli, "open_db", locked)
    assert cli.main(["stats"]) == 1
    err = capsys.readouterr().err
    assert "базы данных" in err and "Traceback" not in err


def test_no_token_in_git_files():
    files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout
    pattern = re.compile(r"t\.[A-Za-z0-9_-]{80,}")
    leaked = [f for f in files.split() if (ROOT / f).is_file()
              and pattern.search((ROOT / f).read_text(errors="ignore"))]  # fmt: skip
    assert leaked == []


@pytest.mark.live
@pytest.mark.parametrize(
    "tool, args",
    [
        ("invest_find_instrument", {"query": "TMOS", "instrumentKind": "INSTRUMENT_TYPE_ETF"}),
        ("invest_get_share", {"instrumentId": "SBER_TQBR", "idType": "INSTRUMENT_ID_TYPE_ID"}),
        ("invest_get_etf", {"instrumentId": "TMOS_TQBR", "idType": "INSTRUMENT_ID_TYPE_ID"}),
        ("invest_get_bond", {"instrumentId": "RU000A101012_TQCB", "idType": "INSTRUMENT_ID_TYPE_ID"}),
        ("invest_get_currency", {"instrumentId": "USD000UTSTOM_CETS", "idType": "INSTRUMENT_ID_TYPE_ID"}),
        ("invest_get_asset", {"id": "41ee95a0-318f-49e1-bfe4-2c3f7c83fe21"}),
        ("invest_get_brand", {"id": "8be1bbf0-6035-42ec-9e02-a623887ee29e"}),
        ("invest_get_candles", {"instrumentId": "SBER_TQBR", "interval": "CANDLE_INTERVAL_DAY",
                                "limit": 5, "to": "2026-11-20T00:00:00Z"}),
        ("invest_get_risk_rates", {"instrumentId": ["SBER_TQBR"]}),
    ],
)  # fmt: skip
def test_live_tool_answers(monkeypatch, tool, args):
    monkeypatch.chdir(ROOT)  # токен из .env в корне репозитория
    client = mcp.Mcp(config.token(), config.mcp_url())
    assert client.call(tool, args)
