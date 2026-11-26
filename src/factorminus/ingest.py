"""Загрузка вселенной бумаг из MCP: карточка → актив → бренд → свечи → ставки риска."""

import csv
import json
import time
from datetime import UTC, date, datetime
from pathlib import Path

from . import db

UNIVERSE = Path(__file__).with_name("universe.csv")
CARD_TOOLS = {
    "share": "invest_get_share",
    "etf": "invest_get_etf",
    "bond": "invest_get_bond",
    "currency": "invest_get_currency",
}
MAX_WINDOW_DAYS = 700  # окно from/to для дневных свечей не больше 2 лет
RISK_BATCH = 50
RISK_LEVEL = "STANDARD"  # уровень риска клиента для ставок, если в карточке пусто


def num(v):
    """Число MCP: {"units","nano"}, {"value"}, строка или число."""
    if v is None or v == "":
        return None
    if isinstance(v, dict):
        if "value" in v:
            return num(v["value"])
        if "units" in v or "nano" in v:
            return int(v.get("units") or 0) + int(v.get("nano") or 0) / 1e9
        return None
    return float(v)


def load_universe(path: Path = UNIVERSE, only: set[str] | None = None) -> list[dict]:
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    return [r for r in rows if not only or r["id"] in only]


def run(mcp, conn, rows, since="2020-01-01", log=print) -> dict:
    """Загрузить бумаги. Ошибка на одной бумаге попадает в сводку и не останавливает загрузку."""
    started = time.monotonic()
    summary = {"instruments": 0, "brands": 0, "candles": 0, "errors": []}
    known_brands = {r[0] for r in conn.execute("SELECT uid FROM brands")}
    loaded = []
    for row in rows:
        try:
            if row["kind"] == "index":
                save_index(conn, row)
            else:
                summary["brands"] += load_instrument(mcp, conn, row, known_brands)
                loaded.append(row["id"])  # у индекса нет ставок риска
            summary["candles"] += load_candles(mcp, conn, row["id"], since)
            summary["instruments"] += 1
            log(f"  {row['id']}: ok")
        except Exception as e:  # noqa: BLE001 — любая ошибка бумаги идёт в сводку
            summary["errors"].append(f"{row['id']}: {e}")
            log(f"  {row['id']}: ошибка: {e}")
        conn.commit()
    try:
        fill_risk_rates(mcp, conn, loaded)
    except Exception as e:  # noqa: BLE001
        summary["errors"].append(f"ставки риска: {e}")
    conn.commit()
    summary["seconds"] = round(time.monotonic() - started, 1)
    return summary


def load_instrument(mcp, conn, row, known_brands) -> int:
    """Карточка, актив и бренд. Возвращает число новых брендов (0 или 1)."""
    args = {"instrumentId": row["id"], "idType": "INSTRUMENT_ID_TYPE_ID", "responseView": ["FULL"]}
    card = mcp.call(CARD_TOOLS[row["kind"]], args)
    inst = card.get("instrument", card)
    asset = {}
    if inst.get("assetUid"):
        asset = mcp.call("invest_get_asset", {"id": inst["assetUid"]}).get("asset", {})
    brand_uid = (asset.get("brand") or {}).get("uid") or None
    new_brand = 0
    if brand_uid and brand_uid not in known_brands:
        save_brand(conn, mcp.call("invest_get_brand", {"id": brand_uid}))
        known_brands.add(brand_uid)
        new_brand = 1
    company = conn.execute("SELECT company FROM brands WHERE uid=?", (brand_uid,)).fetchone()
    db.upsert(conn, "instruments", {
        "id": row["id"], "ticker": inst.get("ticker"), "class_code": inst.get("classCode"),
        "kind": row["kind"], "role": row["role"], "index_id": row.get("index") or None,
        "name": inst.get("name"), "asset_name": asset.get("name"), "isin": inst.get("isin"),
        "lot": inst.get("lot"), "currency": inst.get("currency"),
        "asset_uid": inst.get("assetUid"), "brand_uid": brand_uid, "uid": inst.get("uid"),
        "issuer": issuer(row, company[0] if company else None),
        "first_candle": day(inst.get("first1dayCandleDate")), "maturity": day(inst.get("maturityDate")),
        "dlong": num(inst.get("dlongClient")), "dshort": num(inst.get("dshortClient")),
        "source": "mcp", "raw_json": json.dumps(card, ensure_ascii=False), "updated_at": now(),
    })  # fmt: skip
    return new_brand


