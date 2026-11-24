"""Синтетический набор данных для тестов этапов 1–4.

Цены строятся из факторной модели `r_i = β_i·Market + Σ γ_ik·Factor_k + ε_i`.
Реальные тикеры не используются: все коды `SYN_*`. Даты фиксированы (500 рабочих дней
от 2024-01-02), поэтому один и тот же seed даёт побайтно один и тот же набор.
"""

from __future__ import annotations

import csv
import io
import json
import shutil
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import yaml

from factorminus.ingest.pipeline import RISK_BATCH, candle_args, candle_windows
from factorminus.ingest.universe import GET_TOOL, UniverseEntry, instrument_args
from factorminus.mcp.allowlist import READ_ONLY_TOOLS
from factorminus.mcp.cassette import Cassette
from factorminus.mcp.client import META_TOOL, TOOLS_LIST_ARGS

SYNTH_START = date(2024, 1, 2)
N_DAYS = 500
INDEX_ID = "SYNIDX"
FACTORS = ("market", "oil", "banks", "metals", "tech", "rate", "gold")
FACTOR_VOL = {
    "market": 0.012,
    "oil": 0.010,
    "banks": 0.009,
    "metals": 0.009,
    "tech": 0.012,
    "rate": 0.004,
    "gold": 0.008,
}
TRACKING_NOISE = 0.0015
FIND_ARGS_VIEW = ["IDENTIFIERS", "STATIC_DATA"]


@dataclass
class Spec:
    """Описание синтетической бумаги."""

    id: str
    kind: str  # share | etf | bond
    role: str
    name: str
    brand: str  # ключ в BRANDS
    loads: dict[str, float] = field(default_factory=dict)  # β и γ по факторам
    idio: float = 0.0
    p0: float = 100.0
    drift: float = 0.0
    history_days: int = N_DAYS
    index: str | None = None
    maturity: str | None = None
    basket: dict[str, float] | None = None  # корзина из других бумаг (доли, сумма 1)
    noise: float = TRACKING_NOISE  # шум поверх корзины
    in_universe: bool = True


# ключ -> (название, компания, сектор, описание)
BRANDS: dict[str, tuple[str, str, str, str]] = {
    "oil1": ("Синтнефть", "ПАО «Синтнефть»", "energy",
             "Вертикально интегрированная нефтяная компания: добыча и переработка нефти."),
    "oil2": ("Нефтесинт", "ПАО «Нефтесинт»", "energy",
             "Добыча нефти и газового конденсата, экспорт нефти."),
    "oil3": ("Синтгаз", "ПАО «Синтгаз»", "energy",
             "Добыча природного газа и нефти, трубопроводный экспорт."),
    "oil4": ("Северная нефть", "ПАО «Северная нефть»", "energy",
             "Нефтедобывающая компания Западной Сибири."),
    "oil5": ("Синт-Переработка", "ПАО «Синт-Переработка»", "energy",
             "Нефтепереработка и сеть АЗС, нефтехимия."),
    "bank1": ("Синтбанк", "ПАО «Синтбанк»", "financial",
              "Крупнейший универсальный банк: кредиты, вклады, платежи. "
              "Обыкновенные и привилегированные акции."),
    "bank2": ("Банк Синт-Капитал", "ПАО «Банк Синт-Капитал»", "financial",
              "Розничный и корпоративный банк."),
    "met1": ("Синтметалл", "ПАО «Синтметалл»", "materials",
             "Производство стали и металлопроката."),
    "met2": ("Синтникель", "ПАО «Синтникель»", "materials",
             "Добыча никеля, меди и металлов платиновой группы."),
    "tech1": ("Синтех", "МКПАО «Синтех»", "it",
              "Интернет-компания: поиск, такси, электронная коммерция."),
    "tech2": ("СинтСофт", "ПАО «СинтСофт»", "it", "Разработка корпоративного ПО."),
    "newco": ("Синт-Новация", "ПАО «Синт-Новация»", "it",
              "Технологическая компания, недавнее IPO."),
    "retail1": ("СинтМаркет", "ПАО «СинтМаркет»", "consumer", "Сеть продуктовых магазинов."),
    "tel1": ("СинтТелеком", "ПАО «СинтТелеком»", "telecom", "Мобильная связь и интернет."),
    "pow1": ("СинтЭнерго", "ПАО «СинтЭнерго»", "utilities", "Генерация электроэнергии."),
    "idxa": ("Синт-Капитал Индекс", "УК «Синт-Капитал»", "other",
             "Биржевой фонд повторяет индекс SYNIDX: крупнейшие акции синтетического рынка."),
    "idxb": ("Первая Синт — Индекс", "УК «Первая Синт»", "other",
             "Фонд отслеживает индекс SYNIDX полной доходности."),
    "topco": ("Синт Топ Компаний", "УК «Синт-Инвест»", "other",
              "Фонд инвестирует в акции крупнейших и наиболее ликвидных компаний рынка."),
    "divact": ("Синт Дивидендный", "УК «Синт-Актив»", "other",
               "Активно управляемый фонд дивидендных акций."),
    "gold": ("Синт Золото", "УК «Синт-Капитал»", "other", "Фонд физического золота."),
    "money": ("Синт Ликвидность", "УК «Синт-Капитал»", "other",
              "Фонд денежного рынка: сделки обратного РЕПО с ЦК."),
    "minfin": ("Минфин Синт", "Министерство финансов Синтландии", "government",
               "Государственные облигации федерального займа."),
    "absent": ("Синт-Отсутствующая", "ПАО «Синт-Отсутствующая»", "industrials",
               "Машиностроительная компания (только в каталоге MCP, нет в базе)."),
}  # fmt: skip

