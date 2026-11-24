"""Синтетический набор данных для тестов этапов 1–4.

Цены строятся из факторной модели `r_i = β_i·Market + Σ γ_ik·Factor_k + ε_i`.
Реальные тикеры не используются: все коды `SYN_*`. Даты фиксированы (1500 рабочих дней
от 2020-01-02, около 6 лет), поэтому один и тот же seed даёт побайтно один и тот же набор.

В ряд встроены шоки: три эпизода (SHOCK_A, SHOCK_B, SHOCK_C) и отдельные дни резкого падения.
В шоки рынок падает с повышенной волатильностью, и у каждого сектора (нефть, банки, металлы,
технологии) появляется общий стресс-фактор: корреляции внутри секторов растут. Так устроен
контрпример эксперта: «синтетический Сбер» (SYN_BANK1) и «синтетический ВТБ» (SYN_BANK2)
слабо связаны в обычные дни и сильно в шоки, а в спокойные годы один растёт, другой падает.
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

SYNTH_START = date(2020, 1, 2)
N_DAYS = 1500
INDEX_ID = "SYNIDX"
FACTORS = ("market", "oil", "banks", "metals", "tech", "rate", "gold", "group")
FACTOR_VOL = {
    "market": 0.012,
    "oil": 0.010,
    "banks": 0.009,
    "metals": 0.009,
    "tech": 0.012,
    "rate": 0.004,
    "gold": 0.008,
    "group": 0.008,  # общий фактор группы компаний «Синт-Система»
}
MARKET_DRIFT = 0.0003
STRESS_SECTORS = ("oil", "banks", "metals", "tech")
# (id, первый день ряда доходностей, длина, средняя доходность рынка, вол. рынка, вол. стресса)
SHOCKS: tuple[tuple[str, int, int, float, float, float], ...] = (
    ("SHOCK_A", 40, 30, -0.012, 0.035, 0.025),
    ("SHOCK_B", 560, 20, -0.015, 0.040, 0.030),
    ("SHOCK_C", 1100, 150, -0.0025, 0.015, 0.012),  # затяжное плавное снижение
)
N_DROP_DAYS = 12
DROP_MEAN, DROP_VOL, DROP_STRESS = -0.045, 0.01, 0.025
TRACKING_NOISE = 0.0015
FIND_ARGS_VIEW = ["IDENTIFIERS", "STATIC_DATA"]
INDEX_MCP_ID = "SYNIDX_SYN"  # «MCP-идентификатор» синтетического индекса (как IMOEX_TQBR)
INDEX_LEVEL0 = 1000.0
# Особенности реальных данных, которые синтетика воспроизводит (ТЗ правок этапа 1, п. 2)
WEEKEND_IDS = ("SYN_BANK1", "SYN_OIL1", "SYN_TECH2")  # торги выходного дня
WEEKEND_FROM_DAY = 1200  # с какого рабочего дня ряда появляются свечи выходных
INCOMPLETE_LAST_ID = "SYN_TECH2"  # последняя свеча в кассете с isComplete=false


@dataclass
class Spec:
    """Описание синтетической бумаги."""

    id: str
    kind: str  # share | etf | bond
    role: str
    name: str
    brand: str | None  # ключ в BRANDS; None — у актива нет бренда
    loads: dict[str, float] = field(default_factory=dict)  # β и γ по факторам
    idio: float = 0.0
    p0: float = 100.0
    drift: float = 0.0
    calm_drift: float = 0.0  # дополнительный дрейф только в обычные дни
    history_days: int = N_DAYS
    index: str | None = None
    maturity: str | None = None
    basket: dict[str, float] | None = None  # корзина из других бумаг (доли, сумма 1)
    noise: float = TRACKING_NOISE  # шум поверх корзины
    in_universe: bool = True
    issuer: str | None = None  # ручной эмитент в universe.yaml (облигации через «дочку»)


# ключ -> (название бренда, company, сектор, описание). Как в реальном MCP: у бумаг одного
# эмитента бренды разные (ао/ап, акция/облигация), общая у них company; у фондов company —
# управляющая компания; у части фондов сектор пустой.
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
    "bank1": ("Синтбанк ао", "ПАО «Синтбанк»", "financial",
              "Крупнейший универсальный банк: кредиты, вклады, платежи."),
    "bank1p": ("Синтбанк ап", "ПАО «Синтбанк»", "financial",
               "Привилегированные акции крупнейшего универсального банка."),
    "bank2": ("Банк Синт-Капитал", "ПАО «Банк Синт-Капитал»", "financial",
              "Второй по величине государственный банк: розничный и корпоративный бизнес."),
    "grp": ("Синт-Система", "ПАО АФК «Синт-Система»", "financial",
            "Инвестиционный холдинг: телеком, лесопереработка, девелопмент."),
    "grptel": ("СинтМобайл ао", "ПАО «СинтМобайл»", "telecom",
               "Мобильная связь и цифровые сервисы."),
    "grptel_b": ("СинтМобайл", "ПАО «СинтМобайл»", "telecom",
                 "Облигации оператора мобильной связи."),
    "grpfor": ("СинтЛес", "ПАО «СинтЛес»", "materials",
               "Лесопромышленная компания: пиломатериалы, бумага, фанера."),
    "grpdev": ("СинтСтрой", "ПАО «СинтСтрой»", "real_estate",
               "Девелопер жилой недвижимости."),
    "grpdevfin": ("СинтСтрой-Финанс", "ООО «СинтСтрой-Финанс»", "real_estate",
                  "Финансовая компания группы СинтСтрой: выпуск облигаций."),
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
    "gold": ("Синт Золото", "УК «Синт-Капитал»", "", "Фонд физического золота."),
    "money": ("Синт Ликвидность", "УК «Синт-Капитал»", "",
              "Фонд денежного рынка: сделки обратного РЕПО с ЦК."),
    "bondf": ("Синт Облигации", "УК «Синт-Капитал»", "",
              "Фонд государственных и корпоративных облигаций."),
    "minfin": ("Минфин Синт", "Министерство финансов Синтландии", "government",
               "Государственные облигации федерального займа."),
    "absent": ("Синт-Отсутствующая", "ПАО «Синт-Отсутствующая»", "industrials",
               "Машиностроительная компания (только в каталоге MCP, нет в базе)."),
}  # fmt: skip

# Группа компаний (слой 3): материнская компания и дочерние, включая облигации дочек.
GROUPS: tuple[dict, ...] = (
    {
        "name": "Синт-Система",
        "type": "ownership",
        "parent_brand": "Синт-Система",
        "member_brands": [
            "СинтМобайл ао",
            "СинтМобайл",
            "СинтЛес",
            "СинтСтрой",
            "СинтСтрой-Финанс",
        ],
        "instruments": ["SYN_GRP", "SYN_GRPTEL", "SYN_GRPTEL_B", "SYN_GRPFOR_B", "SYN_GRPDEV_B"],
    },
)

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
        # «синтетический Сбер»: в спокойные годы растёт
        Spec("SYN_BANK1", "share", "share", "Синтбанк ао", "bank1",
             {"market": 1.1, "banks": 1.0, "rate": -0.5}, 0.008, 250, calm_drift=0.0006),
        # префы того же эмитента: цена следует за обыкновенной акцией
        Spec("SYN_BANK1P", "share", "share", "Синтбанк ап", "bank1p",
             p0=240, basket={"SYN_BANK1": 1.0}, noise=0.003),
        # «синтетический ВТБ»: в спокойные годы падает
        Spec("SYN_BANK2", "share", "share", BRANDS["bank2"][0], "bank2",
             {"market": 1.1, "banks": 1.0, "rate": -0.6}, 0.008, 0.03, calm_drift=-0.0007),
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
        # группа «Синт-Система»
        Spec("SYN_GRP", "share", "share", "Синт-Система ао", "grp",
             {"market": 1.0, "group": 1.0}, 0.012, 15.0),
        Spec("SYN_GRPTEL", "share", "share", "СинтМобайл ао", "grptel",
             {"market": 0.6, "group": 0.6, "rate": -0.3}, 0.008, 230.0),
        Spec("SYN_GRPTEL_B", "bond", "corp_bond", "СинтМобайл 001P-02", "grptel_b",
             {"rate": -0.6, "group": 0.15}, 0.001, 98.0, drift=0.0003, maturity="2028-11-15"),
        Spec("SYN_GRPFOR_B", "bond", "corp_bond", "СинтЛес 002P-01", "grpfor",
             {"rate": -0.6, "group": 0.3}, 0.002, 90.0, drift=0.0004, maturity="2029-03-10"),
        # выпуск через финансовую «дочку»: company «СинтСтрой-Финанс», эмитент риска — СинтСтрой
        Spec("SYN_GRPDEV_B", "bond", "corp_bond", "СинтСтрой-Финанс 002P-01", "grpdevfin",
             {"rate": -0.6, "group": 0.25}, 0.0015, 95.0, drift=0.0004, maturity="2028-02-03",
             issuer="ПАО «СинтСтрой»"),
        Spec("SYN_NEWCO", "share", "share", BRANDS["newco"][0], "newco",
             {"market": 1.3, "tech": 1.2}, 0.02, 50, history_days=40),
        Spec("SYN_ABSENT", "share", "share", BRANDS["absent"][0], "absent",
             {"market": 1.0}, 0.012, 70, in_universe=False),
        # фонды
        Spec("SYN_IDXA", "etf", "index_fund", "Синт-Капитал Индекс SYNIDX", "idxa",
             p0=7.0, index=INDEX_ID, basket=_norm(INDEX_WEIGHTS)),
        # моложе SHOCK_A: история с 200-го рабочего дня (правило «до запуска — по индексу»)
        Spec("SYN_IDXB", "etf", "index_fund", "Первая Синт — Фонд индекса SYNIDX", "idxb",
             p0=20.0, index=INDEX_ID, basket=_norm(INDEX_WEIGHTS), history_days=N_DAYS - 200),
        # фонд без бренда (как AMIX): у актива нет brand.uid
        Spec("SYN_IDXC", "etf", "index_fund", "Синт-Атон Индекс SYNIDX", None,
             p0=1.0, index=INDEX_ID, basket=_norm(INDEX_WEIGHTS), history_days=200),
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
        Spec("SYN_BONDF", "etf", "bond_fund", "Синт Облигации", "bondf",
             p0=10.0, basket={"SYN_OFZS": 0.5, "SYN_OFZL": 0.3, "SYN_GRPTEL_B": 0.2},
             noise=0.0005),
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
    index_candles: list[dict] = field(default_factory=list)  # SYNIDX: дневные закрытия

    def stored_candles(self, iid: str) -> list[dict]:
        """Свечи, которые корректный загрузчик сохранит: без незакрытой последней."""
        rows = self.candles[iid]
        return rows[:-1] if iid == INCOMPLETE_LAST_ID else rows

    @property
    def last_date(self) -> date:
        return self.dates[-1]


def _regimes(rng: np.random.Generator, n: int) -> tuple[list[str], dict]:
    """Режим каждого дня ряда доходностей: normal, SHOCK_A/B/C или drop."""
    regime = ["normal"] * n
    for sid, start, length, *_ in SHOCKS:
        for t in range(start, start + length):
            regime[t] = sid
    busy = {t + d for t, r in enumerate(regime) if r != "normal" for d in range(-5, 6)}
    candidates = [t for t in range(5, n) if t not in busy]
    for t in sorted(rng.choice(candidates, N_DROP_DAYS, replace=False).tolist()):
        regime[t] = "drop"
    return regime, {sid: (start, length) for sid, start, length, *_ in SHOCKS}


def generate(seed: int = 42) -> SynthDataset:
    rng = np.random.default_rng(seed)
    dates = business_days(SYNTH_START, N_DAYS)
    n = N_DAYS - 1
    regime, _ = _regimes(rng, n)
    shock = {sid: (mean, vol, svol) for sid, _, _, mean, vol, svol in SHOCKS}
    m_mean, m_vol, s_vol = np.empty(n), np.empty(n), np.zeros(n)
    for t, r in enumerate(regime):
        if r == "normal":
            m_mean[t], m_vol[t] = MARKET_DRIFT, FACTOR_VOL["market"]
        elif r == "drop":
            m_mean[t], m_vol[t], s_vol[t] = DROP_MEAN, DROP_VOL, DROP_STRESS
        else:
            m_mean[t], m_vol[t], s_vol[t] = shock[r]
    f = {k: rng.normal(0.0, FACTOR_VOL[k], n) for k in FACTORS}
    f["market"] = m_mean + m_vol * rng.standard_normal(n)
    stress = {k: s_vol * rng.standard_normal(n) for k in STRESS_SECTORS}
    calm = np.array([r == "normal" for r in regime], dtype=float)
    specs = _specs()
    ret: dict[str, np.ndarray] = {}
    for sp in specs:  # сначала бумаги из факторов, потом корзины из них
        if sp.basket is None:
            r = np.full(n, sp.drift) + sp.calm_drift * calm
            for k, v in sp.loads.items():
                r = r + v * f[k]
                if k in stress:
                    r = r + v * stress[k]
            ret[sp.id] = r + rng.normal(0.0, sp.idio, n)
    for sp in specs:
        if sp.basket is not None:
            r = sum(w * ret[i] for i, w in sp.basket.items())
            ret[sp.id] = r + rng.normal(0.0, sp.noise, n)
    candles = {sp.id: _ohlc(sp, dates, ret[sp.id], rng) for sp in specs}
    weekend_from = dates[WEEKEND_FROM_DAY]
    for iid in WEEKEND_IDS:
        candles[iid] = _add_weekends(candles[iid], weekend_from, rng)
    idx_r = sum(w * ret[i] for i, w in _norm(INDEX_WEIGHTS).items())
    levels = INDEX_LEVEL0 * np.exp(np.concatenate([[0.0], np.cumsum(idx_r)]))
    index_candles = [
        {"date": d.isoformat(), "open": None, "high": None, "low": None,
         "close": round(float(v), 2), "volume": 0}
        for d, v in zip(dates, levels, strict=True)
    ]  # fmt: skip
    manifest = _manifest(seed, dates, specs, regime)
    return SynthDataset(seed, dates, specs, candles, manifest, index_candles)


def _add_weekends(rows: list[dict], start: date, rng: np.random.Generator) -> list[dict]:
    """Свечи субботы и воскресенья: малый объём, небольшой шум от закрытия пятницы."""
    out: list[dict] = []
    for i, row in enumerate(rows):
        out.append(row)
        d = date.fromisoformat(row["date"])
        nxt = date.fromisoformat(rows[i + 1]["date"]) if i + 1 < len(rows) else None
        if d < start or d.weekday() != 4 or nxt is None:
            continue
        close = row["close"]
        for k in (1, 2):
            c = round(close * (1 + float(rng.normal(0.0, 0.002))), 4)
            out.append({"date": (d + timedelta(days=k)).isoformat(), "open": close,
                        "high": round(max(close, c) * 1.001, 4),
                        "low": round(min(close, c) * 0.999, 4), "close": c,
                        "volume": int(rng.integers(10, 500))})  # fmt: skip
            close = c
    return out


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


def _manifest(seed: int, dates: list[date], specs: list[Spec], regime: list[str]) -> dict:
    oils = [f"SYN_OIL{i}" for i in range(1, 6)]
    expected: list[dict] = [
        {"type": "corr_gte", "a": "SYN_IDXA", "b": "SYN_IDXB", "value": 0.95,
         "why": "фонды-близнецы на один индекс"},
        {"type": "corr_gte", "a": "SYN_IDXA", "b": "SYN_TOPCO", "value": 0.9,
         "why": "скрытый дубль: тот же индекс без слова «индекс»"},
        {"type": "corr_gte", "a": "SYN_BANK1", "b": "SYN_BANK1P", "value": 0.85,
         "why": "обыкновенная и привилегированная акции одного эмитента"},
        {"type": "resid_corr_between", "a": "SYN_BANK1", "b": "SYN_BANK2", "market": "SYN_IDXA",
         "regime": "normal", "low": 0.3, "high": 0.5,
         "why": "«Сбер» и «ВТБ» в обычные дни слабо связаны после вычета рынка"},
        {"type": "corr_gte", "a": "SYN_BANK1", "b": "SYN_BANK2", "regime": "shock", "value": 0.8,
         "why": "в шоки «Сбер» и «ВТБ» падают вместе"},
        {"type": "calm_trend_opposite", "a": "SYN_BANK1", "b": "SYN_BANK2",
         "why": "в спокойные дни один растёт, другой падает"},
        {"type": "corr_gte", "a": "SYN_OIL1", "b": "SYN_OIL2", "regime": "shock", "value": 0.9,
         "why": "в шоки корреляция внутри сектора растёт"},
        {"type": "episode_drawdown_lte", "a": "SYN_IDXA", "episode": "SHOCK_A", "value": -0.2,
         "why": "эпизод SHOCK_A: рынок падает больше чем на 20%"},
        {"type": "episode_drawdown_lte", "a": "SYN_IDXA", "episode": "SHOCK_B", "value": -0.2,
         "why": "эпизод SHOCK_B: рынок падает больше чем на 20%"},
        {"type": "episode_drawdown_lte", "a": "SYN_IDXA", "episode": "SHOCK_C", "value": -0.15,
         "why": "эпизод SHOCK_C: затяжное снижение рынка"},
        {"type": "corr_gte", "a": "SYN_GRP", "b": "SYN_GRPTEL", "value": 0.5,
         "why": "материнская и дочерняя компании группы «Синт-Система»"},
        {"type": "corr_gte", "a": "SYN_GRPFOR_B", "b": "SYN_GRPDEV_B", "value": 0.5,
         "why": "облигации дочерних компаний одной группы"},
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
        {"type": "same_issuer_different_brand", "a": "SYN_BANK1", "b": "SYN_BANK1P",
         "why": "ао и ап: бренды разные, company общая (как SBER/SBERP)"},
        {"type": "same_issuer_different_brand", "a": "SYN_GRPTEL", "b": "SYN_GRPTEL_B",
         "why": "акция и облигация одной компании: бренды разные, company общая"},
        {"type": "issuer_override", "a": "SYN_GRPDEV_B", "value": "ПАО «СинтСтрой»",
         "why": "облигация через финансовую «дочку»: эмитент задан в universe.yaml"},
        {"type": "weekend_candles", "a": list(WEEKEND_IDS),
         "from": dates[WEEKEND_FROM_DAY].isoformat(), "max_volume": 500,
         "why": "торги выходного дня: этап 2 их отфильтровывает"},
        {"type": "incomplete_last_candle", "a": INCOMPLETE_LAST_ID,
         "why": "последняя свеча в кассете isComplete=false: разбор её пропускает"},
        {"type": "no_brand", "a": "SYN_IDXC",
         "why": "фонд без бренда (как AMIX): ошибка шага brand, флаг на этапе 2"},
        {"type": "empty_sector", "a": ["SYN_GOLD", "SYN_MONEY", "SYN_BONDF"],
         "why": "пустой сектор бренда (как TGLD, LQDT, TBRU): профиль из role"},
        {"type": "starts_after_episode", "a": "SYN_IDXB", "episode": "SHOCK_A",
         "why": "фонд моложе шока: до запуска считаем по индексу"},
        {"type": "index_candles", "a": "SYNIDX_INDEX", "value": len(dates),
         "why": "дневная история синтетического индекса (как IMOEX_INDEX)"},
        {"type": "not_in_universe", "a": "SYN_ABSENT",
         "why": "есть только в каталоге MCP: флаг preliminary"},
    ]  # fmt: skip
    for i, a in enumerate(oils):
        for b in oils[i + 1 :]:
            expected.append({"type": "corr_between", "a": a, "b": b, "low": 0.6, "high": 0.8,
                             "regime": "normal", "why": "нефть в обычные дни"})  # fmt: skip
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
            "market_drift": MARKET_DRIFT,
            "shocks": [
                {
                    "id": sid,
                    "start": dates[start + 1].isoformat(),
                    "end": dates[start + length].isoformat(),
                    "days": length,
                    "market_mean": mean,
                    "market_vol": vol,
                    "stress_vol": svol,
                }
                for sid, start, length, mean, vol, svol in SHOCKS
            ],
            "drop_days": [dates[t + 1].isoformat() for t, r in enumerate(regime) if r == "drop"],
            "regime_note": "режим относится к доходности дня date (от закрытия предыдущего дня)",
        },
        "groups": list(GROUPS),
        "expected_ingest_errors": [{"instrument_id": "SYN_IDXC", "step": "brand"}],
        "instruments": [
            {
                "id": sp.id,
                "kind": sp.kind,
                "role": sp.role,
                "index": sp.index,
                "brand": BRANDS[sp.brand][0] if sp.brand else None,
                "company": BRANDS[sp.brand][1] if sp.brand else None,
                "sector": (BRANDS[sp.brand][2] or None) if sp.brand else None,
                "issuer": sp.issuer,
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
        UniverseEntry(
            id=sp.id, kind=sp.kind, role=sp.role, index=sp.index, issuer=sp.issuer, note=sp.name
        )
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


def write_dataset(ds: SynthDataset, out: Path | str, *, cassettes: bool = False) -> None:
    """Пишет набор. Кассеты (около 8 МБ) по умолчанию не пишутся: `load_synth` строит их
    из того же seed на лету, в git они не хранятся."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    if any(out.iterdir()) and not (out / "manifest.json").exists():
        raise ValueError(f"{out} не пуст и не похож на синтетический набор: не перезаписываю")
    by_id = {sp.id: sp for sp in ds.specs}
    brands = _brands()
    instruments = [
        _card(sp)["instrument"]
        | {
            "role": sp.role,
            "index": sp.index,
            "brandUid": brands[sp.brand]["uid"] if sp.brand else None,
        }
        for sp in ds.specs
    ]
    (out / "instruments.json").write_text(_dump(instruments), encoding="utf-8")
    (out / "brands.json").write_text(_dump(brands), encoding="utf-8")
    candle_rows = [
        [sp.id, c["date"], c["open"], c["high"], c["low"], c["close"], c["volume"]]
        for sp in ds.specs
        if sp.in_universe
        for c in ds.stored_candles(sp.id)
    ] + [
        [f"{INDEX_ID}_INDEX", c["date"], "", "", "", c["close"], c["volume"]]
        for c in ds.index_candles
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
    if cassettes:
        root = out / "cassettes"
        if root.exists():
            shutil.rmtree(root)
        write_cassettes(ds, root)


def _brands() -> dict:
    return {
        key: {"uid": _uid("brand", key), "name": b[0], "company": b[1], "sector": b[2],
              "description": b[3], "countryOfRisk": "SY"}
        for key, b in BRANDS.items()
    }  # fmt: skip


def _candle_payload(rows: list[dict], incomplete_last: bool = False) -> dict:
    out = []
    for i, c in enumerate(rows):
        item = {"time": c["date"], "close": _q(c["close"]), "volume": str(c["volume"]),
                "isComplete": not (incomplete_last and i == len(rows) - 1),
                "candleSource": "CANDLE_SOURCE_EXCHANGE"}  # fmt: skip
        for k in ("open", "high", "low"):
            if c[k] is not None:
                item[k] = _q(c[k])
        out.append(item)
    return {"priceCurrency": "rub", "candles": out}


def write_cassettes(ds: SynthDataset, root: Path | str) -> None:
    """Кассеты в формате ответов MCP для `fm ingest --mode replay` по синтетике."""
    root = Path(root)
    if root.exists() and any(root.iterdir()):
        raise ValueError(f"{root} не пуст: кассеты пишутся только в пустой каталог")
    brands = _brands()
    entries = _entries(ds.specs)
    cas = Cassette(root)
    by_id = {sp.id: sp for sp in ds.specs}
    last = ds.last_date.isoformat()
    for sp in ds.specs:
        e = UniverseEntry(id=sp.id, kind=sp.kind, role=sp.role, index=sp.index)
        card = _card(sp)
        cas.save(GET_TOOL[sp.kind], instrument_args(e), card)
        if not sp.in_universe:
            item = {k: card["instrument"][k] for k in ("ticker", "classCode", "isin", "name")}
            find_args = {"query": sp.id, "responseView": FIND_ARGS_VIEW}
            cas.save("invest_find_instrument", find_args, {"instruments": [item]})
            continue
        asset = {
            "uid": _uid("asset", sp.id),
            "name": sp.name,
            "type": "ASSET_TYPE_SECURITY",
            "instruments": [{"ticker": sp.id, "classCode": "SYN"}],
        }
        if sp.brand:
            b = brands[sp.brand]
            asset["brand"] = {"uid": b["uid"]}
            cas.save("invest_get_brand", {"id": b["uid"]}, {"brand": b})
        cas.save("invest_get_asset", {"id": asset["uid"]}, {"asset": asset})
        rows_all = ds.candles[sp.id]
        incomplete = sp.id == INCOMPLETE_LAST_ID
        first = date.fromisoformat(rows_all[0]["date"])  # конвейер начинает с листинга
        windows = candle_windows(first, ds.last_date)
        if incomplete:  # повторный запуск догружает с последней сохранённой (предпоследней) даты
            prev = date.fromisoformat(ds.stored_candles(sp.id)[-1]["date"])
            windows += candle_windows(prev, ds.last_date)
        for frm, to in windows:
            lo, hi = frm[:10], to[:10]
            rows = [c for c in rows_all if lo <= c["date"] < hi]
            has_last = bool(rows) and rows[-1]["date"] == last
            cas.save(
                "invest_get_candles",
                candle_args(sp.id, frm, to),
                _candle_payload(rows, incomplete_last=incomplete and has_last),
            )
    for frm, to in candle_windows(ds.dates[0], ds.last_date):
        lo, hi = frm[:10], to[:10]
        rows = [c for c in ds.index_candles if lo <= c["date"] < hi]
        cas.save("invest_get_candles", candle_args(INDEX_MCP_ID, frm, to), _candle_payload(rows))
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
