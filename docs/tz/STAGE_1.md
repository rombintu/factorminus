# ТЗ. Этап 1 из 4: фундамент и данные

Сначала прочитай `docs/CONTEXT.md` целиком: продукт, ограничения, контракт, правила работы и плагины. Здесь только задачи этапа 1.

## Цель этапа

К концу этапа в репозитории есть:
- рабочий каркас Python-проекта;
- безопасный read-only MCP-клиент;
- загрузка данных о бумагах из T-Invest MCP и весов IMOEX из ISS в SQLite;
- генератор **синтетического** набора данных для тестов;
- зафиксированный контракт вердикта;
- CLI и зелёные тесты.

Анализа и вердиктов на этом этапе ещё нет: это этап 2.

## Порядок работы

1. Прочитай `docs/CONTEXT.md`, этот файл и соседние материалы из раздела 9 контекста.
2. Создай ветку `stage-1`.
3. Составь план в `docs/plans/STAGE_1_PLAN.md` по задачам ниже. Покажи план пользователю одним сообщением и, не дожидаясь ответа, начинай задачу 1.1. Если пользователь поправит, учти.
4. Выполняй по TDD.
5. После MCP-клиента и после всего этапа — security-review и code-review.
6. Проверка (`make lint`, `make test`) → отчёт `docs/reports/STAGE_1_REPORT.md`.

---

## Задачи

### 1.1. Каркас проекта

Структура:
```
factorminus/
  pyproject.toml          # name=factorminus, python>=3.12, extras: [ml] = laya==0.5.1, [dev] = pytest, ruff, respx/или httpx MockTransport
  Makefile                # install, lint, test, test-live, ingest, synth
  .env.example            # TINVEST_TOKEN=, TINVEST_MCP_URL=https://invest-public-api.tbank.ru/mcp, TINVEST_CA_BUNDLE=, FM_DB_PATH=data/fm.sqlite
  .gitignore              # + .env, data/, *.sqlite, .venv/, __pycache__/, .pytest_cache/
  src/factorminus/
    __init__.py
    config.py             # чтение env, значения по умолчанию, маскирование секретов в repr
    mcp/client.py         # MCP-клиент
    mcp/allowlist.py      # белый список read-only инструментов
    mcp/cassette.py       # запись и воспроизведение ответов
    iss.py                # клиент ISS Мосбиржи
    db/schema.sql         # миграция 001
    db/__init__.py        # connect(), migrate()
    ingest/universe.py    # загрузка и проверка вселенной
    ingest/pipeline.py    # конвейер загрузки
    ingest/parse.py       # разбор ответов MCP (Quotation, MoneyValue, даты)
    synth/generator.py    # синтетические данные
    contracts.py          # pydantic-модели контракта вердикта
    cli.py                # typer, точка входа `fm`
  data/universe.yaml      # вселенная бумаг (в git: это не рыночные данные)
  docs/contract/          # JSON Schema и примеры
  tests/
    fixtures/synthetic/   # генерируется `fm synth generate`, лежит в git
    ...
```

- `README.md`: коротко что это, как установить (`python3.12 -m venv .venv && pip install -e '.[dev]'`, для laya `pip install -e '.[ml]'`), как задать токен, основные команды.
- `ruff` настроен, `make lint` и `make test` проходят.

### 1.2. Конфигурация и секреты

- `TINVEST_TOKEN` — из окружения, а если его нет, из `.env` в корне репозитория. Обязателен только для команд, которые ходят в MCP. Без него понятная ошибка «задайте TINVEST_TOKEN в .env», без трейсбека. Тест проверяет, что переменная окружения имеет приоритет над `.env`; в тесте используется временный `.env` с фиктивным значением.
- `TINVEST_MCP_URL` — по умолчанию боевой адрес, можно задать песочницу.
- `TINVEST_CA_BUNDLE` — путь к PEM, передаётся в `httpx` как `verify=`.
- `TINVEST_INSECURE_SSL=1` — отключает проверку сертификата, печатает предупреждение в stderr. В тестах запрещён: тест проверяет, что при `PYTEST_CURRENT_TEST` клиент отказывается стартовать с этим флагом.
- В `repr` и логах конфигурации токен виден как `t.***`. Тест: строковое представление конфига и все записи логов клиента не содержат токен.

