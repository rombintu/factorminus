# Отчёт по этапу 1: фундамент и данные

Ветка `stage-1`. План: `docs/plans/STAGE_1_PLAN.md`. Дата: 24.11.2026.

Во время работы ТЗ обновилось: в CONTEXT.md добавлены слои связей, в STAGE_1.md свечи теперь с 2020 года, синтетика за 1500 дней с шоками и группой компаний, во вселенной 5 новых акций. Обновления отдельным коммитом `6cbfa42`. Все новые требования выполнены, они перечислены ниже вместе с исходными.

## Что сделано

- **Каркас:** `pyproject.toml`, src-layout, пакет `factorminus`, extras `[ml]` (laya==0.5.1) и `[dev]`, `Makefile` (install, lint, test, test-live, ingest, synth), `.env.example`, `.gitignore`, `README.md`, ruff.
- **Конфиг и секреты** (`config.py`):
  - токен берётся из окружения, иначе из `.env`;
  - в repr и логах токен показан как `t.***`;
  - без токена выводится понятная ошибка;
  - запросы идут только по https на `*.tbank.ru`;
  - `TINVEST_CA_BUNDLE` превращается в `SSLContext`;
  - `TINVEST_INSECURE_SSL=1` печатает предупреждение и запрещён под pytest.
- **MCP-клиент** (`mcp/`):
  - initialize, notifications/initialized и Mcp-Session-Id;
  - разбор JSON и SSE с выбором ответа по `id`;
  - `isError` и JSON-RPC error превращаются в `McpToolError`;
  - 3 попытки на 429, 5xx и сетевые ошибки; на 429 пауза длиннее, `Retry-After` учитывается;
  - одна переинициализация, если сессия истекла;
  - лимитер: равномерно не больше 180 запросов в минуту;
  - белый список из 16 read-only инструментов, `ForbiddenToolError` до сетевого запроса;
  - кассеты в режимах live, record и replay;
  - токен вычищается из текста ошибок.
- **Разбор ответов** (`ingest/parse.py`): Quotation и MoneyValue (`value`, `units/nano`, строки), даты по Москве, карточки, активы, бренды, свечи, ставки риска.
- **БД** (`db/`): мигратор `migrations/NNN_*.sql`, каждая миграция в своей транзакции. Миграция 001 по ТЗ.
- **Вселенная:** `data/universe.yaml` (61 бумага) и `fm universe verify`, результат в `data/universe_resolved.json`.
- **Конвейер** `fm ingest`:
  - шаги: карточки, активы, бренды (с кэшем), свечи, ставки риска;
  - свечи с `--since 2020-01-01` или с даты первой свечи;
  - инкрементальная догрузка и догрузка назад, если `--since` раньше сохранённой истории;
  - UPSERT, ошибки бумаги пишутся в `ingest_errors`;
  - сетевой сбой и отказ в токене прерывают запуск с одной понятной ошибкой.
- **ISS:** `fm iss weights --index IMOEX`.
- **Синтетика:** `fm synth generate --seed 42` и `fm synth load`.
  - 30 бумаг `SYN_*`, 1500 рабочих дней (2020-01-02 … 2025-10-01), факторная модель;
  - индекс SYNIDX и фонды на него;
  - шоки SHOCK_A (30 дней), SHOCK_B (20), SHOCK_C (150, плавное снижение) и 12 дней резкого падения;
  - стресс-фактор по секторам, пара «синтетический Сбер / ВТБ»;
  - группа «Синт-Система»: материнская компания, дочерняя с акцией и облигацией, ещё две дочки с облигациями;
  - паспорт с 29 ожидаемыми свойствами и кассеты в формате MCP.
- **Контракт:** `contracts.py` (v1.0), JSON Schema в `docs/contract/`, 5 примеров, линтер формулировок `wording.py`.
- **CLI** `fm`: все команды из п. 1.9, ошибки выводятся без трейсбека.
- **Ревью:**
  - security-review MCP-клиента и итоговый по ветке: критичных и высоких находок нет, низкие исправлены;
  - code-review по ветке: 5 важных находок, все исправлены с тестами (см. ниже).

## Как проверено (фактический вывод)