INDEX_WEIGHTS: dict[str, float] = {
    "SYN_OIL1": 15.0,
    "SYN_OIL2": 12.0,
    "SYN_OIL3": 8.0,
    "SYN_BANK1": 14.0,
    "SYN_BANK1P": 3.0,
    "SYN_BANK2": 6.0,
    "SYN_MET1": 8.0,
    "SYN_MET2": 5.0,
    "SYN_TECH1": 9.0,
    "SYN_TECH2": 6.0,
    "SYN_RETAIL1": 7.0,
    "SYN_TELECOM1": 4.0,
    "SYN_POWER1": 3.0,
}


def _norm(w: dict[str, float]) -> dict[str, float]:
    total = sum(w.values())
    return {k: v / total for k, v in w.items()}


def _specs() -> list[Spec]:
    s: list[Spec] = []
    oil = [(0.9, 1.0), (1.0, 0.9), (1.1, 1.1), (0.95, 0.8), (1.05, 1.0)]
    for i, (b, g) in enumerate(oil, 1):
        s.append(Spec(f"SYN_OIL{i}", "share", "share", BRANDS[f"oil{i}"][0], f"oil{i}",
                      {"market": b, "oil": g}, 0.009, 80 + 20 * i))  # fmt: skip
    s += [
        Spec("SYN_BANK1", "share", "share", "Синтбанк ао", "bank1",
             {"market": 1.1, "banks": 1.0, "rate": -0.5}, 0.007, 250),
        # префы того же эмитента: цена следует за обыкновенной акцией
        Spec("SYN_BANK1P", "share", "share", "Синтбанк ап", "bank1",
             p0=240, basket={"SYN_BANK1": 1.0}, noise=0.003),
        Spec("SYN_BANK2", "share", "share", BRANDS["bank2"][0], "bank2",
             {"market": 1.2, "banks": 0.9, "rate": -0.6}, 0.011, 0.03),
        Spec("SYN_MET1", "share", "share", BRANDS["met1"][0], "met1",
             {"market": 0.9, "metals": 1.0}, 0.009, 1500),
        Spec("SYN_MET2", "share", "share", BRANDS["met2"][0], "met2",
             {"market": 0.8, "metals": 1.1}, 0.010, 150),
        Spec("SYN_TECH1", "share", "share", BRANDS["tech1"][0], "tech1",
             {"market": 1.2, "tech": 1.0}, 0.012, 4000),
        Spec("SYN_TECH2", "share", "share", BRANDS["tech2"][0], "tech2",
             {"market": 1.1, "tech": 0.9}, 0.014, 600),
        Spec("SYN_RETAIL1", "share", "share", BRANDS["retail1"][0], "retail1",
             {"market": 0.7}, 0.010, 3000),
        Spec("SYN_TELECOM1", "share", "share", BRANDS["tel1"][0], "tel1",
             {"market": 0.6, "rate": -0.3}, 0.008, 250),
        Spec("SYN_POWER1", "share", "share", BRANDS["pow1"][0], "pow1",
             {"market": 0.6, "rate": -0.4}, 0.009, 3.5),
        Spec("SYN_NEWCO", "share", "share", BRANDS["newco"][0], "newco",
             {"market": 1.3, "tech": 1.2}, 0.02, 50, history_days=40),
        Spec("SYN_ABSENT", "share", "share", BRANDS["absent"][0], "absent",
             {"market": 1.0}, 0.012, 70, in_universe=False),
        # фонды
        Spec("SYN_IDXA", "etf", "index_fund", "Синт-Капитал Индекс SYNIDX", "idxa",
             p0=7.0, index=INDEX_ID, basket=_norm(INDEX_WEIGHTS)),
        Spec("SYN_IDXB", "etf", "index_fund", "Первая Синт — Фонд индекса SYNIDX", "idxb",
             p0=20.0, index=INDEX_ID, basket=_norm(INDEX_WEIGHTS)),
        # скрытый дубль: почти тот же индекс, в названии и описании нет слова «индекс»
        Spec("SYN_TOPCO", "etf", "active_fund", "Синт — Топ российских компаний", "topco",
             p0=150.0, basket=_norm({k: v for k, v in INDEX_WEIGHTS.items() if v >= 5})),
        # скрытая концентрация: 70% нефть и банки, состав неизвестен
        Spec("SYN_DIVACT", "etf", "active_fund", "Синт Дивидендные акции", "divact",
             p0=12.0, basket=_norm({"SYN_OIL1": 15, "SYN_OIL2": 15, "SYN_OIL4": 10,
                                    "SYN_BANK1P": 20, "SYN_BANK2": 10, "SYN_TELECOM1": 15,
                                    "SYN_POWER1": 15})),
        Spec("SYN_GOLD", "etf", "gold_fund", "Синт Золото", "gold",
             {"market": -0.05, "gold": 1.0}, 0.003, 11.0),
        Spec("SYN_MONEY", "etf", "money_fund", "Синт Ликвидность", "money",
             {}, 0.00005, 1.5, drift=0.0004),
        Spec("SYN_OFZS", "bond", "ofz", "ОФЗ Синт 2027", "minfin",
             {"rate": -0.3}, 0.0005, 98.0, drift=0.0003, maturity="2027-06-16"),
        Spec("SYN_OFZL", "bond", "ofz", "ОФЗ Синт 2041", "minfin",
             {"rate": -1.5}, 0.0008, 65.0, drift=0.0003, maturity="2041-05-15"),
    ]  # fmt: skip
    return s


