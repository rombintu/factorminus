"""Конвейер загрузки: карточки, активы, бренды, свечи, ставки риска → SQLite."""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from factorminus.db import now_iso
from factorminus.ingest.parse import (
    parse_asset,
    parse_brand,
    parse_candles,
    parse_instrument,
    parse_risk_rates,
)
from factorminus.ingest.universe import GET_TOOL, UniverseEntry, instrument_args
from factorminus.mcp.errors import CassetteMissError, McpToolError, McpTransportError

log = logging.getLogger("factorminus.ingest")

RISK_BATCH = 50
CANDLE_WINDOW_DAYS = 365
# Ошибки одной бумаги: пишутся в ingest_errors, конвейер идёт дальше.
# McpTransportError (сеть, 401/403, исчерпаны повторы) сюда не входит: она прерывает запуск.
_STEP_ERRORS = (McpToolError, CassetteMissError, ValueError, KeyError, TypeError)


def candle_windows(
    since: date, until: date, max_days: int = CANDLE_WINDOW_DAYS
) -> list[tuple[str, str]]:
    """Полуоткрытые окна [from, to) не длиннее `max_days`, покрывающие since..until включительно."""
    end = until + timedelta(days=1)
    out = []
    cur = since
    while cur < end:
        nxt = min(cur + timedelta(days=max_days), end)
        out.append((f"{cur.isoformat()}T00:00:00Z", f"{nxt.isoformat()}T00:00:00Z"))
        cur = nxt
    return out


def candle_args(instrument_id: str, frm: str, to: str) -> dict:
    return {"instrumentId": instrument_id, "interval": "CANDLE_INTERVAL_DAY", "from": frm, "to": to}


@dataclass
class IngestSummary:
    instruments: int = 0
    brands: int = 0
    candles: int = 0
    errors: int = 0
    seconds: float = 0.0
    run_id: int | None = None

    def text(self) -> str:
        return (
            f"Бумаг: {self.instruments}, брендов: {self.brands}, новых свечей: {self.candles}, "
            f"ошибок: {self.errors}, время: {self.seconds:.1f} с"
        )


_INSTRUMENT_COLS = (
    "instrument_id", "ticker", "class_code", "kind", "role", "index_id", "isin", "name", "lot",
    "currency", "asset_uid", "position_uid", "first_day_candle", "maturity_date", "dlong",
    "dshort", "api_trade_flag", "raw_json", "source", "updated_at",
)  # fmt: skip


def _upsert(conn: sqlite3.Connection, table: str, key: str, row: dict) -> None:
    cols = list(row)
    updates = ", ".join(f"{c}=excluded.{c}" for c in cols if c != key)
    conn.execute(
        f"INSERT INTO {table}({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))}) "
        f"ON CONFLICT({key}) DO UPDATE SET {updates}",
        [row[c] for c in cols],
    )