```
$ make lint
All checks passed!
34 files already formatted

$ make test
179 passed, 4 skipped in 2.91s          # 4 skipped = live-тесты

$ TINVEST_CA_BUNDLE=data/ca/ru-bundle.pem make test-live
4 passed, 179 deselected in 4.73s

$ fm synth generate --seed 42 && git status --short tests/fixtures | wc -l
seed=42: 30 бумаг, 2020-01-02 … 2025-10-01, 29 ожидаемых свойств → tests/fixtures/synthetic
       0                                 # перегенерация побайтно совпадает с git

$ fm synth load; fm synth load          # replay, без сети
data/fm_synth.sqlite: Бумаг: 29, брендов: 26, новых свечей: 42040, ошибок: 0, время: 0.2 с
data/fm_synth.sqlite: Бумаг: 29, брендов: 26, новых свечей: 0, ошибок: 0, время: 0.0 с

$ fm mcp check
MCP: https://invest-public-api.tbank.ru/mcp
Токен: задан
TLS: CA-бандл …/data/ca/ru-bundle.pem
Рукопожатие: ок, инструментов на сервере: 69
Белый список: 16/16 есть на сервере

$ fm universe verify
Всего 61: найдено 61, не найдено 0, без apiTradeAvailableFlag 9

$ fm ingest --mode record                # полная загрузка с нуля
Бумаг: 61, брендов: 58, новых свечей: 102667, ошибок: 1, время: 198.4 с

$ fm ingest --only SBER_TQBR,TMOS_TQBR,SU26238RMFS4_TQOB   # повторный запуск
Бумаг: 3, брендов: 3, новых свечей: 0, ошибок: 0, время: 5.1 с

$ fm iss weights --index IMOEX
IMOEX: 44 бумаг на 2026-11-23, сумма весов 100.03

$ fm db stats
  assets                   61
  brands                   58
  candles              102667
  index_weights            44
  ingest_errors             1
  ingest_runs               2
  instruments              61
  schema_migrations         1
Свечи: 61 инструментов, даты 2020-01-03 … 2026-11-23
Инструментов с брендом и сектором: 55
Веса IMOEX: 44 бумаг на 2026-11-23

$ git ls-files | grep -E "^data/|(^|/)\.env$|\.sqlite$"
data/universe.yaml
```

У всех 61 бумаги история начинается с 2020-01-03 или с `first1dayCandleDate`. Единственная ошибка загрузки: `AMIX_TQBR brand: в активе нет brand.uid`.

Сеть в тестах закрыта autouse-фикстурой в `tests/conftest.py`: она подменяет `socket.connect` и `create_connection`. `test_network_guard` проверяет, что подмена работает. Live-тесты запускаются только с `--live`.

### Критерии приёмки

| № | Критерий | Статус |
|---|---|---|
| 1 | lint и test зелёные, тесты не ходят в сеть | да |
| 2 | вне белого списка вызвать нельзя, токен не в логах, TLS по умолчанию | да: `test_forbidden_tool_sends_nothing`, `test_token_not_in_logs`, `test_verify_default_and_ca_bundle` |
| 3 | synth детерминирован, паспорт в git, свойства проверяются | да: `test_same_seed_byte_identical`, `test_committed_fixtures_match_generator`, `test_manifest_expected_properties` |
| 4 | replay на синтетике без ошибок, повтор без дублей | да: `tests/test_synth_load.py` |
| 5 | JSON Schema, 5 примеров валидны и проходят линтер | да: `tests/test_contracts.py` |
| 6 | ≥ 50 бумаг с брендами и секторами, свечи с 2020 или с первой свечи, веса IMOEX | да: 55 с сектором, 61 со свечами, 44 веса |
| 7 | в git нет `.env`, `data/`, реальных цен и ответов MCP | да (+ тест `test_only_universe_yaml_tracked_under_data`) |
| 8 | отчёт | этот файл |

## Бумаги: найдена, замена, не найдена

