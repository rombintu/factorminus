"""Белый список read-only инструментов T-Invest MCP.

Торговые, денежные и портфельные инструменты сюда не входят и не должны входить:
любой вызов вне списка отклоняется до отправки запроса.

В списке только инструменты, которые вызывает код. Новый добавляется вместе с кодом, который
его вызывает, и с live-проверкой в `tests/test_live.py` (`SMOKE_ARGS`, `SMOKE_FIELD`).
"""

from factorminus.mcp.errors import ForbiddenToolError

READ_ONLY_TOOLS: frozenset[str] = frozenset(
    {
        # карточки инструментов
        "invest_find_instrument",
        "invest_get_share",
        "invest_get_etf",
        "invest_get_bond",
        "invest_get_currency",
        # активы и бренды
        "invest_get_asset",
        "invest_get_brand",
        # рыночные данные
        "invest_get_candles",
        "invest_get_risk_rates",
    }
)


def ensure_allowed(name: str) -> None:
    if name not in READ_ONLY_TOOLS:
        raise ForbiddenToolError(name)