### 1.3. MCP-клиент (`mcp/client.py`)

Требования:
- `httpx.Client`, таймаут 30 с.
- `initialize` с `protocolVersion: "2025-03-26"` и `clientInfo {name: "factorminus", version}`, затем `notifications/initialized`. Сохраняет `Mcp-Session-Id`.
- `call_tool(name, arguments) -> dict | list`. Разбирает ответ:
  - тело `application/json` или `text/event-stream`: берёт `data:` с совпадающим `id`;
  - в `result.content[]` текстовые части с JSON — распарсить; если не JSON, вернуть строку;
  - `result.isError == true` или JSON-RPC `error` → `McpToolError(name, message)`.
- `list_tools() -> list[str]`.
- **Белый список** (`allowlist.py`): только инструменты чтения, которые нужны проекту:
  - `invest_find_instrument`, `invest_get_share`, `invest_get_etf`, `invest_get_bond`, `invest_get_currency`;
  - `invest_get_asset`, `invest_get_brand`, `invest_get_asset_fundamentals`;
  - `invest_get_candles`, `invest_get_risk_rates`;
  - `invest_list_shares`, `invest_list_etfs`, `invest_list_bonds`;
  - `invest_get_market_values`, `invest_get_trading_statuses`, `invest_get_news`.

  Всё остальное → `ForbiddenToolError` **до** сетевого запроса. Портфельные инструменты (`invest_get_portfolio`, `invest_list_accounts`) в MVP не нужны: портфели синтетические. В белый список их не добавлять.
- Ретраи: 3 попытки с экспоненциальной задержкой на 429, 5xx и сетевые ошибки. Сессия истекла (404 или 400 с сообщением о сессии) → одна переинициализация.
- Ограничитель частоты: не больше 180 запросов в минуту (запас к лимиту 200).
- Логирование: имя инструмента, аргументы, длительность, размер ответа. Заголовки не логируются.
- **Кассеты** (`mcp/cassette.py`), режимы `live` | `record` | `replay`:
  - `record`: каждый ответ сохраняется в `data/cassettes/<tool>/<sha1(args)>.json`;
  - `replay`: отвечает только из кассет, в сеть не ходит; нет кассеты → `CassetteMissError`;
  - режим задаётся параметром клиента и флагом CLI `--mode`.

Тесты (без сети, `httpx.MockTransport` как фейковый сервер):
- рукопожатие и передача `Mcp-Session-Id`;
- SSE-ответ с несколькими событиями: выбирается нужный `id`;
- JSON-ответ;
- `isError`;
- ретрай на 429, затем успех;
- переинициализация при истёкшей сессии;
- `ForbiddenToolError` для `invest_create_order` (запрос не отправлен — проверить счётчик транспорта);
- replay без сети;
- токен не попадает в логи (`caplog`).

### 1.4. Вселенная бумаг (`data/universe.yaml`)

Около 60 инструментов для демо-портфелей и кандидатов на покупку. Формат записи:
```yaml
- id: TMOS_TQTF
  kind: etf
  role: index_fund
  index: IMOEX
  note: Т-Капитал Индекс МосБиржи
```

`role`: `index_fund`, `bond_fund`, `money_fund`, `gold_fund`, `active_fund`, `share`, `ofz`, `corp_bond`. Поле `index` нужно только индексным фондам. Состав:
- **Индексные фонды на IMOEX:** TMOS, SBMX, EQMX. Найди ещё 1–2 через `invest_list_etfs` по описаниям брендов со словами «индекс Мосбиржи».
- **Другие фонды** (проверить наличие, недостающие заменить аналогами и записать замену в отчёт):
  - золото — TGLD;
  - денежный рынок — LQDT, AKMM;
  - облигации — TBRU, SBGB;
  - «вечный портфель» — TRUR;
  - дивидендные или активные акции — DIVD, AKME.
