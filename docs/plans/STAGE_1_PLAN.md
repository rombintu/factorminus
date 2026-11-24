# Этап 1: фундамент и данные. План реализации

> **Для исполнителя:** выполнять по задачам, TDD, шаги отмечать `- [ ]`.

**Цель:** каркас Python-проекта `factorminus`, безопасный read-only MCP-клиент с кассетами, загрузка вселенной и весов IMOEX в SQLite, синтетический набор, контракт вердикта, CLI `fm`, зелёные тесты.

**Архитектура:** src-layout. Сеть есть только в `mcp/client.py` (httpx) и `iss.py` (httpx). Конвейер (`ingest/pipeline.py`) получает клиент снаружи, поэтому в тестах его заменяют кассеты replay или `httpx.MockTransport`. Синтетика пишет кассеты в формате ответов MCP, и сквозной тест — это обычный `fm ingest --mode replay`.

**Стек:** Python 3.12, httpx, pydantic v2, typer, pyyaml, numpy, sqlite3, pytest, ruff.

**Спека:** `docs/tz/STAGE_1.md` + `docs/CONTEXT.md` (разделы 5–7, 10).

## Глобальные ограничения

- Белый список MCP: ровно 16 инструментов из п. 1.3 ТЗ. Всё прочее → `ForbiddenToolError` до сетевого запроса.
- Токен: env `TINVEST_TOKEN` > `.env` в корне репо. `.env` не открывать вручную, не печатать. В repr/логах `t.***`.
- TLS проверяется всегда; `TINVEST_CA_BUNDLE` → `verify=<path>`; `TINVEST_INSECURE_SSL=1` → предупреждение в stderr, при `PYTEST_CURRENT_TEST` → отказ.
- Тесты не ходят в сеть (autouse-guard на `socket.connect`), live-тесты под `@pytest.mark.live`, по умолчанию пропуск.
- В git: никаких реальных свечей и ответов MCP; `data/` кроме `data/universe.yaml` игнорируется.
- Формулировки: без «купите, продайте, рекомендуем, советуем, лучше, стоит».
- Таймаут httpx 30 с, `protocolVersion: "2025-03-26"`, ретраи 3, лимит 180 запросов/мин.

## Решения, принятые в плане (идут в отчёт)

- Миграции лежат в `src/factorminus/db/migrations/001_init.sql`. Отдельного `schema.sql` нет, чтобы схема не жила в двух местах.
- YAML читается через `pyyaml`, добавлен в зависимости. `.env` разбирается простым парсером, без python-dotenv.
- Свечи запрашиваются окнами не длиннее 365 дней. Окна считает одна функция `candle_windows()`, общая для конвейера и генератора кассет, поэтому ключи кассет совпадают.
- Synth id: `SYN_<NAME>`. Для них `ticker = id`, `class_code = "SYN"`. Даты синтетики фиксированы: 500 рабочих дней от 2024-01-02, без привязки к «сегодня».
- Кассета хранит `{"tool", "arguments", "result"}`. Ключ — sha1 от `json.dumps(args, sort_keys=True, ensure_ascii=False)`.

## Фокус ревью (входы, которые ТЗ подразумевает, но не называет)

1. SSE-ответ с пустыми строками, `event:` и несколькими `data:` → выбрать нужный `id`, игнорировать уведомления. Тест в задаче 4.
2. Кавычки и `export` в `.env`, пустое значение → считать «не задан». Тест в задаче 2.
3. Бумага без `assetUid` или бренд без сектора → строка в `instruments` есть, ошибка шага записана, конвейер идёт дальше. Тест в задаче 9.
4. Повторный ingest на тех же кассетах: строки не дублируются, свечи догружаются от последней даты. Тест в задаче 9.
5. `nano` отрицательный или строковый в Quotation, `units` строкой. Тест в задаче 5.

---

### Задача 1. Каркас

**Файлы:** `pyproject.toml`, `Makefile`, `.env.example`, `.gitignore`, `README.md`, `src/factorminus/__init__.py` (`__version__ = "0.1.0"`), `src/factorminus/cli.py` (пустое typer-приложение `app`, точка входа `fm = "factorminus.cli:app"`), `tests/conftest.py`, `tests/test_smoke.py`.