def save_index(conn, row) -> None:
    """Индекс: карточки, бренда и ставок риска нет, только строка и свечи."""
    db.upsert(conn, "instruments", {
        "id": row["id"], "ticker": row["id"].split("_")[0], "kind": "index", "role": row["role"],
        "index_id": row["index"], "name": row["note"], "source": "mcp", "updated_at": now(),
    })  # fmt: skip


def issuer(row, company: str | None) -> str | None:
    """Кто несёт риск: ручное значение из universe.csv, иначе компания бренда у акций и облигаций."""
    name = row.get("issuer") or (company if row["kind"] in ("share", "bond") else None)
    return " ".join(name.split()) or None if name else None


def save_brand(conn, brand: dict) -> None:
    b = brand.get("brand", brand)
    db.upsert(conn, "brands", {
        "uid": b["uid"], "name": b.get("name"), "company": b.get("company"),
        "sector": b.get("sector") or None, "description": b.get("description"),
        "country": b.get("countryOfRisk"), "source": "mcp",
        "raw_json": json.dumps(brand, ensure_ascii=False), "updated_at": now(),
    })  # fmt: skip


def load_candles(mcp, conn, iid: str, since: str) -> int:
    """Дневные свечи с since; при повторном запуске только с последнего сохранённого дня."""
    last = conn.execute("SELECT max(date) FROM candles WHERE instrument_id=?", (iid,)).fetchone()[0]
    args = {"instrumentId": iid, "interval": "CANDLE_INTERVAL_DAY", "to": now()}
    if last and (date.today() - date.fromisoformat(last)).days < MAX_WINDOW_DAYS:
        args["from"] = f"{last}T00:00:00Z"  # последний день перезаписывается: мог быть неполным
    else:
        args["limit"] = 2400
    rows = []
    for c in mcp.call("invest_get_candles", args).get("candles", []):
        d = day(c["time"])
        if d >= since:
            prices = [num(c.get(k)) for k in ("open", "high", "low", "close")]
            rows.append((iid, d, *prices, num(c.get("volume"))))
    conn.executemany("INSERT OR REPLACE INTO candles VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
    return sum(1 for r in rows if not last or r[1] > last)


def fill_risk_rates(mcp, conn, ids: list[str]) -> None:
    """uid и ставки риска. Ответ идёт в порядке запроса и без instrumentId."""
    for i in range(0, len(ids), RISK_BATCH):
        chunk = ids[i : i + RISK_BATCH]
        rates = mcp.call("invest_get_risk_rates", {"instrumentId": chunk})["instrumentRiskRates"]
        if len(rates) != len(chunk):
            raise ValueError(f"ставок риска {len(rates)}, а бумаг {len(chunk)}")
        for iid, r in zip(chunk, rates):
            conn.execute(
                "UPDATE instruments SET uid = coalesce(uid, ?), dlong = coalesce(dlong, ?), "
                "dshort = coalesce(dshort, ?) WHERE id = ?",
                (r.get("instrumentUid") or None, level_rate(r.get("longRiskRates")),
                 level_rate(r.get("shortRiskRates")), iid),
            )  # fmt: skip


def level_rate(rates) -> float | None:
    for r in rates or []:
        if r.get("riskLevelCode") == RISK_LEVEL:
            return num(r.get("value"))
    return None


def day(value: str | None) -> str | None:
    return value[:10] if value else None


def now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
