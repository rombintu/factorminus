from pathlib import Path

import pytest

from factorminus.config import REPO_ROOT
from factorminus.ingest.universe import (
    UniverseEntry,
    instrument_args,
    load_universe,
    verify_universe,
)
from factorminus.mcp.errors import McpToolError


def write(tmp_path, text) -> Path:
    p = tmp_path / "u.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def test_load_valid(tmp_path):
    p = write(
        tmp_path,
        """
- id: TMOS_TQTF
  kind: etf
  role: index_fund
  index: IMOEX
  note: Т-Капитал Индекс МосБиржи
- id: SBER_TQBR
  kind: share
  role: share
""",
    )
    entries = load_universe(p)
    assert [e.id for e in entries] == ["TMOS_TQTF", "SBER_TQBR"]
    assert entries[0].index == "IMOEX"
    assert entries[1].note == ""


@pytest.mark.parametrize(
    "text,match",
    [
        ("- {id: A_B, kind: etf, role: index_fund}", "index"),
        ("- {id: A_B, kind: share, role: share, index: IMOEX}", "index"),
        ("- {id: A_B, kind: share, role: nope}", "role"),
        ("- {id: A_B, kind: stock, role: share}", "kind"),
        ("- {id: A_B, kind: share, role: share}\n- {id: A_B, kind: share, role: share}", "дубл"),
        ("- {id: sber, kind: share, role: share}", "id"),
        ("{}", "universe.yaml"),
    ],
)
def test_load_invalid(tmp_path, text, match):
    with pytest.raises(ValueError, match=match):
        load_universe(write(tmp_path, text))


def test_instrument_args():
    e = UniverseEntry(id="SBER_TQBR", kind="share", role="share")
    assert instrument_args(e) == {
        "instrumentId": "SBER_TQBR",
        "idType": "INSTRUMENT_ID_TYPE_ID",
        "responseView": ["FULL"],
    }


class FakeClient:
    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def call_tool(self, name, args):
        self.calls.append((name, args))
        a = self.answers[args["instrumentId"]]
        if isinstance(a, Exception):
            raise a
        return a


def test_verify_universe_does_not_fail_on_missing():
    entries = [
        UniverseEntry(id="SYN_A", kind="share", role="share"),
        UniverseEntry(id="SYN_B", kind="etf", role="money_fund"),
        UniverseEntry(id="SYN_C", kind="bond", role="ofz"),
    ]
    client = FakeClient(
        {
            "SYN_A": {
                "instrument": {"ticker": "SYN_A", "name": "А", "apiTradeAvailableFlag": True}
            },
            "SYN_B": McpToolError("invest_get_etf", "not found"),
            "SYN_C": {
                "instrument": {"ticker": "SYN_C", "name": "С", "apiTradeAvailableFlag": False}
            },
        }
    )
    report = verify_universe(client, entries)
    assert report["found"] == ["SYN_A", "SYN_C"]
    assert report["not_found"] == ["SYN_B"]
    assert report["no_api_flag"] == ["SYN_C"]
    assert report["details"]["SYN_B"]["error"].endswith("not found")
    assert [c[0] for c in client.calls] == ["invest_get_share", "invest_get_etf", "invest_get_bond"]


def test_real_universe_file_is_valid():
    entries = load_universe(REPO_ROOT / "data" / "universe.yaml")
    assert len(entries) >= 55
    roles = {e.role for e in entries}
    assert {"index_fund", "share", "ofz", "corp_bond", "gold_fund", "money_fund"} <= roles
    assert sum(e.role == "index_fund" for e in entries) >= 3