def business_days(start: date, n: int) -> list[date]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


@dataclass
class SynthDataset:
    seed: int
    dates: list[date]
    specs: list[Spec]
    candles: dict[str, list[dict]]  # id -> [{date, open, high, low, close, volume}]
    manifest: dict

    @property
    def last_date(self) -> date:
        return self.dates[-1]


def generate(seed: int = 42) -> SynthDataset:
    rng = np.random.default_rng(seed)
    dates = business_days(SYNTH_START, N_DAYS)
    n = N_DAYS - 1
    f = {k: rng.normal(0.0, FACTOR_VOL[k], n) for k in FACTORS}
    specs = _specs()
    ret: dict[str, np.ndarray] = {}
    for sp in specs:  # сначала бумаги из факторов, потом корзины из них
        if sp.basket is None:
            r = np.full(n, sp.drift)
            for k, v in sp.loads.items():
                r = r + v * f[k]
            ret[sp.id] = r + rng.normal(0.0, sp.idio, n)
    for sp in specs:
        if sp.basket is not None:
            r = sum(w * ret[i] for i, w in sp.basket.items())
            ret[sp.id] = r + rng.normal(0.0, sp.noise, n)
    candles = {sp.id: _ohlc(sp, dates, ret[sp.id], rng) for sp in specs}
    return SynthDataset(seed, dates, specs, candles, _manifest(seed, dates, specs))


