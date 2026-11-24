"""Разбор ответов T-Invest MCP: Quotation, MoneyValue, даты, карточки, свечи.

Разбор терпим к обёртке: принимает и `{"instrument": {...}}`, и сам объект.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

MSK = timezone(timedelta(hours=3), "MSK")
NANO = 1_000_000_000


def to_float(v: Any) -> float | None:
    """`{"value": "0.125"}`, `{"units": "3", "nano": 500000000}`, строка, число, None."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, int | float):
        return float(v)
    if isinstance(v, str):
        s = v.strip().replace(",", ".")
        if not s:
            return None
        return float(s)  # ValueError на мусоре — намеренно
    if isinstance(v, dict):
        if "value" in v:
            return to_float(v["value"])
        if "units" in v or "nano" in v:
            units = int(v.get("units") or 0)
            nano = int(v.get("nano") or 0)
            return units + nano / NANO
        return None
    raise ValueError(f"Неизвестный формат числа: {type(v).__name__}")


def to_msk_date(ts: str | None) -> str | None:
    """ISO-время → дата `YYYY-MM-DD` по Москве."""
    if not ts:
        return None
    if len(ts) == 10:
        return ts
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(MSK).date().isoformat()


def _unwrap(payload: Any, key: str) -> dict:
    if isinstance(payload, dict) and isinstance(payload.get(key), dict):
        return payload[key]
    if isinstance(payload, dict):
        return payload
    raise ValueError(f"Ожидался объект {key}, получено {type(payload).__name__}")


def _first(d: dict, *keys: str) -> Any:
    for k in keys:
        if d.get(k) is not None:
            return d[k]
    return None


def _flag(v: Any) -> int | None:
    return None if v is None else int(bool(v))


def parse_instrument(payload: Any, kind: str) -> dict:
    """Карточка `get_share|get_etf|get_bond|get_currency` → поля таблицы `instruments`."""
    d = _unwrap(payload, "instrument")
    if not d.get("ticker"):
        raise ValueError("В карточке инструмента нет ticker")
    lot = d.get("lot")
    return {
        "ticker": d["ticker"],
        "class_code": d.get("classCode") or "",
        "kind": kind,
        "uid": d.get("uid"),
        "isin": d.get("isin") or None,
        "name": d.get("name"),
        "lot": int(lot) if lot is not None else None,
        "currency": d.get("currency"),
        "asset_uid": d.get("assetUid") or None,
        "position_uid": d.get("positionUid") or None,
        "first_day_candle": to_msk_date(_first(d, "first1dayCandleDate", "first1DayCandleDate")),
        "maturity_date": to_msk_date(d.get("maturityDate")) if kind == "bond" else None,
        "dlong": to_float(_first(d, "dlongClient", "dlong")),
        "dshort": to_float(_first(d, "dshortClient", "dshort")),
        "api_trade_flag": _flag(d.get("apiTradeAvailableFlag")),
        "raw_json": json.dumps(d, ensure_ascii=False, sort_keys=True),
    }


def parse_asset(payload: Any) -> dict:
    d = _unwrap(payload, "asset")
    brand = d.get("brand") or {}
    return {
        "asset_uid": d.get("uid"),
        "name": d.get("name"),
        "brand_uid": (brand.get("uid") if isinstance(brand, dict) else None) or d.get("brandUid"),
    }


def parse_brand(payload: Any) -> dict:
    d = _unwrap(payload, "brand")
    return {
        "brand_uid": d.get("uid"),
        "name": d.get("name"),
        "company": d.get("company"),
        "sector": d.get("sector") or None,
        "description": _first(d, "description", "info"),
        "country_of_risk": _first(d, "countryOfRisk", "countryOfRiskName"),
    }


def parse_candles(payload: Any) -> list[dict]:
    """Дневные свечи; свечи без цены закрытия пропускаются."""
    items = payload.get("candles", []) if isinstance(payload, dict) else payload or []
    rows = []
    for c in items:
        close = to_float(c.get("close"))
        date = to_msk_date(c.get("time"))
        if close is None or date is None:
            continue
        rows.append(
            {
                "date": date,
                "open": to_float(c.get("open")),
                "high": to_float(c.get("high")),
                "low": to_float(c.get("low")),
                "close": close,
                "volume": to_float(c.get("volume")),
            }
        )
    return rows


def _rate(v: Any) -> float | None:
    if isinstance(v, dict) and "value" in v:
        return to_float(v["value"])
    return to_float(v)


def parse_risk_rates(payload: Any) -> dict[str, tuple[float | None, float | None]]:
    """`{instrumentUid: (long, short)}`."""
    items = payload.get("instrumentRiskRates", []) if isinstance(payload, dict) else payload or []
    out: dict[str, tuple[float | None, float | None]] = {}
    for r in items:
        uid = _first(r, "instrumentUid", "instrumentId", "uid")
        if uid:
            out[uid] = (_rate(r.get("longRiskRate")), _rate(r.get("shortRiskRate")))
    return out