- [ ] Тест `test_version` (`factorminus.__version__ == "0.1.0"`) и `test_network_guard`: `socket.create_connection(("example.com", 80))` поднимает `RuntimeError`.
- [ ] `conftest.py`: autouse-фикстура патчит `socket.socket.connect` на `RuntimeError("network disabled in tests")`, кроме тестов с маркером `live`. Опция `--live` включает live-тесты, без неё они пропускаются.
- [ ] pyproject: deps `httpx, pydantic>=2, typer, pyyaml, numpy`; extras `ml = ["laya==0.5.1"]`, `dev = ["pytest", "ruff"]`; ruff line-length 100, правила `E,F,I,UP,B`; pytest markers `live`.
- [ ] Makefile: `install, lint (ruff check + ruff format --check), test (pytest -q), test-live (pytest -q --live -m live), ingest, synth`.
- [ ] `.gitignore` дополнить: `.venv/ __pycache__/ .pytest_cache/ .ruff_cache/ *.egg-info/`.
- [ ] `python3.12 -m venv .venv && .venv/bin/pip install -e '.[dev]' && make lint test` → зелено. Коммит.

### Задача 2. Конфигурация (`config.py`)

**Производит:** `Settings` (frozen dataclass: `token: str|None`, `mcp_url: str`, `ca_bundle: str|None`, `insecure_ssl: bool`, `db_path: Path`), `load_settings(env: Mapping[str,str]|None = None, env_file: Path|None = None) -> Settings`, `Settings.require_token() -> str`, `Settings.verify() -> bool|str`, `mask_secret(s: str|None) -> str`, `ConfigError`. Константы `DEFAULT_MCP_URL = "https://invest-public-api.tbank.ru/mcp"`, `DEFAULT_DB_PATH = "data/fm.sqlite"`. `REPO_ROOT` — корень с `pyproject.toml`.

- [ ] Тесты: env важнее `.env` (временный `.env` с `TINVEST_TOKEN=t.fake-file`, env `t.fake-env`); `.env` с кавычками, `export`, комментариями; пустой токен → `None`; `require_token()` без токена → `ConfigError` с текстом «задайте TINVEST_TOKEN в .env»; `repr(settings)` и `str` не содержат токен, содержат `t.***`; `verify()` → `True` по умолчанию, путь при `TINVEST_CA_BUNDLE`; insecure при `PYTEST_CURRENT_TEST` → `ConfigError`.
- [ ] Реализация, зелёные тесты, коммит.

### Задача 3. Белый список и кассеты

**Производит:** `mcp/errors.py`: `McpError`, `McpToolError(name, message)`, `ForbiddenToolError(name)`, `CassetteMissError(tool, path)`, `McpTransportError`. `mcp/allowlist.py`: `READ_ONLY_TOOLS: frozenset[str]` (16 имён), `ensure_allowed(name) -> None`. `mcp/cassette.py`: `Mode = Literal["live","record","replay"]`, `Cassette(root: Path)` с `key(tool, args) -> str`, `path(tool, args) -> Path`, `load(tool, args) -> Any`, `save(tool, args, result) -> Path`.

- [ ] Тесты: все 16 имён разрешены; `invest_create_order`, `invest_get_portfolio`, `invest_list_accounts`, `invest_cancel_order` → `ForbiddenToolError`; ключ не зависит от порядка ключей args; save→load возвращает то же; load без файла → `CassetteMissError`.
- [ ] Реализация, коммит.

### Задача 4. MCP-клиент (`mcp/client.py`)

**Потребляет:** задачи 2–3. **Производит:** `McpClient(settings: Settings, *, mode: Mode = "live", cassette_dir: Path = Path("data/cassettes"), transport: httpx.BaseTransport|None = None, max_rpm: int = 180, retries: int = 3, backoff: float = 0.5, sleep: Callable[[float],None] = time.sleep)`; методы `call_tool(name, arguments) -> dict|list|str`, `list_tools() -> list[str]`, `close()`, контекстный менеджер. `RateLimiter(max_per_minute, clock, sleep)` со скользящим окном 60 с.

