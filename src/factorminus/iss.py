"""Веса индекса Мосбиржи (IMOEX) из публичного ISS, без токена."""

import httpx

from . import config

URL = "https://iss.moex.com/iss/statistics/engines/stock/markets/index/analytics/IMOEX.json"


def fetch_weights(transport=None) -> list[tuple]:
    """Строки (index_id, date, ticker, weight) за последнюю дату расчёта."""
    params = {"iss.meta": "off", "limit": 100}
    verify = config.tls_context()
    with httpx.Client(timeout=30, verify=verify, transport=transport) as client:
        resp = client.get(URL, params=params)
        resp.raise_for_status()
    block = resp.json()["analytics"]
    rows = [dict(zip(block["columns"], r)) for r in block["data"]]
    return [("IMOEX", r["tradedate"], r["ticker"], float(r["weight"])) for r in rows]


def save_weights(conn, rows: list[tuple]) -> int:
    conn.executemany("INSERT OR REPLACE INTO index_weights VALUES (?, ?, ?, ?)", rows)
    conn.commit()
    return len(rows)
