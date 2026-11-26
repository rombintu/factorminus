-- База — кэш: миграций нет. Схема изменилась — `fm reset` и загрузка заново.
-- Синтетика в тех же таблицах: id с префиксом SYN, source = 'synth'.

CREATE TABLE IF NOT EXISTS instruments (
    id TEXT PRIMARY KEY,          -- TICKER_CLASSCODE или SYN_*
    ticker TEXT,
    class_code TEXT,
    kind TEXT,                    -- share | etf | bond | currency | index
    role TEXT,                    -- из universe.csv: index_fund, ofz, ...
    index_id TEXT,                -- индекс фонда; у kind='index' — сам индекс (рынок)
    name TEXT,
    asset_name TEXT,              -- полное название актива (у фондов: «БПИФ ... Индекс МосБиржи»)
    isin TEXT,
    lot INTEGER,
    currency TEXT,
    asset_uid TEXT,
    brand_uid TEXT,
    issuer TEXT,                  -- кто несёт риск; у фондов, индексов и валют NULL
    uid TEXT,
    first_candle TEXT,            -- YYYY-MM-DD
    maturity TEXT,                -- YYYY-MM-DD, у облигаций
    dlong REAL,
    dshort REAL,
    source TEXT NOT NULL,         -- mcp | synth
    raw_json TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS brands (
    uid TEXT PRIMARY KEY,
    name TEXT,
    company TEXT,
    sector TEXT,
    description TEXT,
    country TEXT,
    source TEXT NOT NULL,
    raw_json TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS candles (
    instrument_id TEXT NOT NULL,
    date TEXT NOT NULL,           -- YYYY-MM-DD; MCP отдаёт и выходные, расчёты берут будни
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume REAL,
    PRIMARY KEY (instrument_id, date)
);

CREATE TABLE IF NOT EXISTS index_weights (
    index_id TEXT NOT NULL,       -- IMOEX или SYNIDX
    date TEXT NOT NULL,
    ticker TEXT NOT NULL,
    weight REAL,                  -- проценты, сумма около 100
    PRIMARY KEY (index_id, date, ticker)
);