| Бумага | Роль | Статус | Свечи с | Свечей | Сектор бренда | API-торговля |
|---|---|---|---|---|---|---|
| TMOS_TQBR | index_fund | замена класса: TMOS_TQTF → TMOS_TQBR | 2020-08-26 | 1586 | other | нет |
| SBMX_TQBR | index_fund | замена класса: SBMX_TQTF → SBMX_TQBR | 2020-01-03 | 1788 | other | да |
| EQMX_TQBR | index_fund | замена класса: EQMX_TQTF → EQMX_TQBR | 2020-03-02 | 1685 | other | да |
| AMIX_TQBR | index_fund | найдена (добавлена: фонд на IMOEX) | 2026-06-22 | 147 | — | нет |
| TGLD_TQBR | gold_fund | замена класса: TGLD_TQTF → TGLD_TQBR | 2021-08-25 | 1256 | — | нет |
| LQDT_TQBR | money_fund | замена класса: LQDT_TQTF → LQDT_TQBR | 2020-01-20 | 1828 | — | нет |
| AKMM_TQBR | money_fund | замена класса: AKMM_TQTF → AKMM_TQBR | 2022-07-14 | 1227 | other | нет |
| TBRU_TQBR | bond_fund | замена класса: TBRU_TQTF → TBRU_TQBR | 2021-07-12 | 1393 | — | нет |
| SBGB_TQBR | bond_fund | замена класса: SBGB_TQTF → SBGB_TQBR | 2020-01-03 | 1800 | — | да |
| TRUR_TQBR | active_fund | замена класса: TRUR_TQTF → TRUR_TQBR | 2020-01-03 | 1725 | — | нет |
| DIVD_TQBR | active_fund | замена класса: DIVD_TQTF → DIVD_TQBR | 2021-01-19 | 1465 | other | нет |
| AKME_TQBR | active_fund | замена класса: AKME_TQTF → AKME_TQBR | 2020-12-18 | 1572 | other | да |
| SBER_TQBR | share | найдена | 2020-01-03 | 1869 | financial | да |
| SBERP_TQBR | share | найдена | 2020-01-03 | 1869 | financial | да |
| VTBR_TQBR | share | найдена | 2020-01-03 | 1865 | financial | да |
| T_TQBR | share | найдена | 2020-01-03 | 1839 | financial | да |
| MOEX_TQBR | share | найдена | 2020-01-03 | 1869 | financial | да |
| LKOH_TQBR | share | найдена | 2020-01-03 | 1869 | energy | да |
| ROSN_TQBR | share | найдена | 2020-01-03 | 1869 | energy | да |
| TATN_TQBR | share | найдена | 2020-01-03 | 1867 | energy | да |
| TATNP_TQBR | share | найдена | 2020-01-03 | 1867 | energy | да |
| GAZP_TQBR | share | найдена | 2020-01-03 | 1869 | energy | да |
| NVTK_TQBR | share | найдена | 2020-01-03 | 1865 | energy | да |
| SNGS_TQBR | share | найдена | 2020-01-03 | 1869 | energy | да |
| SNGSP_TQBR | share | найдена | 2020-01-03 | 1869 | energy | да |
| SIBN_TQBR | share | найдена | 2020-01-03 | 1861 | energy | да |
| TRNFP_TQBR | share | найдена | 2020-01-03 | 1865 | energy | да |
| GMKN_TQBR | share | найдена | 2020-01-03 | 1865 | materials | да |
| CHMF_TQBR | share | найдена | 2020-01-03 | 1869 | materials | да |
| NLMK_TQBR | share | найдена | 2020-01-03 | 1869 | materials | да |
| MAGN_TQBR | share | найдена | 2020-01-03 | 1869 | materials | да |
| PLZL_TQBR | share | найдена | 2020-01-03 | 1862 | materials | да |
| ALRS_TQBR | share | найдена | 2020-01-03 | 1869 | materials | да |
| RUAL_TQBR | share | найдена | 2020-01-03 | 1865 | materials | да |
| PHOR_TQBR | share | найдена | 2020-01-03 | 1867 | materials | да |
| YDEX_TQBR | share | найдена | 2020-01-03 | 1835 | it | да |
| OZON_TQBR | share | найдена | 2020-11-24 | 1552 | consumer | да |
| HEAD_TQBR | share | найдена | 2020-09-25 | 1651 | it | да |
| X5_TQBR | share | найдена | 2020-01-03 | 1671 | consumer | да |
| MGNT_TQBR | share | найдена | 2020-01-03 | 1869 | consumer | да |
| MTSS_TQBR | share | найдена | 2020-01-03 | 1868 | telecom | да |
| RTKM_TQBR | share | найдена | 2020-01-03 | 1869 | telecom | да |
| AFKS_TQBR | share | найдена | 2020-01-03 | 1869 | financial | да |
| PIKK_TQBR | share | найдена | 2020-01-03 | 1832 | real_estate | нет |
| SMLT_TQBR | share | найдена | 2020-10-29 | 1661 | real_estate | да |
| IRAO_TQBR | share | найдена | 2020-01-03 | 1867 | utilities | да |
| HYDR_TQBR | share | найдена | 2020-01-03 | 1869 | utilities | да |
| SGZH_TQBR | share | найдена | 2021-04-28 | 1537 | materials | да |
| ETLN_TQBR | share | найдена | 2020-02-03 | 1753 | real_estate | да |
| MSNG_TQBR | share | найдена | 2020-01-03 | 1867 | utilities | да |
| OGKB_TQBR | share | найдена | 2020-01-03 | 1863 | utilities | да |
| TGKA_TQBR | share | найдена | 2020-01-03 | 1863 | utilities | да |
| SU26236RMFS8_TQOB | ofz | замена: ОФЗ 26207 не найдена, взята 26236 | 2020-11-25 | 1569 | government | да |
| SU26233RMFS5_TQOB | ofz | найдена | 2020-05-13 | 1705 | government | да |
| SU26238RMFS4_TQOB | ofz | найдена | 2021-06-23 | 1424 | government | да |
| RU000A101012_TQCB | corp_bond | найдена | 2020-01-03 | 1786 | financial | да |
| RU000A1078S8_TQCB | corp_bond | найдена | 2023-11-22 | 825 | telecom | да |
| RU000A105SP3_TQCB | corp_bond | найдена | 2023-02-03 | 1028 | materials | да |
| RU000A105VU7_TQCB | corp_bond | найдена | 2023-02-22 | 1015 | real_estate | да |
| RU000A0JXQ44_TQCB | corp_bond | найдена | 2020-01-03 | 1784 | industrials | да |
| RU000A107050_TQCB | corp_bond | найдена | 2023-10-10 | 847 | financial | да |
| RCMX_TQTF | index_fund | не найдена в TQBR, в TQTF без свежих свечей: исключена | — | 0 | — | — |

