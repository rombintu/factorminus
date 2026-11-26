"""Синтетический рынок для тестов и демо без токена: та же база, id SYN_*, source='synth'.

Доходность бумаги: r = β·рынок + Σγ·фактор + шум. Цены — накопленная доходность от 100.
"""

from datetime import UTC, date, datetime, timedelta

import numpy as np

SEED = 42
DAYS = 1500
END = date(2026, 11, 20)  # фиксированная дата: одинаковый seed даёт одинаковые данные
SHOCKS = [(60, 30), (560, 20), (1150, 150)]  # (первый торговый день, длина)
VOL = {"market": 0.011, "oil": 0.011, "banks": 0.01, "metals": 0.012, "tech": 0.014,
       "rate": 0.0012, "gold": 0.009, "group": 0.01}  # fmt: skip

# бренд: (название, компания, сектор, описание)
BRANDS = {
    "oil1": ("Синтнефть", "ПАО Синтнефть", "energy", "Добыча и переработка нефти в Западной Сибири."),
    "oil2": ("Северный баррель", "ПАО Северный баррель", "energy", "Нефтяная компания полного цикла."),
    "oil3": ("Уралойл", "ПАО Уралойл", "energy", "Добыча нефти и газового конденсата."),
    "oil4": ("Каспий Петро", "ПАО Каспий Петро", "energy", "Морская добыча нефти на шельфе."),
    "oil5": ("Тайга Энерджи", "ПАО Тайга Энерджи", "energy", "Независимый производитель нефти."),
    "sber": ("Синтбанк", "ПАО Синтбанк", "financial", "Крупнейший универсальный банк страны."),
    "vtb": ("Госбанк Синт", "ПАО Госбанк Синт", "financial", "Второй по размеру банк, госучастие."),
    "met": ("Синтметалл", "ПАО Синтметалл", "materials", "Производство никеля и палладия."),
    "tech": ("Синтех", "МКПАО Синтех", "it", "Интернет-сервисы: поиск, такси, доставка."),
    "newt": ("Нейросинт", "ПАО Нейросинт", "it", "Разработчик ИИ-сервисов, недавнее IPO."),
    "hold": ("Синт Холдинг", "ПАО Синт Холдинг", "other", "Диверсифицированный холдинг."),
    "htel": ("Синтсвязь", "ПАО Синтсвязь", "telecom", "Мобильный оператор, дочка Синт Холдинга."),
    "hdev": ("Синтстрой", "ПАО Синтстрой", "real_estate", "Девелопер, дочка Синт Холдинга."),
    "idxa": ("Синт Индекс Рынка", "УК Альфа-Синт", "other",
             "Биржевой фонд повторяет индекс SYNIDX: крупнейшие компании Синт-рынка."),
    "idxb": ("Индекс Синт-биржи", "УК Бета-Синт", "other",
             "Фонд отслеживает индекс Синт-биржи и вкладывает в его акции."),
    "capf": ("Лидеры капитала", "УК Гамма-Синт", "other",
             "Фонд вкладывает в акции двенадцати крупнейших компаний страны пропорционально "
             "их капитализации."),
    "divf": ("Дивидендный поток", "УК Дельта-Синт", "other",
             "Активный фонд дивидендных акций: нефтяные компании и банки."),
    "gold": ("Синт Золото", "УК Альфа-Синт", "other", "Фонд на физическое золото."),
    "money": ("Синт Ликвидность", "УК Бета-Синт", "other", "Фонд денежного рынка: сделки РЕПО."),
    "ofz": ("Минфин Синт", "Минфин Синт", "government", "Государственные облигации."),
}  # fmt: skip