def _ohlc(sp: Spec, dates: list[date], r: np.ndarray, rng: np.random.Generator) -> list[dict]:
    closes = sp.p0 * np.exp(np.concatenate([[0.0], np.cumsum(r)]))
    wiggle = np.abs(rng.normal(0.0, 0.003, (len(dates), 2)))
    gap = rng.normal(0.0, 0.002, len(dates))
    volume = rng.integers(1_000, 1_000_000, len(dates))
    rows = []
    for t, d in enumerate(dates):
        c = float(closes[t])
        o = float(closes[t - 1] * (1 + gap[t])) if t else c
        rows.append(
            {
                "date": d.isoformat(),
                "open": round(o, 4),
                "high": round(max(o, c) * (1 + wiggle[t, 0]), 4),
                "low": round(min(o, c) * (1 - wiggle[t, 1]), 4),
                "close": round(c, 4),
                "volume": int(volume[t]),
            }
        )
    return rows[-sp.history_days :]


def _manifest(seed: int, dates: list[date], specs: list[Spec]) -> dict:
    oils = [f"SYN_OIL{i}" for i in range(1, 6)]
    expected: list[dict] = [
        {"type": "corr_gte", "a": "SYN_IDXA", "b": "SYN_IDXB", "value": 0.95,
         "why": "фонды-близнецы на один индекс"},
        {"type": "corr_gte", "a": "SYN_IDXA", "b": "SYN_TOPCO", "value": 0.9,
         "why": "скрытый дубль: тот же индекс без слова «индекс»"},
        {"type": "corr_gte", "a": "SYN_BANK1", "b": "SYN_BANK1P", "value": 0.85,
         "why": "обыкновенная и привилегированная акции одного эмитента"},
        {"type": "corr_lte", "a": "SYN_GOLD", "b": "SYN_IDXA", "value": 0.1,
         "why": "золото не связано с рынком акций"},
        {"type": "vol_lte", "a": "SYN_MONEY", "value": 0.001,
         "why": "фонд денежного рынка почти без волатильности"},
        {"type": "corr_gte", "a": "SYN_OFZS", "b": "SYN_OFZL", "value": 0.5,
         "why": "обе ОФЗ зависят от фактора ставки"},
        {"type": "vol_gt", "a": "SYN_OFZL", "b": "SYN_OFZS",
         "why": "длинная ОФЗ чувствительнее к ставке"},
        {"type": "corr_gte", "a": "SYN_DIVACT", "b": "SYN_OIL1", "value": 0.6,
         "why": "активный фонд на 70% из нефти и банков"},
        {"type": "history_days_eq", "a": "SYN_NEWCO", "value": 40,
         "why": "короткая история: флаг description_based"},
        {"type": "not_in_universe", "a": "SYN_ABSENT",
         "why": "есть только в каталоге MCP: флаг preliminary"},
    ]  # fmt: skip
    for i, a in enumerate(oils):
        for b in oils[i + 1 :]:
            expected.append({"type": "corr_between", "a": a, "b": b, "low": 0.6, "high": 0.8,
                             "why": "нефтяные акции"})  # fmt: skip
    return {
        "seed": seed,
        "generator": "factorminus.synth.generator",
        "params": {
            "start": dates[0].isoformat(),
            "end": dates[-1].isoformat(),
            "n_days": len(dates),
            "factors": FACTOR_VOL,
            "tracking_noise": TRACKING_NOISE,
            "index_id": INDEX_ID,
        },
        "instruments": [
            {
                "id": sp.id,
                "kind": sp.kind,
                "role": sp.role,
                "index": sp.index,
                "brand": BRANDS[sp.brand][0],
                "sector": BRANDS[sp.brand][2],
                "loads": sp.loads,
                "basket": {k: round(v, 6) for k, v in sp.basket.items()} if sp.basket else None,
                "history_days": sp.history_days,
                "in_universe": sp.in_universe,
            }
            for sp in specs
        ],
        "index_weights": {INDEX_ID: INDEX_WEIGHTS},
        "expected": expected,
    }