Порядок `call_tool`: `ensure_allowed` → replay: `cassette.load` (без сети и без токена) → иначе ленивый `initialize` → POST → разбор → record: `cassette.save`. Сессия истекла (404, или 400 с «session» в теле) → один повторный `initialize` и повтор. 429/5xx/`httpx.TransportError` → до 3 попыток, задержка `backoff * 2**i`. Логи: `logger "factorminus.mcp"`, имя, args, мс, байты. Заголовки не логируются. `list_tools` в replay читает кассету `_meta/tools_list`.

- [ ] Тесты на `httpx.MockTransport` с фейковым сервером: рукопожатие (initialize → notifications/initialized → tools/call несёт `Mcp-Session-Id`); SSE с двумя событиями, нужен второй `id`; JSON-ответ; текст не-JSON → строка; `isError` → `McpToolError`; JSON-RPC error → `McpToolError`; 429 затем 200 → успех, `sleep` вызван; 404 на сессию → переинициализация, успех; `invest_create_order` → `ForbiddenToolError`, счётчик транспорта 0; replay без транспорта; record пишет файл; `caplog` не содержит токен; insecure под pytest → `ConfigError`; лимитер: 181-й вызов в окне ждёт.
- [ ] Реализация, коммит. Затем security-review по `config.py` и `mcp/`.

### Задача 5. Разбор чисел и дат (`ingest/parse.py`)

**Производит:** `to_float(v) -> float|None` (форматы `{"value": "0.125"}`, `{"units": "3", "nano": 500000000}`, `{"currency":..., "units":..., "nano":...}`, str, int/float, None); `to_msk_date(ts: str) -> str` (`YYYY-MM-DD` по Москве, UTC+3); `parse_instrument(payload: dict, kind: str) -> dict` (поля колонок таблицы `instruments`); `parse_candles(payload) -> list[dict]`; `parse_brand(payload) -> dict`; `parse_asset(payload) -> dict`; `parse_risk_rates(payload) -> dict[str, tuple[float|None, float|None]]`.

- [ ] Тесты: `{"value":"0.125"}`→0.125; `{"units":"3","nano":500000000}`→3.5; `{"units":"-1","nano":-250000000}`→-1.25; `"12.5"`→12.5; `None`→None; `"2026-11-20T21:00:00Z"`→`"2026-11-21"`; разбор синтетических карточек share/etf/bond (облигация даёт `maturity_date`).
- [ ] Реализация (ключи ищутся терпимо: `instrument` или корень; `dlongClient`/`dlong`). Коммит.

### Задача 6. БД (`db/__init__.py`, `db/migrations/001_init.sql`)

**Производит:** `connect(path: Path|str) -> sqlite3.Connection` (создаёт каталог, `row_factory = Row`, `foreign_keys=ON`), `migrate(conn) -> list[int]` (применённые версии), `table_counts(conn) -> dict[str,int]`, `candle_ranges(conn) -> dict` (min/max дата, число инструментов). Схема — дословно из п. 1.5 ТЗ плюс индекс `ingest_errors(run_id)`.

- [ ] Тесты: `migrate` на пустой БД → `[1]`, повторно → `[]`; все 8 таблиц есть; второй файл миграции во временном каталоге применяется по порядку.
- [ ] Реализация + CLI `fm db init`, `fm db stats`. Коммит.

### Задача 7. ISS (`iss.py`)

**Производит:** `ISS_URL`, `parse_iss_analytics(payload: dict) -> list[dict]` (`trade_date, ticker, secids, shortname, weight`), `fetch_index_weights(index_id: str, *, transport=None) -> list[dict]`, `store_index_weights(conn, index_id, rows) -> int` (UPSERT).

- [ ] Тесты: разбор синтетического ответа `{"analytics": {"columns": [...], "data": [...]}}`; fetch через MockTransport; повторный store не дублирует.
- [ ] CLI `fm iss weights --index IMOEX`. Коммит.