# id: (бренд, kind, role, название); все id получают префикс SYN_
PAPERS = {
    "OIL1": ("oil1", "share", "share", "Синтнефть"),
    "OIL2": ("oil2", "share", "share", "Северный баррель"),
    "OIL3": ("oil3", "share", "share", "Уралойл"),
    "OIL4": ("oil4", "share", "share", "Каспий Петро"),
    "OIL5": ("oil5", "share", "share", "Тайга Энерджи"),
    "SBER": ("sber", "share", "share", "Синтбанк"),
    "SBERP": ("sber", "share", "share", "Синтбанк — привилегированные акции"),
    "VTB": ("vtb", "share", "share", "Госбанк Синт"),
    "MET": ("met", "share", "share", "Синтметалл"),
    "TECH": ("tech", "share", "share", "Синтех"),
    "NEWT": ("newt", "share", "share", "Нейросинт"),
    "HOLD": ("hold", "share", "share", "Синт Холдинг"),
    "HTEL": ("htel", "share", "share", "Синтсвязь"),
    "HDEV": ("hdev", "share", "share", "Синтстрой"),
    "HTELB": ("htel", "bond", "corp_bond", "Синтсвязь БО-01"),
    "IDXA": ("idxa", "etf", "index_fund", "Синт Индекс Рынка"),
    "IDXB": ("idxb", "etf", "index_fund", "Индекс Синт-биржи"),
    "CAPF": ("capf", "etf", "active_fund", "Лидеры капитала"),
    "DIVF": ("divf", "etf", "active_fund", "Дивидендный поток"),
    "GOLD": ("gold", "etf", "gold_fund", "Синт Золото"),
    "MONEY": ("money", "etf", "money_fund", "Синт Ликвидность"),
    "OFZ2": ("ofz", "bond", "ofz", "ОФЗ-Синт 2 года"),
    "OFZ8": ("ofz", "bond", "ofz", "ОФЗ-Синт 8 лет"),
}
WEIGHTS = {"OIL1": 14, "OIL2": 10, "OIL3": 8, "OIL4": 5, "OIL5": 3, "SBER": 15, "SBERP": 2,
           "VTB": 5, "MET": 10, "TECH": 12, "HOLD": 8, "HTEL": 8}  # fmt: skip
MATURITY = {"OFZ2": "2028-11-20", "OFZ8": "2034-11-20", "HTELB": "2029-06-01"}
SHORT_HISTORY = 40


def trading_days() -> list[str]:
    days, d = [], END
    while len(days) < DAYS:
        if d.weekday() < 5:
            days.append(d.isoformat())
        d -= timedelta(days=1)
    return days[::-1]


DATES = trading_days()
EXPECTED = {
    "index_twins": ["SYN_IDXA", "SYN_IDXB"],
    "twin_min_corr": 0.95,
    "hidden_duplicate": "SYN_CAPF",  # тот же индекс, но без слова «индекс»
    "dividend_fund": "SYN_DIVF",
    "dividend_mix": {"oil": 35, "banks": 35, "market": 30},
    "oil": [f"SYN_OIL{i}" for i in range(1, 6)],
    "oil_corr": (0.6, 0.8),
    "banks": ["SYN_SBER", "SYN_VTB"],
    "same_brand": ["SYN_SBER", "SYN_SBERP"],
    "gold": "SYN_GOLD",
    "gold_max_market_corr": 0.05,
    "money_fund": "SYN_MONEY",
    "money_max_daily_vol": 0.0005,
    "ofz_by_duration": ["SYN_OFZ2", "SYN_OFZ8"],  # дюрация 2 и 8 лет
    "short_history": ("SYN_NEWT", SHORT_HISTORY),
    "shocks": [(DATES[s], DATES[s + n - 1]) for s, n in SHOCKS],
    "shock_pair": ["SYN_SBER", "SYN_VTB"],
    "shock_corr_min": 0.8,
    "normal_resid_corr": (0.3, 0.5),
    "group": {"parent": "SYN_HOLD", "members": ["SYN_HTEL", "SYN_HDEV", "SYN_HTELB"]},
    "missing_id": "SYN_GHOST",  # бумаги нет в базе: флаг preliminary на этапе 2
}


