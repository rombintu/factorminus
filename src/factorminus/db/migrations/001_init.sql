-- Миграция 001: базовые таблицы этапа 1 (ТЗ п. 1.5).
-- Дополнительно к ТЗ: instruments.uid (ответы risk_rates адресуют бумаги по uid),
-- индексы по uid и по ingest_errors.run_id.
CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
CREATE TABLE instruments(
  instrument_id TEXT PRIMARY KEY,
  ticker TEXT NOT NULL, class_code TEXT NOT NULL,
  kind TEXT NOT NULL,
  role TEXT, index_id TEXT,
  uid TEXT,
  isin TEXT, name TEXT, lot INTEGER, currency TEXT,
  asset_uid TEXT, position_uid TEXT, brand_uid TEXT,
  first_day_candle TEXT, maturity_date TEXT,
  dlong REAL, dshort REAL, api_trade_flag INTEGER,
  raw_json TEXT NOT NULL, source TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE INDEX idx_instruments_uid ON instruments(uid);
CREATE TABLE assets(asset_uid TEXT PRIMARY KEY, name TEXT, brand_uid TEXT, raw_json TEXT NOT NULL,
  updated_at TEXT NOT NULL);
CREATE TABLE brands(brand_uid TEXT PRIMARY KEY, name TEXT, company TEXT, sector TEXT,
  description TEXT, country_of_risk TEXT, raw_json TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE candles(instrument_id TEXT NOT NULL, date TEXT NOT NULL,
  open REAL, high REAL, low REAL, close REAL NOT NULL, volume REAL,
  PRIMARY KEY(instrument_id, date));
CREATE TABLE index_weights(index_id TEXT NOT NULL, trade_date TEXT NOT NULL, ticker TEXT NOT NULL,
  secids TEXT, shortname TEXT, weight REAL NOT NULL, PRIMARY KEY(index_id, trade_date, ticker));
CREATE TABLE ingest_runs(run_id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT, finished_at TEXT,
  source TEXT, mode TEXT, ok_count INTEGER, error_count INTEGER, notes TEXT);
CREATE TABLE ingest_errors(run_id INTEGER, instrument_id TEXT, step TEXT, message TEXT);
CREATE INDEX idx_ingest_errors_run ON ingest_errors(run_id);
