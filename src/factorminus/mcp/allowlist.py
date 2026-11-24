"""Белый список read-only инструментов T-Invest MCP.

Торговые, денежные и портфельные инструменты сюда не входят и не должны входить:
любой вызов вне списка отклоняется до отправки запроса.
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
        "invest_get_asset_fundamentals",
        # рыночные данные
        "invest_get_candles",
        "invest_get_risk_rates",
        "invest_get_market_values",
        "invest_get_trading_statuses",
        "invest_get_news",
        # каталоги
        "invest_list_shares",
        "invest_list_etfs",
        "invest_list_bonds",
    }
)


def ensure_allowed(name: str) -> None:
    if name not in READ_ONLY_TOOLS:
        raise ForbiddenToolError(name)