## Поля MCP, которые не совпали с описанием в контексте

1. **Фонды в классе `TQTF` больше не получают свечей.** У `TMOS_TQTF` свечи заканчиваются в 2025 году, у `TMOS_TQBR` та же история плюс свежие дни. `invest_list_etfs` отдаёт фонды с `classCode: TQBR`. Поэтому во вселенной все фонды указаны как `_TQBR`. В примере запроса в CONTEXT §7 стоит `TMOS_TQTF`, формат от этого не меняется.
2. **`invest_list_etfs` неполный:** 277 записей, из них 175 `SPBXM`. TMOS в списке нет, через `invest_find_instrument` он находится. Индексные фонды искали через `find_instrument` и описания брендов.
3. **В карточке `get_share|etf|bond` (FULL) нет `uid`.** Ставки риска приходят с `instrumentUid`. Сопоставление идёт по позиции в запросе: порядок сохраняется, для неизвестной бумаги uid пустой. Если число ответов не совпадает с числом бумаг в батче, это ошибка шага. uid пишется в дополнительное поле `instruments.uid`.
4. **`invest_get_risk_rates`** возвращает списки по уровням риска (`longRiskRates[]`, `shortRiskRates[]`: HIGH, STANDARD, ELEMENTARY …), а не одну ставку. `dshort` дополняется только там, где его нет в карточке (у облигаций), и только по уровню, чья long-ставка совпадает с `dlongClient` карточки. Сейчас `dshort` пуст у 18 бумаг.
5. **`time` у дневной свечи и `maturityDate` у облигации — даты без времени** (`"2026-11-18"`). Разбор понимает оба формата.
6. **Числа приходят как `{"value": "0.125"}`**, формат `units/nano` в ответах не встретился. Поддерживаются оба.
7. **Свечи выходных дней:** MCP отдаёт и торги выходного дня. У SBER 876 свечей с 2024 года, из них 140 в субботу и воскресенье, начиная с 2024-04-27. Хранятся как есть, см. вопрос 1.
8. **Сектор бренда пуст** у части фондов: TGLD, LQDT, TBRU, SBGB, TRUR. У AMIX в активе нет `brand.uid`, история с 2026-06-22.
9. **TLS:** `invest-public-api.tbank.ru` и `iss.moex.com` подписаны «Russian Trusted Root CA» (Минцифры), certifi их не знает. Бандл `data/ca/ru-bundle.pem` (не в git) собран из certifi и PEM-файлов, уже лежавших на машине в `~/Downloads/nuc-certs/`. SHA-256 корневого сертификата: `D2:6D:2D:02:31:B7:C3:9F:92:CC:73:85:12:BA:54:10:35:19:E4:40:5D:68:B5:BD:70:3E:97:88:CA:8E:CF:31`. **Сверьте его с отпечатком на Госуслугах**: я проверил только, что цепочки серверов с ним сходятся.
10. **Лимит частоты:** при 180 запросах в минуту в скользящем окне сервер ответил 429 на всплеск (около 150 запросов за 15 с). Лимитер переделан на равномерный интервал 1/3 с.