- **Акции, примерно 35** (класс TQBR):
  - банки и финансы: SBER, SBERP, VTBR, T, MOEX;
  - нефть и газ: LKOH, ROSN, TATN, TATNP, GAZP, NVTK, SNGS, SNGSP, SIBN, TRNFP;
  - металлы и добыча: GMKN, CHMF, NLMK, MAGN, PLZL, ALRS, RUAL;
  - удобрения: PHOR;
  - технологии и интернет: YDEX, OZON, HEAD;
  - ритейл: X5, MGNT;
  - телеком и группа АФК: MTSS, RTKM, AFKS;
  - девелоперы: PIKK, SMLT;
  - электроэнергетика: IRAO, HYDR.
  - для групп компаний (слой 3 на этапе 2): SGZH, ETLN (группа АФК Система), MSNG, OGKB, TGKA (группа Газпром). Список групп — в `docs/CONTEXT.md`, раздел 3.
- **ОФЗ:** 3 ликвидных выпуска с разным сроком (короткий, средний, длинный, например 26238). Подобрать через `invest_list_bonds` или `invest_find_instrument`.
- **Корпоративные облигации:** по одному выпуску АФК Системы, МТС, Сегежи, Эталона (для портфеля облигационщика), плюс 1–2 выпуска не из этой группы.

Команда `fm universe verify`: для каждой записи вызывает нужный `get_*`. Результат пишется в `data/universe_resolved.json` (в `.gitignore`), сводка печатается: найдено, не найдено, нет `apiTradeAvailableFlag` (это не ошибка, только пометка). Ненайденные бумаги не валят команду.

### 1.5. Схема БД (`db/schema.sql`, миграция 001)

```sql
CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
CREATE TABLE instruments(
  instrument_id TEXT PRIMARY KEY,         -- TICKER_CLASSCODE
  ticker TEXT NOT NULL, class_code TEXT NOT NULL,
  kind TEXT NOT NULL,                     -- share|etf|bond|currency
  role TEXT, index_id TEXT,               -- из universe.yaml
  isin TEXT, name TEXT, lot INTEGER, currency TEXT,
  asset_uid TEXT, position_uid TEXT, brand_uid TEXT,
  first_day_candle TEXT, maturity_date TEXT,
  dlong REAL, dshort REAL, api_trade_flag INTEGER,
  raw_json TEXT NOT NULL, source TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE assets(asset_uid TEXT PRIMARY KEY, name TEXT, brand_uid TEXT, raw_json TEXT NOT NULL, updated_at TEXT NOT NULL);
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
```

- Мигратор применяет новые файлы `db/migrations/NNN_*.sql` по порядку. Таблицы этапов 2–3 (профили, корреляции, лог вердиктов, отметки) добавятся следующими миграциями.
- Разумные дополнительные поля и индексы добавляй, если нужны, и записывай в отчёт.

### 1.6. Конвейер загрузки (`fm ingest`)

Для каждого инструмента из вселенной:
1. `get_share | get_etf | get_bond` с `INSTRUMENT_ID_TYPE_ID`, `responseView: ["FULL"]` → `instruments`. Для облигаций сохранить `maturity_date`.
2. `get_asset(assetUid)` → `assets`. Затем `get_brand(brand.uid)` → `brands`. Бренды кэшируются: один бренд — один вызов.
3. Свечи `CANDLE_INTERVAL_DAY` с `2020-01-01` по сегодня (с 2020 года — для анализа шоков 2020, 2022 и 2024; у молодых бумаг история начинается с `first1dayCandleDate`) → `candles` (дата в `YYYY-MM-DD` по Москве). Повторный запуск догружает только новые дни (инкремент от последней даты).
4. `get_risk_rates` батчами → обновить `dlong` и `dshort`, если ответ богаче карточки.

Плюс `fm iss weights --index IMOEX` → `index_weights` (последняя доступная дата; запрос публичный, без токена).

Требования:
- Разбор чисел (`ingest/parse.py`): форматы `{"value": "0.125"}`, `{"units": "3", "nano": 500000000}` и строки. Покрыть тестами на примерах.
- Ошибка на одной бумаге пишется в `ingest_errors` и не останавливает конвейер. В конце печатается сводка: сколько бумаг, брендов, свечей, ошибок; время.
- Флаги: `--only SBER_TQBR,TMOS_TQTF`, `--since 2020-01-01`, `--mode live|record|replay`.
- Идемпотентность: повторный запуск не дублирует строки (`UPSERT`).
- Пиши в `FM_DB_PATH` (по умолчанию `data/fm.sqlite`).