# --- запись на диск ---


def _q(x: float) -> dict:
    """Число в формате ответов MCP (проверено 24.11.2026: `{"value": "0.125"}`)."""
    return {"value": f"{x:.4f}"}


def _uid(prefix: str, key: str) -> str:
    return f"syn-{prefix}-{key.lower().replace('_', '-')}"


def _card(sp: Spec) -> dict:
    d: dict = {
        "ticker": sp.id,
        "classCode": "SYN",
        "isin": ("SY" + sp.id[4:]).ljust(12, "0")[:12],
        "name": sp.name,
        "lot": 10 if sp.kind == "share" else 1,
        "currency": "rub",
        "assetUid": _uid("asset", sp.id),
        "positionUid": _uid("pos", sp.id),
        "dlongClient": {"value": "0.2"},
        "apiTradeAvailableFlag": sp.kind == "share",
        "exchange": "SYN",
    }
    first = business_days(SYNTH_START, N_DAYS)[-sp.history_days]
    d["first1dayCandleDate"] = f"{first.isoformat()}T07:00:00Z"
    if sp.kind == "bond":
        d["maturityDate"] = sp.maturity
    return {"instrument": d}


def _entries(specs: list[Spec]) -> list[UniverseEntry]:
    return [
        UniverseEntry(id=sp.id, kind=sp.kind, role=sp.role, index=sp.index, note=sp.name)
        for sp in specs
        if sp.in_universe
    ]


def _dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=1) + "\n"


