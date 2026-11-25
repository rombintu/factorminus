import pytest

from factorminus.mcp.allowlist import READ_ONLY_TOOLS, ensure_allowed
from factorminus.mcp.cassette import Cassette
from factorminus.mcp.errors import CassetteMissError, ForbiddenToolError

# Только инструменты, которые вызывает код (ревью PR #1, п. 3)
EXPECTED = {
    "invest_find_instrument",
    "invest_get_share",
    "invest_get_etf",
    "invest_get_bond",
    "invest_get_currency",
    "invest_get_asset",
    "invest_get_brand",
    "invest_get_candles",
    "invest_get_risk_rates",
}


def test_allowlist_is_exactly_spec():
    assert READ_ONLY_TOOLS == frozenset(EXPECTED)
    for name in EXPECTED:
        ensure_allowed(name)


@pytest.mark.parametrize(
    "name", ["invest_get_asset_fundamentals", "invest_get_news", "invest_list_shares"]
)
def test_unused_tools_removed(name):
    with pytest.raises(ForbiddenToolError):
        ensure_allowed(name)


def test_every_allowed_tool_has_live_smoke():
    """Инструмент попадает в белый список только вместе с live-проверкой (офлайн-тест)."""
    from test_live import SMOKE_ARGS, SMOKE_FIELD

    assert set(SMOKE_ARGS) == READ_ONLY_TOOLS
    assert set(SMOKE_FIELD) == READ_ONLY_TOOLS


@pytest.mark.parametrize(
    "name",
    [
        "invest_create_order",
        "invest_create_stoporder",
        "invest_cancel_order",
        "invest_cancel_stoporder",
        "invest_replace_order",
        "invest_deposit_broker_account",
        "invest_transfer_broker_accounts",
        "invest_create_favorite_group",
        "invest_edit_favorite_instruments",
        "invest_get_portfolio",
        "invest_list_accounts",
        "",
        "INVEST_GET_SHARE",
    ],
)
def test_forbidden(name):
    with pytest.raises(ForbiddenToolError):
        ensure_allowed(name)


def test_cassette_key_order_independent(tmp_path):
    c = Cassette(tmp_path)
    assert c.key("t", {"a": 1, "b": [1, 2]}) == c.key("t", {"b": [1, 2], "a": 1})
    assert c.key("t", {"a": 1}) != c.key("t", {"a": 2})


def test_cassette_roundtrip_and_layout(tmp_path):
    c = Cassette(tmp_path)
    args = {"instrumentId": "SYN_A", "idType": "INSTRUMENT_ID_TYPE_ID"}
    path = c.save("invest_get_share", args, {"instrument": {"ticker": "SYN_A", "name": "Тест"}})
    assert path.parent == tmp_path / "invest_get_share"
    assert path.name == c.key("invest_get_share", args) + ".json"
    assert c.load("invest_get_share", args) == {"instrument": {"ticker": "SYN_A", "name": "Тест"}}


def test_cassette_miss(tmp_path):
    with pytest.raises(CassetteMissError):
        Cassette(tmp_path).load("invest_get_share", {"x": 1})