### Задача 8. Вселенная (`data/universe.yaml`, `ingest/universe.py`)

**Производит:** `UniverseEntry` (pydantic: `id`, `kind: share|etf|bond|currency`, `role` из 8 значений, `index: str|None`, `note: str = ""`), `load_universe(path) -> list[UniverseEntry]` (уникальные id, `index` обязателен ровно для `index_fund`), `GET_TOOL = {"share": "invest_get_share", "etf": "invest_get_etf", "bond": "invest_get_bond", "currency": "invest_get_currency"}`, `instrument_args(entry) -> dict`, `verify_universe(client, entries) -> dict` (`found`, `not_found`, `no_api_flag`, `details`).

- [ ] Тесты: валидный и невалидные YAML; `verify_universe` на фейковом клиенте (одна найдена, одна `McpToolError`) → не падает, сводка верна; реальный `data/universe.yaml` проходит `load_universe` и содержит ≥ 55 записей.
- [ ] Составить `data/universe.yaml` (~60 записей по п. 1.4), CLI `fm universe verify` → `data/universe_resolved.json`. Коммит.

### Задача 9. Конвейер (`ingest/pipeline.py`)

**Производит:** `candle_windows(since: date, until: date, max_days: int = 365) -> list[tuple[str,str]]` (ISO `YYYY-MM-DDT00:00:00Z`, правая граница `until + 1 день`); `IngestSummary` (dataclass: instruments, brands, candles, errors, seconds); `run_ingest(conn, client, entries, *, since: date, until: date, mode: str, source: str = "mcp") -> IngestSummary`.

Шаги по п. 1.6 ТЗ. Бренды кэшируются в рамках запуска. Свечи с `max(date)+1` при наличии. Risk rates батчами по 50, обновляют `dlong/dshort`, только если значения не `None`. Ошибка шага → `ingest_errors(run_id, instrument_id, step, message)`. Запись в `ingest_runs`.

- [ ] Тесты на фейковом клиенте (dict tool→ответ): заполняет instruments/assets/brands/candles; бренд запрошен один раз на два инструмента; ошибка у одной бумаги → 1 строка в `ingest_errors`, остальные загружены; повторный запуск → те же счётчики строк; инкремент запрашивает свечи от последней даты + 1.
- [ ] CLI `fm ingest --only --since --mode --db`. Коммит.

### Задача 10. Синтетика (`synth/generator.py`)

**Производит:** `generate(seed: int = 42) -> SynthDataset`, `write_dataset(ds, out: Path) -> None`, `SYNTH_START = date(2024,1,2)`, `N_DAYS = 500`.

Факторная модель по ТЗ: факторы `market, oil, banks, metals, tech, rate, gold`. Состав (минимум из ТЗ): `SYN_IDXA`, `SYN_IDXB` (близнецы на `SYNIDX`), `SYN_TOPCO` (скрытый дубль, без слова «индекс»), `SYN_DIVACT` (70% нефть+банки, «дивидендные акции»), нефть `SYN_OIL1..5`, банки `SYN_BANK1`, `SYN_BANK1P` (общий бренд), `SYN_BANK2`, металлы, технологии, `SYN_GOLD`, `SYN_MONEY`, `SYN_OFZS`, `SYN_OFZL`, `SYN_NEWCO` (40 дней), `SYN_ABSENT` (только кассета `find_instrument`/`get_share`, нет в `universe.yaml` набора). Индекс `SYNIDX` — 10–12 акций, веса в сумме 100.

Файлы: `instruments.json`, `brands.json`, `candles.csv`, `index_weights.csv`, `manifest.json`, `universe.yaml`, `cassettes/<tool>/<sha1>.json` (ответы в формате MCP: Quotation `{"units","nano"}` для цен, `time` ISO UTC 21:00 предыдущего дня). Числа округлены, JSON с `sort_keys`, CSV с `\n`.