def simulate(seed: int = SEED) -> dict[str, np.ndarray]:
    """Дневные лог-доходности всех бумаг (ключ без префикса SYN_)."""
    rng = np.random.default_rng(seed)
    f = {k: rng.normal(0, v, DAYS) for k, v in VOL.items()}
    shock = np.zeros(DAYS, bool)
    for start, n in SHOCKS:
        shock[start : start + n] = True
    f["market"] = np.where(shock, rng.normal(-0.003, 0.03, DAYS), f["market"])
    stress = np.where(shock, rng.normal(0, 0.025, DAYS), 0.0)  # системный стресс банков

    def stock(beta, noise, **loads):
        r = beta * f["market"] + rng.normal(0.0003, noise, DAYS)
        return r + sum(g * f[k] for k, g in loads.items())

    r = {f"OIL{i}": stock(0.8, 0.011, oil=1.0) for i in range(1, 6)}
    r["SBER"] = stock(1.1, 0.012, banks=1.0, rate=-2) + stress
    r["SBERP"] = r["SBER"] + rng.normal(0, 0.004, DAYS)
    r["VTB"] = stock(1.2, 0.012, banks=1.0, rate=-3) + stress
    r["MET"] = stock(0.9, 0.012, metals=1.0)
    r["TECH"] = stock(1.2, 0.014, tech=1.0)
    r["NEWT"] = stock(1.4, 0.02, tech=1.2)
    r["HOLD"] = stock(1.0, 0.012, group=1.0)
    r["HTEL"] = stock(0.7, 0.01, group=0.6)
    r["HDEV"] = stock(1.0, 0.014, group=0.5, rate=-4)
    r["HTELB"] = -3 * f["rate"] + 0.05 * f["group"] + rng.normal(0.0004, 0.0006, DAYS)
    index = sum(w / 100 * r[p] for p, w in WEIGHTS.items())
    r["IDXA"] = index + rng.normal(0, 0.0007, DAYS)
    r["IDXB"] = index + rng.normal(0, 0.0008, DAYS)
    r["CAPF"] = index + rng.normal(0, 0.0012, DAYS)
    oil = np.mean([r[f"OIL{i}"] for i in range(1, 6)], axis=0)
    banks = (r["SBER"] + r["VTB"]) / 2
    r["DIVF"] = 0.35 * oil + 0.35 * banks + 0.3 * index + rng.normal(0, 0.002, DAYS)
    r["GOLD"] = f["gold"] - 0.15 * f["market"] + rng.normal(0.0002, 0.003, DAYS)
    r["MONEY"] = rng.normal(0.0006, 0.00003, DAYS)
    r["OFZ2"] = -2 * f["rate"] + rng.normal(0.0003, 0.0004, DAYS)
    r["OFZ8"] = -8 * f["rate"] + rng.normal(0.0003, 0.0006, DAYS)
    return r


def write(conn, seed: int = SEED) -> dict:
    """Удалить старую синтетику и записать новую. Возвращает число строк по таблицам."""
    for table, key in (("instruments", "id"), ("brands", "uid"), ("candles", "instrument_id"),
                       ("index_weights", "index_id")):  # fmt: skip
        conn.execute(f"DELETE FROM {table} WHERE {key} LIKE 'SYN%'")
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    for key, (name, company, sector, text) in BRANDS.items():
        conn.execute(
            "INSERT INTO brands VALUES (?, ?, ?, ?, ?, 'RU', 'synth', NULL, ?)",
            (f"SYN_BRAND_{key.upper()}", name, company, sector, text, stamp),
        )
    candles = 0
    for pid, r in simulate(seed).items():
        candles += write_paper(conn, pid, r, stamp)
    weights = [("SYNIDX", DATES[-1], f"SYN_{p}", float(w)) for p, w in WEIGHTS.items()]
    conn.executemany("INSERT INTO index_weights VALUES (?, ?, ?, ?)", weights)
    conn.commit()
    return {"instruments": len(PAPERS), "brands": len(BRANDS), "candles": candles}


def write_paper(conn, pid: str, r: np.ndarray, stamp: str) -> int:
    brand, kind, role, name = PAPERS[pid]
    asset = f"Синтетический актив «{name}»"
    if role == "index_fund":
        asset = f"Паи БПИФ «{name}», индекс SYNIDX"
    dates = DATES[-SHORT_HISTORY:] if pid == "NEWT" else DATES
    r = r[-len(dates) :]
    close = 100 * np.exp(np.cumsum(r))
    open_ = np.concatenate([[100.0], close[:-1]])
    spread = np.abs(r) / 2 + 0.002
    high = np.maximum(open_, close) * (1 + spread)
    low = np.minimum(open_, close) * (1 - spread)
    volume = (1e6 * (1 + 20 * np.abs(r))).round()
    iid = f"SYN_{pid}"
    conn.execute(
        "INSERT INTO instruments (id, ticker, class_code, kind, role, index_id, name, asset_name, "
        "lot, currency, brand_uid, first_candle, maturity, source, updated_at) "
        "VALUES (?, ?, 'SYN', ?, ?, ?, ?, ?, 1, 'rub', ?, ?, ?, 'synth', ?)",
        (iid, pid, kind, role, "SYNIDX" if role == "index_fund" else None, name, asset,
         f"SYN_BRAND_{brand.upper()}", dates[0], MATURITY.get(pid), stamp),
    )  # fmt: skip
    rows = zip([iid] * len(dates), dates, *(np.round(x, 4).tolist() for x in (open_, high, low, close)),
               volume.tolist())  # fmt: skip
    conn.executemany("INSERT INTO candles VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
    return len(dates)