### 1.7. Синтетический набор данных (`fm synth generate`, `fm synth load`)

Это основа всех тестов этапов 2–4. Он нужен, чтобы тесты были детерминированными и в git не попадали реальные цены.

Генератор с фиксированным `seed` создаёт:
- **инструменты** с синтетическими кодами (`SYN_*`), брендами, секторами и описаниями на русском в стиле MCP. Реальные тикеры не использовать, чтобы не путать с рыночными данными;
- **дневные цены** за 1500 торговых дней (около 6 лет) из факторной модели: `r_i = β_i·Market + Σ γ_ik·Factor_k + ε_i`. Факторы: рынок, нефть, банки, металлы, технологии, ставка (облигации), золото. Шум у каждой бумаги свой;
- **синтетический индекс** `SYNIDX` с весами (сумма 100%) и **индексные фонды** на него. Цена фонда — взвешенная корзина плюс небольшой шум трекинга, тогда корреляция двух фондов ≈ 0,95–0,99;
- **заранее известные свойства**, на которых этап 2 строит контрольные кейсы. Минимум:
  - два индексных фонда на `SYNIDX` (близнецы);
  - третий фонд на тот же индекс с другим описанием («крупнейшие компании»), в названии слово «индекс» не встречается (скрытый дубль);
  - «активный» фонд, на 70% состоящий из нефтянки и банков, с описанием «дивидендные акции» (скрытая концентрация, состав неизвестен);
  - 4–5 нефтяных акций (взаимная корреляция 0,6–0,8);
  - 3 банка, включая пару обыкновенная и привилегированная акция одного эмитента (бренд общий);
  - золото с отрицательной или около нулевой корреляцией к рынку;
  - фонд денежного рынка (почти нулевая волатильность);
  - 2 ОФЗ с разной дюрацией (чувствительность к фактору ставки);
  - акция с короткой историей (40 дней), для флага `description_based`;
  - бумага, которой нет в синтетической базе (только в каталоге «MCP»), для флага `preliminary`.
- **шоки рынка**: 3 именованных эпизода (`SHOCK_A` 30 дней, `SHOCK_B` 20 дней, `SHOCK_C` 150 дней с плавным снижением) и отдельные дни резкого падения рынка. В шоки корреляции внутри секторов растут: пара «синтетический Сбер — синтетический ВТБ» слабо связана в обычные дни (0,3–0,5 после вычета рынка) и сильно в шоки (больше 0,8). В спокойные годы у них разная собственная динамика: один растёт, другой падает. Это синтетическая копия контрпримера эксперта;
- **группа компаний**: 3–4 синтетические компании одной группы (материнская и дочерние, включая облигации дочек), чтобы этап 2 проверил слой 3;
- **паспорт набора** `tests/fixtures/synthetic/manifest.json`: seed, параметры, список бумаг с ролями и **ожидаемые свойства** (например, `expected_corr(SYN_IDX_A, SYN_IDX_B) >= 0.95`).

Форматы: `instruments.json`, `brands.json`, `candles.csv`, `index_weights.csv`, `manifest.json`. Кроме того, кассеты в формате MCP-ответов (`tests/fixtures/synthetic/cassettes/`), чтобы конвейер `fm ingest --mode replay` прогонялся на синтетике без сети. Это и есть сквозной тест загрузки.

Тесты:
- одинаковый seed даёт побайтно одинаковый результат;
- ожидаемые свойства из паспорта выполняются: посчитать корреляции и проверить пороги;
- `fm ingest --mode replay` на синтетических кассетах заполняет БД с нулём ошибок.

### 1.8. Контракт вердикта (`contracts.py`)