## Отклонения от ТЗ и решения, принятые самостоятельно

- Фонды в `_TQBR`, а не `_TQTF` (см. выше). **RCMX** исключён: в TQBR не найден, в TQTF без свежих данных. **ОФЗ 26207** не нашлась среди доступных для API, короткая ОФЗ теперь 26236 (2028).
- Миграция лежит в `db/migrations/001_init.sql`, отдельного `db/schema.sql` нет, чтобы схема не жила в двух местах. Сверх ТЗ: `instruments.uid`, индексы `instruments(uid)` и `ingest_errors(run_id)`.
- Свечи с `isComplete: false` (текущий день) не сохраняются. Иначе инкремент начнётся с завтрашнего дня и не обновит финальную цену сегодняшнего.
- Инкремент начинается с последней сохранённой даты, а не со следующей: пересечение в один день безопасно благодаря UPSERT и защищает от свечи с временем в полночь МСК. Если `--since` раньше сохранённой истории и бумага тогда уже торговалась, конвейер догружает прошлое.
- Сетевые ошибки и 401/403 прерывают `fm ingest` и `fm universe verify` целиком, запуск помечается как «прерван». Это решение по итогам code-review: иначе получалась ошибка на каждую бумагу и долгие повторы.
- Добавлена зависимость `pyyaml` (для universe.yaml). `.env` читается простым парсером, без python-dotenv. `numpy<3`: потоки `Generator` не обещают стабильности между мажорными версиями, при смене версии фикстуры перегенерируются.
- Примеры контракта используют `SYN_*`, чтобы в публичном репозитории не было чисел, похожих на рыночные.
- Кассеты пишутся компактным JSON. Синтетические фикстуры занимают около 11 МБ на диске (1500 дней × 30 бумаг, CSV плюс кассеты), в git они хорошо сжимаются.
- Добавлены команда `fm mcp find <запрос>` (поиск бумаг для universe.yaml) и `--until` у `fm ingest` (для replay реальных записей).
- Ревью: security-review MCP-клиента, итоговые security-review и code-review всей ветки.

## Время полной загрузки

`fm ingest --mode record` с нуля по 61 бумаге с 2020-01-01: **198 с** (102 667 свечей). Почти всё это время уходит на равномерный лимитер, около 600 запросов по 0,33 с. Повторный запуск идёт только за новыми днями: 3 бумаги заняли 5 с.

## Открытые вопросы к этапу 2

1. **Свечи выходных дней.** Для корреляций оставить только будни? Или запрашивать `candleSourceType: CANDLE_SOURCE_EXCHANGE`? Сейчас хранятся все свечи.
2. **История фондов короче 2020 года:** TMOS с 2020-08, TGLD с 2021-08, AKMM с 2022-07, AMIX с 2026-06. В шоке 2020 года есть только SBMX, EQMX и LQDT. Для шоков считать фонды по IMOEX или по SBMX как прокси?
3. **Сектор бренда пуст** у 5 фондов, AMIX без бренда. Профиль фонда задавать по `role` из universe.yaml, без сектора бренда?
4. **Группы компаний (слой 3):** во вселенной есть AFKS, MTSS, SGZH, ETLN и облигации АФК, МТС, Сегежи, Эталона, а также GAZP, SIBN, MSNG, OGKB, TGKA. `data/groups.yaml` с источниками будет на этапе 2. В синтетике группа описана в `manifest.json` → `groups`.
5. **Шоки на реальных данных:** для эпизода «февраль–март 2020» свечи есть с 2020-01-03. Худшие 5% дней IMOEX с 2020 года считать по самому индексу? Для этого нужны свечи индекса (ISS или MCP `INSTRUMENT_TYPE_INDEX`), их пока не грузим.
6. **Демо-портфели** из `../analysis/sample_portfolios.json` используют `_TQTF`. На этапе 3 их нужно перевести на `_TQBR`.
