"""Дневная история индексов (IMOEX) для шоков и «худших дней рынка».

Источник — T-Invest MCP: индекс IMOEX доступен как `IMOEX_TQBR` (тип INSTRUMENT_TYPE_INDEX),
свечи с 2020-01-03. Закрытия совпадают с ISS Мосбиржи (сверено 24.11.2026 за январь 2020).
Хранение: таблица `candles`, `instrument_id = '<INDEX>_INDEX'`; источник записан в строке
`instruments` (kind='index', source, raw_json.mcp_instrument_id).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date
from typing import Any

from factorminus.db import now_iso
from factorminus.ingest.parse import parse_candles
from factorminus.ingest.pipeline import candle_args, candle_windows, store_candles

INDEX_SOURCES: dict[str, str] = {"IMOEX": "IMOEX_TQBR"}
INDEX_NAMES: dict[str, str] = {"IMOEX": "Индекс МосБиржи", "SYNIDX": "Синтетический индекс"}


def index_instrument_id(index_id: str) -> str:
    return f"{index_id}_INDEX"


def ingest_index_candles(
    conn: sqlite3.Connection,
    client: Any,
    index_id: str,
    *,
    since: date,
    until: date,
    sources: dict[str, str] | None = None,
    source: str = "mcp",
) -> int:
    """Загружает дневные свечи индекса; инкремент от последней сохранённой даты."""
    sources = INDEX_SOURCES if sources is None else sources
    if index_id not in sources:
        raise ValueError(f"Нет источника свечей для индекса {index_id!r}: {sorted(sources)}")
    mcp_id = sources[index_id]
    iid = index_instrument_id(index_id)
    conn.execute(
        "INSERT INTO instruments(instrument_id, ticker, class_code, kind, index_id, name, "
        "raw_json, source, updated_at) VALUES (?, ?, 'INDEX', 'index', ?, ?, ?, ?, ?) "
        "ON CONFLICT(instrument_id) DO UPDATE SET raw_json=excluded.raw_json, "
        "source=excluded.source, updated_at=excluded.updated_at",
        (
            iid,
            index_id,
            index_id,
            INDEX_NAMES.get(index_id, index_id),
            json.dumps({"mcp_instrument_id": mcp_id}, ensure_ascii=False),
            source,
            now_iso(),
        ),
    )
    last = conn.execute("SELECT MAX(date) FROM candles WHERE instrument_id=?", (iid,)).fetchone()[0]
    start = date.fromisoformat(last) if last else since
    if last and start >= until:
        return 0
    added = 0
    for frm, to in candle_windows(start, until):
        rows = parse_candles(client.call_tool("invest_get_candles", candle_args(mcp_id, frm, to)))
        added += store_candles(conn, iid, rows)
    return added