- Pydantic-модели `VerdictRequest`, `VerdictResponse` и вложенные по разделу 7 `docs/CONTEXT.md`. Перечисления для `verdict`, `severity`, `flags`, `operation` (`buy`, `sell`; `sell` в MVP отвечает `no_data`, кроме одного заготовленного примера на этапе 3).
- Валидация:
  - `amount_rub > 0`;
  - позиции с неотрицательной стоимостью;
  - `instrument_id` в формате `TICKER_CLASSCODE` или `SYN_*`;
  - доли в ответе в процентах, 0–100 с допуском округления; сумма `factors_*` ≈ 100.
- `fm contract export` → `docs/contract/verdict_request.schema.json`, `verdict_response.schema.json`.
- `docs/contract/examples/`: 5 примеров ответов (`duplicate`, `increases_skew`, `reduces_skew`, `neutral`, `unavailable`). Тест: каждый пример валиден.
- Формулировки в примерах — только факты (п. 5 правил в контексте). Тест-линтер: в `headline` и `facts` примеров нет слов «купите», «продайте», «рекомендуем», «советуем», «лучше», «стоит». Этот линтер переиспользуется на этапе 2 для всех вердиктов. Вынеси его в `factorminus/wording.py`.

### 1.9. CLI (`fm`)

| Команда | Что делает |
|---|---|
| `fm db init` / `fm db stats` | миграции; счётчики по таблицам, диапазоны дат свечей |
| `fm mcp check` | рукопожатие, число инструментов, наличие всех инструментов из белого списка на сервере; токен не печатается |
| `fm universe verify` | п. 1.4 |
| `fm ingest [...]` | п. 1.6 |
| `fm iss weights --index IMOEX` | п. 1.6 |
| `fm synth generate --seed 42 --out tests/fixtures/synthetic` / `fm synth load --db data/fm_synth.sqlite` | п. 1.7 |
| `fm contract export` | п. 1.8 |

### 1.10. Живая проверка с реальным токеном

Токен лежит в `factorminus/.env`, конфиг подхватывает его автоматически (п. 2 правил в `docs/CONTEXT.md`). Не открывай `.env` и не подставляй токен в команды. Если `fm mcp check` пишет, что токена нет или он отклонён (401/403), пропусти этот пункт и опиши его в отчёте как непроверенный.
1. `fm mcp check`.
2. `fm universe verify`.
3. `fm ingest --mode record` по всей вселенной.
4. `fm iss weights --index IMOEX`.
5. `fm db stats`.

Тесты с маркером `live` (`make test-live`): одна бумага, один фонд, одна облигация, свечи за 30 дней. Проверяют, что структура реальных ответов совпадает с той, на которую рассчитан разбор.

---

## Критерии приёмки этапа 1

1. `make lint` и `make test` зелёные; тесты не ходят в сеть (проверить, например, запуском с отключённой сетью или подменой транспорта, который падает на любой реальный запрос).
2. Вызов инструмента вне белого списка невозможен (тест), токен нигде не логируется (тест), TLS по умолчанию проверяется.
3. `fm synth generate --seed 42` детерминирован, паспорт с ожидаемыми свойствами лежит в git, свойства проверяются тестом.
4. `fm ingest --mode replay` на синтетике заполняет БД без ошибок; повторный запуск не дублирует строки.
5. Контракт экспортирован в JSON Schema, 5 примеров валидны и проходят линтер формулировок.
6. Если был токен: в `data/fm.sqlite` есть не меньше 50 инструментов вселенной с брендами и секторами и свечи с 2020-01-01 (или с даты первой свечи) для большинства из них, плюс веса IMOEX. Сводка `fm db stats` приложена в отчёт. Если токена не было, это явно указано.
7. В git нет `.env`, `data/`, реальных свечей и ответов MCP.
8. `docs/reports/STAGE_1_REPORT.md` содержит:
   - что сделано;
   - фактический вывод команд проверки;
   - таблицу «бумага → найдена / замена / не найдена»;
   - поля MCP, которые оказались не такими, как описано в контексте;
   - время полной загрузки;
   - открытые вопросы к этапу 2.

## Что НЕ делать на этапе 1

- Не считать профили, корреляции и вердикты.
- Не писать API и веб.
- Не трогать файлы вне `factorminus/`.
- Не делать push и PR без просьбы пользователя.