class _Run:
    def __init__(self, conn: sqlite3.Connection, client: Any, mode: str, source: str):
        self.conn = conn
        self.client = client
        self.source = source
        self.brand_cache: set[str] = set()
        self.summary = IngestSummary()
        cur = conn.execute(
            "INSERT INTO ingest_runs(started_at, source, mode) VALUES (?, ?, ?)",
            (now_iso(), source, mode),
        )
        self.run_id = cur.lastrowid
        self.summary.run_id = self.run_id

    def error(self, instrument_id: str | None, step: str, exc: BaseException | str) -> None:
        message = str(exc)[:500]
        log.warning("ingest %s %s: %s", instrument_id, step, message)
        self.conn.execute(
            "INSERT INTO ingest_errors(run_id, instrument_id, step, message) VALUES (?, ?, ?, ?)",
            (self.run_id, instrument_id, step, message),
        )
        self.summary.errors += 1

    def card(self, e: UniverseEntry) -> dict | None:
        try:
            row = parse_instrument(
                self.client.call_tool(GET_TOOL[e.kind], instrument_args(e)), e.kind
            )
        except _STEP_ERRORS as ex:
            self.error(e.id, "card", ex)
            return None
        uid = row.pop("uid")
        row.update(
            instrument_id=e.id,
            role=e.role,
            index_id=e.index,
            source=self.source,
            updated_at=now_iso(),
        )
        _upsert(self.conn, "instruments", "instrument_id", {c: row[c] for c in _INSTRUMENT_COLS})
        if uid:
            self.conn.execute("UPDATE instruments SET uid=? WHERE instrument_id=?", (uid, e.id))
        self.summary.instruments += 1
        return row

    def asset_and_brand(self, e: UniverseEntry, asset_uid: str | None) -> None:
        if not asset_uid:
            self.error(e.id, "asset", "в карточке нет assetUid")
            return
        try:
            raw = self.client.call_tool("invest_get_asset", {"id": asset_uid})
            asset = parse_asset(raw)
            asset_row = dict(asset, asset_uid=asset["asset_uid"] or asset_uid)
            asset_row["raw_json"] = _raw(raw, "asset", drop=("instruments",))
            asset_row["updated_at"] = now_iso()
            _upsert(self.conn, "assets", "asset_uid", asset_row)
        except _STEP_ERRORS as ex:
            self.error(e.id, "asset", ex)
            return
        brand_uid = asset["brand_uid"]
        if not brand_uid:
            self.error(e.id, "brand", "в активе нет brand.uid")
            return
        self.conn.execute(
            "UPDATE instruments SET brand_uid=? WHERE instrument_id=?", (brand_uid, e.id)
        )
        if brand_uid in self.brand_cache:
            return
        try:
            raw = self.client.call_tool("invest_get_brand", {"id": brand_uid})
            brand = parse_brand(raw)
            brand_row = dict(brand, brand_uid=brand["brand_uid"] or brand_uid)
            brand_row["raw_json"] = _raw(raw, "brand")
            brand_row["updated_at"] = now_iso()
            _upsert(self.conn, "brands", "brand_uid", brand_row)
        except _STEP_ERRORS as ex:
            self.error(e.id, "brand", ex)
            return
        self.brand_cache.add(brand_uid)
        self.summary.brands += 1

    def candles(
        self, e: UniverseEntry, since: date, until: date, listed: str | None = None
    ) -> None:
        first, last = self.conn.execute(
            "SELECT MIN(date), MAX(date) FROM candles WHERE instrument_id=?", (e.id,)
        ).fetchone()
        spans: list[tuple[date, date]] = []
        if last is None:
            spans.append((since, until))
        else:
            # --since раньше сохранённой истории, и бумага тогда уже торговалась
            if since < date.fromisoformat(first) and (listed is None or listed < first):
                spans.append((since, date.fromisoformat(first) - timedelta(days=1)))
            # С последней сохранённой даты, а не со следующей: свеча дня может иметь время
            # в полночь МСК (предыдущий день по UTC). Пересечение в день безопасно (UPSERT).
            if date.fromisoformat(last) < until:  # история уже до until — догружать нечего
                spans.append((date.fromisoformat(last), until))
        for start, end in spans:
            for frm, to in candle_windows(start, end):
                try:
                    rows = parse_candles(
                        self.client.call_tool("invest_get_candles", candle_args(e.id, frm, to))
                    )
                except _STEP_ERRORS as ex:
                    self.error(e.id, "candles", ex)
                    return
                self.summary.candles += self._store_candles(e.id, rows)

    def _store_candles(self, instrument_id: str, rows: list[dict]) -> int:
        count = "SELECT COUNT(*) FROM candles WHERE instrument_id=?"
        before = self.conn.execute(count, (instrument_id,)).fetchone()[0]
        self.conn.execute("BEGIN")
        try:
            self.conn.executemany(
                "INSERT INTO candles(instrument_id, date, open, high, low, close, volume) "
                "VALUES (:iid, :date, :open, :high, :low, :close, :volume) "
                "ON CONFLICT(instrument_id, date) DO UPDATE SET open=excluded.open, "
                "high=excluded.high, low=excluded.low, close=excluded.close, "
                "volume=excluded.volume",
                [dict(r, iid=instrument_id) for r in rows],
            )
            self.conn.execute("COMMIT")
        except Exception:
            self.conn.execute("ROLLBACK")
            raise
        return self.conn.execute(count, (instrument_id,)).fetchone()[0] - before

    def risk_rates(self, loaded: list[tuple[str, dict]]) -> None:
        for i in range(0, len(loaded), RISK_BATCH):
            batch = loaded[i : i + RISK_BATCH]
            ids = [iid for iid, _ in batch]
            try:
                rates = parse_risk_rates(
                    self.client.call_tool("invest_get_risk_rates", {"instrumentId": ids})
                )
            except _STEP_ERRORS as ex:
                self.error(None, "risk_rates", ex)
                continue
            if len(rates) != len(ids):
                self.error(None, "risk_rates", f"ответов {len(rates)} на {len(ids)} бумаг")
                continue
            for (iid, card), rate in zip(batch, rates, strict=True):
                self._apply_rate(iid, card, rate)

    def _apply_rate(self, iid: str, card: dict, rate: dict) -> None:
        if rate["uid"]:
            self.conn.execute(
                "UPDATE instruments SET uid=? WHERE instrument_id=?", (rate["uid"], iid)
            )
        # Уровень риска клиента определяем по совпадению long-ставки с карточкой;
        # дополняем только пустые поля карточки («если ответ богаче карточки»).
        dlong, dshort = card["dlong"], card["dshort"]
        level = next(
            (lv for lv, v in rate["long"].items() if dlong is not None and abs(v - dlong) < 1e-9),
            None,
        )
        if level and dshort is None and level in rate["short"]:
            self.conn.execute(
                "UPDATE instruments SET dshort=? WHERE instrument_id=?", (rate["short"][level], iid)
            )


def _raw(payload: Any, key: str, drop: tuple[str, ...] = ()) -> str:
    d = payload.get(key, payload) if isinstance(payload, dict) else payload
    if isinstance(d, dict) and drop:
        d = {k: v for k, v in d.items() if k not in drop}
    return json.dumps(d, ensure_ascii=False, sort_keys=True)


def run_ingest(
    conn: sqlite3.Connection,
    client: Any,
    entries: list[UniverseEntry],
    *,
    since: date,
    until: date,
    mode: str,
    source: str = "mcp",
) -> IngestSummary:
    started = time.perf_counter()
    run = _Run(conn, client, mode, source)
    s = run.summary
    notes = ""
    try:
        loaded: list[tuple[str, dict]] = []
        for e in entries:
            card = run.card(e)
            if card is None:
                continue
            loaded.append((e.id, card))
            run.asset_and_brand(e, card["asset_uid"])
            run.candles(e, since, until, listed=card["first_day_candle"])
        run.risk_rates(loaded)
    except McpTransportError as ex:
        notes = f"прерван: {ex}"
        raise
    finally:
        s.seconds = time.perf_counter() - started
        conn.execute(
            "UPDATE ingest_runs SET finished_at=?, ok_count=?, error_count=?, notes=? "
            "WHERE run_id=?",
            (now_iso(), s.instruments, s.errors, notes or None, run.run_id),
        )
    return s
