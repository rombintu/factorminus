"""Публичный ISS Мосбиржи: веса индекса (без токена)."""

from __future__ import annotations

import re
import sqlite3
import ssl

import httpx

ISS_URL = (
    "https://iss.moex.com/iss/statistics/engines/stock/markets/index/analytics/"
    "{index}.json?iss.meta=off&limit=100"
)


INDEX_ID_RE = re.compile(r"^[A-Z0-9]{2,12}$")


def parse_iss_analytics(payload: dict) -> list[dict]:
    try:
        block = payload["analytics"]
        cols = block["columns"]
        data = block["data"]
    except (KeyError, TypeError) as e:
        raise ValueError("Неожиданный формат ответа ISS: нет analytics.columns/data") from e
    rows = []
    for raw in data:
        r = dict(zip(cols, raw, strict=False))
        try:
            rows.append(
                {
                    "trade_date": r["tradedate"],
                    "ticker": r["ticker"],
                    "secids": r.get("secids"),
                    "shortname": r.get("shortnames"),
                    "weight": float(r["weight"]),
                }
            )
        except (KeyError, TypeError, ValueError) as e:
            raise ValueError(f"Неожиданный формат строки ISS: {e!r}") from e
    return rows


def fetch_index_weights(
    index_id: str,
    *,
    verify: ssl.SSLContext | bool = True,
    transport: httpx.BaseTransport | None = None,
    timeout: float = 30.0,
) -> list[dict]:
    """Веса индекса на последнюю доступную дату. ISS отдаёт до 100 строк за запрос."""
    if not INDEX_ID_RE.match(index_id):
        raise ValueError(f"Код индекса {index_id!r}: ожидаются заглавные буквы и цифры")
    rows: list[dict] = []
    start = 0
    with httpx.Client(timeout=timeout, verify=verify, transport=transport) as http:
        while True:
            resp = http.get(ISS_URL.format(index=index_id) + f"&start={start}")
            resp.raise_for_status()
            page = parse_iss_analytics(resp.json())
            rows.extend(page)
            if len(page) < 100:
                return rows
            start += len(page)


def store_index_weights(conn: sqlite3.Connection, index_id: str, rows: list[dict]) -> int:
    conn.execute("BEGIN")
    try:
        conn.executemany(
            "INSERT INTO index_weights(index_id, trade_date, ticker, secids, shortname, weight) "
            "VALUES (:index_id, :trade_date, :ticker, :secids, :shortname, :weight) "
            "ON CONFLICT(index_id, trade_date, ticker) DO UPDATE SET "
            "secids=excluded.secids, shortname=excluded.shortname, weight=excluded.weight",
            [dict(r, index_id=index_id) for r in rows],
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return len(rows)