Ожидаемые свойства в `manifest.json`: `{"type": "corr_gte"|"corr_between"|"corr_lte"|"vol_lte"|"history_days_eq", ...}`. Минимум: corr(IDXA, IDXB) ≥ 0.95; corr(IDXA, TOPCO) ≥ 0.9; нефть попарно в [0.6, 0.8]; corr(GOLD, market) ≤ 0.1; vol(MONEY) ≤ 0.001; corr(OFZS, OFZL) ≥ 0.5 и бета к ставке у OFZL больше по модулю; NEWCO — 40 дней.

- [ ] Тесты: два запуска с seed 42 в разные каталоги → побайтно равны; все свойства манифеста выполняются (считать корреляции дневных лог-доходностей numpy); сумма весов SYNIDX = 100 ± 0.01; никаких реальных тикеров (все id начинаются с `SYN_`).
- [ ] CLI `fm synth generate --seed 42 --out tests/fixtures/synthetic`; сгенерировать и закоммитить фикстуры.

### Задача 11. Сквозная загрузка синтетики (`fm synth load`)

**Производит:** `load_synth(db_path: Path, fixtures: Path) -> IngestSummary` = `run_ingest(..., mode="replay", since=SYNTH_START, until=last_date)` по `fixtures/universe.yaml` с кассетами `fixtures/cassettes` + `index_weights.csv` в `index_weights`.

- [ ] Тесты: replay заполняет БД с `errors == 0`, число свечей = число строк `candles.csv`; повторный запуск не меняет счётчики; при отключённой сети (guard) всё проходит; `SYN_ABSENT` отсутствует в `instruments`.
- [ ] CLI `fm synth load --db data/fm_synth.sqlite`. Коммит.

### Задача 12. Контракт (`contracts.py`, `wording.py`, `docs/contract/`)

**Производит:** enum `Verdict`, `Severity`, `Flag`, `Operation`; модели `Position`, `Portfolio`, `VerdictRequest`, `Overlap`, `DataAsOf`, `Trace`, `VerdictResponse` (`contract_version: Literal["1.0"]`); `INSTRUMENT_ID_RE = r"^([A-Z0-9]+_[A-Z0-9]+|SYN_[A-Z0-9_]+)$"`. `wording.py`: `FORBIDDEN_WORDS` (6 слов из ТЗ, по основам: «куп(ите|и)», «прода(йте|й)», «рекоменд», «совету», «лучше», «стоит»), `find_forbidden(text) -> list[str]`, `check_response_wording(resp) -> list[str]`. `export_schemas(out: Path) -> list[Path]`.

- [ ] Тесты: пример запроса из CONTEXT §7 валиден; `amount_rub = 0` и отрицательная позиция отклоняются; `instrument_id = "sber"` отклоняется; `factors_after` с суммой 90 отклоняется (допуск ±0.5), с долей 101 отклоняется; 5 примеров в `docs/contract/examples/` валидны и без запрещённых слов; `find_forbidden("Рекомендуем купить")` непуст, `find_forbidden("корреляция 0,92")` пуст; экспорт схем совпадает с файлами в репо.
- [ ] CLI `fm contract export`. Коммит.

### Задача 13. Живая проверка и live-тесты

- [ ] `fm mcp check` (рукопожатие, число инструментов, наличие 16 инструментов белого списка). При ошибке TLS подобрать `TINVEST_CA_BUNDLE` (корневые сертификаты Минцифры) и записать в отчёт.
- [ ] `tests/test_live.py` (`@pytest.mark.live`): SBER_TQBR, TMOS_TQTF, одна ОФЗ, свечи 30 дней → парсеры дают непустые поля.
- [ ] `fm universe verify`, `fm ingest --mode record`, `fm iss weights --index IMOEX`, `fm db stats` → вывод и время в отчёт. Замены бумаг → в `universe.yaml` и отчёт.

### Задача 14. Ревью и отчёт

- [ ] Security-review и code-review по всей ветке, исправления.
- [ ] Проверка: `make lint`, `make test`, `git status` (нет `.env`, `data/`).
- [ ] `docs/reports/STAGE_1_REPORT.md` по п. 8 критериев приёмки.