def _csv(header: list[str], rows: list[list]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    w.writerows(rows)
    return buf.getvalue()


def write_dataset(ds: SynthDataset, out: Path | str) -> None:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    if any(out.iterdir()) and not (out / "manifest.json").exists():
        raise ValueError(f"{out} не пуст и не похож на синтетический набор: не перезаписываю")
    by_id = {sp.id: sp for sp in ds.specs}
    brands = {
        key: {"uid": _uid("brand", key), "name": b[0], "company": b[1], "sector": b[2],
              "description": b[3], "countryOfRisk": "SY"}
        for key, b in BRANDS.items()
    }  # fmt: skip
    instruments = [
        _card(sp)["instrument"]
        | {"role": sp.role, "index": sp.index, "brandUid": brands[sp.brand]["uid"]}
        for sp in ds.specs
    ]
    (out / "instruments.json").write_text(_dump(instruments), encoding="utf-8")
    (out / "brands.json").write_text(_dump(brands), encoding="utf-8")
    candle_rows = [
        [sp.id, c["date"], c["open"], c["high"], c["low"], c["close"], c["volume"]]
        for sp in ds.specs
        if sp.in_universe
        for c in ds.candles[sp.id]
    ]
    (out / "candles.csv").write_text(
        _csv(["instrument_id", "date", "open", "high", "low", "close", "volume"], candle_rows),
        encoding="utf-8",
    )
    weight_rows = [
        [INDEX_ID, ds.last_date.isoformat(), t, t, by_id[t].name, f"{w:.2f}"]
        for t, w in INDEX_WEIGHTS.items()
    ]
    (out / "index_weights.csv").write_text(
        _csv(["index_id", "trade_date", "ticker", "secids", "shortname", "weight"], weight_rows),
        encoding="utf-8",
    )
    (out / "manifest.json").write_text(_dump(ds.manifest), encoding="utf-8")
    entries = _entries(ds.specs)
    (out / "universe.yaml").write_text(
        "# Синтетическая вселенная (генерируется: fm synth generate)\n"
        + yaml.safe_dump(
            [e.model_dump(exclude_none=True) for e in entries], allow_unicode=True, sort_keys=False
        ),
        encoding="utf-8",
    )
    _write_cassettes(ds, out / "cassettes", brands, entries)


def _write_cassettes(
    ds: SynthDataset, root: Path, brands: dict, entries: list[UniverseEntry]
) -> None:
    if root.exists():
        if root.name != "cassettes" or not (root.parent / "manifest.json").exists():
            raise ValueError(f"Отказ удалять {root}: это не каталог кассет синтетического набора")
        shutil.rmtree(root)
    cas = Cassette(root)
    by_id = {sp.id: sp for sp in ds.specs}
    windows = candle_windows(SYNTH_START, ds.last_date)
    for sp in ds.specs:
        e = UniverseEntry(id=sp.id, kind=sp.kind, role=sp.role, index=sp.index)
        card = _card(sp)
        cas.save(GET_TOOL[sp.kind], instrument_args(e), card)
        if not sp.in_universe:
            item = {k: card["instrument"][k] for k in ("ticker", "classCode", "isin", "name")}
            find_args = {"query": sp.id, "responseView": FIND_ARGS_VIEW}
            cas.save("invest_find_instrument", find_args, {"instruments": [item]})
            continue
        b = brands[sp.brand]
        asset = {
            "uid": _uid("asset", sp.id),
            "name": f"{b['company']}: {sp.name}",
            "type": "ASSET_TYPE_SECURITY",
            "brand": {"uid": b["uid"]},
            "instruments": [{"ticker": sp.id, "classCode": "SYN"}],
        }
        cas.save("invest_get_asset", {"id": asset["uid"]}, {"asset": asset})
        cas.save("invest_get_brand", {"id": b["uid"]}, {"brand": b})
        for frm, to in windows:
            lo, hi = frm[:10], to[:10]
            rows = [c for c in ds.candles[sp.id] if lo <= c["date"] < hi]
            payload = {
                "priceCurrency": "rub",
                "candles": [
                    {"time": c["date"], "open": _q(c["open"]), "high": _q(c["high"]),
                     "low": _q(c["low"]), "close": _q(c["close"]), "volume": str(c["volume"]),
                     "isComplete": True, "candleSource": "CANDLE_SOURCE_EXCHANGE"}
                    for c in rows
                ],
            }  # fmt: skip
            cas.save("invest_get_candles", candle_args(sp.id, frm, to), payload)
    ids = [e.id for e in entries]
    for i in range(0, len(ids), RISK_BATCH):
        batch = ids[i : i + RISK_BATCH]
        cas.save(
            "invest_get_risk_rates",
            {"instrumentId": batch},
            {"instrumentRiskRates": [_risk(by_id[x]) for x in batch]},
        )
    cas.save(META_TOOL, TOOLS_LIST_ARGS, sorted(READ_ONLY_TOOLS))


def _risk(sp: Spec) -> dict:
    return {
        "instrumentUid": _uid("uid", sp.id),
        "longRiskRates": [
            {"riskLevelCode": "STANDARD", "value": {"value": "0.2"}},
            {"riskLevelCode": "HIGH", "value": {"value": "0.125"}},
        ],
        "shortRiskRates": [
            {"riskLevelCode": "STANDARD", "value": {"value": "0.3"}},
            {"riskLevelCode": "HIGH", "value": {"value": "0.15"}},
        ],
    }
