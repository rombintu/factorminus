# Отчёт по этапу 1.5: CI/CD, Docker и контроль этапов

Ветка `infra`, 24.11.2026. ТЗ: `docs/tz/STAGE_1_5_INFRA.md`, план: `docs/plans/STAGE_1_5_PLAN.md`. Логика анализа и контракт вердикта не менялись.

## Что сделано

- **Пути: `FM_HOME` и `FM_DATA_DIR`** (`config.py`):
  - `FM_HOME` задаёт корень, иначе корень ищется по `pyproject.toml`, как раньше;
  - `FM_DATA_DIR` — каталог данных времени выполнения, по умолчанию `<корень>/data`; туда пишутся SQLite, кассеты record и `universe_resolved.json`;
  - конфигурация из git (`universe.yaml`) читается из `<корень>/data` (`CONFIG_DIR`), поэтому том с данными её не закрывает;
  - `FM_DB_PATH` по-прежнему важнее; без переменных локальная работа не изменилась.
- **CA-бандл:**
  - публичные сертификаты Russian Trusted Root CA и два Russian Trusted Sub CA лежат в `certs/`;
  - `scripts/build_ca_bundle.py` собирает certifi + `certs/*.pem` и сверяет SHA-256 каждого файла с зашитым значением; подменённый, лишний или отсутствующий сертификат — ошибка;
  - `make ca-bundle` пишет `data/ca/ru-bundle.pem`; в образе бандл собирается при сборке и подключён по умолчанию.
- **Гигиена репозитория** (`scripts/check_repo_hygiene.py`, `make hygiene`, pre-commit, CI), по файлам из `git ls-files`:
  - запрещены `.env*` (кроме `.env.example`), `*.sqlite*`, `*.log`, кассеты и CA-бандл из `data/`;
  - в `data/` разрешены только `*.yaml`;
  - нет строк вида токена T-Invest `t\.[A-Za-z0-9_-]{80,}` (токен 88 символов);
  - нет файлов больше 1 МБ, кроме списка;
  - нет реальных тикеров в `tests/fixtures/`, кроме списка исключений с причиной;
  - `.gitleaks.toml` добавляет правило для токена поверх стандартных; `.gitignore`: `data/*` + `!data/*.yaml`.
- **Зависимости:**
  - lock-файлы `requirements/{base,dev,ml,build}.txt` с хэшами (`uv pip compile --universal`); torch на Linux — CPU-сборка;
  - `make lock` перегенерирует их, `make lock-check` проверяет, что они соответствуют `pyproject.toml` и что общие пакеты в `dev.txt` и `ml.txt` совпадают;
  - в `dev` добавлены `pytest-cov`, `pre-commit`, `pip-audit`, `uv`.
- **Makefile:**
  - `PY` определяется автоматически (`.venv`, если есть, иначе системный `python`);
  - цели `install`, `install-deps`, `lint`, `lint-docker`, `test-cov`, `hygiene`, `gitleaks`, `audit`, `lock`, `lock-check`, `contract-check`, `ci`, `ci-summary`, `release-notes`, `release-guard`, `ca-bundle`, `docker-build`, `docker-build-ml`, `docker-test`, `docker-test-ml`, `docker-demo`, `docker-check`.
- **Docker:**
  - `Dockerfile` с целями `runtime`, `runtime-ml`, `test`, `test-ml`;
  - `python:3.12-slim` и frontend закреплены по digest;
  - пользователь 10001, `FM_HOME=/app`, `FM_DATA_DIR=/var/lib/factorminus`;
  - зависимости ставятся только из lock-файлов с хэшами, отдельным слоем;
  - пакет ставится из колеса, CA-бандл собирается при сборке, веса laya скачиваются в образ;
  - `.dockerignore` работает как белый список.
- **`compose.yaml`:**
  - сервисы `demo` (синтетика, без сети и токена), `fm`, `nightly`, `fm-ml`;
  - том `fm-data`, `read_only`, `cap_drop: ALL`, `no-new-privileges`;
  - пути и `TINVEST_INSECURE_SSL=0` задаются в compose, значения из `.env` их не переопределяют;
  - оставлено место под сервис `api` этапа 3.
- **CI** (`.github/workflows/ci.yml`):
  - job `lint` (ruff, actionlint, hadolint), `test` (pytest офлайн, порог покрытия 89%), `hygiene` (+ gitleaks по всей истории), `lockfiles`, `contract`, `docker` (сборка `runtime` и `test`, тесты в контейнере, demo-smoke, проверки образа), `audit` (не блокирует);
  - сводка прогона `scripts/ci_summary.py` расширяется файлами `build/ci/*.md`.
- **ML** (`ml.yml`): сборка `runtime-ml` и ML smoke без сети; вручную, раз в неделю и на PR с изменениями ML-файлов; merge не блокирует.
- **CD:**
  - `release.yml` и переиспользуемый `_image.yml`;
  - на push в `main` публикуются `:main` и `:sha-…`; на тег `vX.Y.Z` — `:X.Y.Z`, `:X.Y`, `:latest`, `:vX.Y.Z` и `-ml`-варианты, а также GitHub Release с текстом из отчёта этапа (`scripts/release_notes.py`);
  - multi-arch на нативных раннерах amd64 и arm64, SBOM и provenance;
  - публикация только после CI на том же коммите и только для тегов на коммитах из `main`.
- **Контроль этапов:**
  - `docs/STAGES.md` — журнал этапов;
  - `.github/pull_request_template.md` — шаблон PR;
  - `.github/dependabot.yml` — обновления pip, actions и Docker;
  - `docs/CI.md`: схема, добавление проверок, сводка, релиз, защита `main` с готовой командой `gh api`, видимость GHCR, почему нет live-тестов;
  - `docs/DEPLOY.md` — запуск на любой машине;
  - обновлены `CONTEXT.md` (разделы 4, 8, 10) и `README.md`: бейдж CI, быстрый старт в Docker.

## Как проверено (фактический вывод)

### Локальные проверки

```
$ make ci
All checks passed!
Гигиена: ок, проверено файлов: 106
lock-файлы соответствуют pyproject.toml
dev.txt и ml.txt: общие пакеты закреплены одинаково
схема в docs/contract совпадает с кодом
Required test coverage of 89% reached. Total coverage: 91.41%
294 passed, 8 skipped in 7.59s
make ci exit=0

$ make test-live
7 passed, 289 deselected in 9.03s
```

`make install` на чистом клоне: 13,6 с, затем `make test` — 279 passed, 8 skipped (замер до добавления тестов скриптов релиза), `make lint` чистый.

`lock-check` ловит расхождение: после временного добавления зависимости в `pyproject.toml` `make lock-check` вернул код 2, после отката снова «соответствуют».

### Docker: runtime, test, demo

```
$ make docker-check                       (образ factorminus:local)
ok: нет .env и *.sqlite
ok: нет строк, похожих на токен, в /app и /opt/factorminus
ok: процесс не root (uid 10001, USER 10001:10001)
ok: TINVEST_TOKEN нет в docker history и ENV
ok: fm mcp check без токена: код 2, сообщение о TINVEST_TOKEN, без трейсбека
размер образа: 239 МБ

$ make docker-test
290 passed, 12 skipped in 5.86s          (в образе нет git: 4 теста с маркером git пропущены)
```

Негативная проверка `check_image.sh`: образ поверх `runtime` с `USER root`, `/app/.env`, `x.sqlite` и `ENV TINVEST_TOKEN=t.fake` — все четыре проверки упали, код выхода 1.

`docker compose run --rm demo` из каталога **без `.env`**:

```
/var/lib/factorminus/fm_synth.sqlite: Бумаг: 31, брендов: 29, новых свечей: 45399, ошибок: 1, время: 0.3 с
Ожидаемые ошибки (особенности данных): [('SYN_IDXC', 'brand')]
БД: /var/lib/factorminus/fm_synth.sqlite
  assets                   31
  brands                   29
  candles               45399
  index_weights            13
  ingest_errors             1
  ingest_runs               1
  instruments              32
  schema_migrations         2
Свечи: 32 инструментов, даты 2020-01-02 … 2025-10-01
Инструментов с брендом и сектором: 27
Веса SYNIDX: 13 бумаг на 2025-10-01
Покрытие весов SYNIDX вселенной: 100.0% (нет во вселенной: нет)
Свечи индекса SYNIDX_INDEX: 1500, 2020-01-02 … 2025-10-01
Эмитентов: 27, бумаг без эмитента: ['SYN_IDXC']
Свечей выходных дней: 360
Без сектора бренда: 12.9% (SYN_BONDF, SYN_GOLD, SYN_IDXC, SYN_MONEY)
```

### Docker: реальные данные (`nightly`)

Без `.env`:

```
$ docker compose run --rm nightly
Ошибка: Токен не найден: задайте TINVEST_TOKEN в .env или в окружении
exit code: 2
```

С `.env` пользователя (значение токена нигде не выводилось):

```
$ docker compose run --rm nightly
WARNING factorminus.ingest: ingest AMIX_TQBR brand: в активе нет brand.uid
Бумаг: 75, брендов: 72, новых свечей: 123177, ошибок: 1, время: 239.2 с
IMOEX_INDEX: новых свечей 1749, всего 1749, 2020-01-03 … 2026-11-23
IMOEX: 44 бумаг на 2026-11-23, сумма весов 100.03
real 4:03.30, exit=0

$ docker compose run --rm fm db stats
БД: /var/lib/factorminus/fm.sqlite
  assets                   75
  brands                   72
  candles              124926
  index_weights            44
  ingest_errors             1
  ingest_runs               1
  instruments              76
  schema_migrations         2
Свечи: 76 инструментов, даты 2020-01-03 … 2026-11-23
Инструментов с брендом и сектором: 69
Веса IMOEX: 44 бумаг на 2026-11-23
Покрытие весов IMOEX вселенной: 100.0% (нет во вселенной: нет)
Свечи индекса IMOEX_INDEX: 1749, 2020-01-03 … 2026-11-23
Эмитентов: 64, бумаг без эмитента: ['AMIX_TQBR']
Свечей выходных дней: 8520
Без сектора бренда: 8.0% (AMIX_TQBR, LQDT_TQBR, SBGB_TQBR, TBRU_TQBR, TGLD_TQBR, TRUR_TQBR)
```

Цифры совпадают с локальной загрузкой этапа 1 (124 926 свечей, 64 эмитента, одна ошибка — AMIX без бренда).

### Пересборка с изменённым `universe.yaml` при существующем томе (1.5.0 п. 2)

В `data/universe.yaml` временно добавлена бумага, образ пересобран, том `fm-data` (с `fm.sqlite` и `fm_synth.sqlite`) не трогался:

```
том fm-data: fm.sqlite fm_synth.sqlite
образ до правки:    /app/data/universe.yaml 75 RU000A107050_TQCB
образ после правки: /app/data/universe.yaml 76 TEST_TQBR
```

Правка откатана (`git checkout data/universe.yaml`).

### CA-бандл

```
$ python scripts/build_ca_bundle.py --out …/new-bundle.pem
…/new-bundle.pem: 116 сертификатов (certifi + 3 из certs/)
старый бандл: 116 новый: 116 одинаковый набор: True
$ openssl verify -CAfile certs/russian_trusted_root_ca.pem certs/russian_trusted_sub_ca_*.pem
certs/russian_trusted_sub_ca_2027.pem: OK
certs/russian_trusted_sub_ca_2029.pem: OK
```

Тесты `tests/test_build_ca_bundle.py`:
- отпечаток корневого равен значению из ТЗ;
- подменённый корневой (другой валидный сертификат под его именем), лишний файл, отсутствие корневого и два сертификата в одном файле отвергаются;
- бандл при ошибке не пишется.

### Линтеры workflow и Dockerfile, gitleaks

```
$ actionlint -color=false            (v1.7.12, бинарник из релиза, сверен по checksums)
actionlint rc=0
$ hadolint - < Dockerfile            (ghcr.io/hadolint/hadolint:v2.15.1@sha256:32dac9…, все уровни)
hadolint rc=0
$ make gitleaks
53 commits scanned. … no leaks found
$ make audit                         (pip-audit по base.txt, dev.txt, ml.txt)
No known vulnerabilities found       (×3)
```

### ML: `runtime-ml`

- Как laya хранит веса: `Router` берёт три чекпойнта (english, multilingual, typed-decisions) из одного репозитория Hugging Face `convaiinnovations/laya` (`laya.router.BUNDLE_REPO`, подпапки) через кэш `huggingface_hub` в `$HF_HOME/hub`. Формат — `safetensors`.
- В образ снимок кладётся при сборке через `snapshot_download` закреплённой ревизии `fd4f9dbc…` (`LAYA_REVISION`), без загрузки моделей в память. Затем `HF_HOME=/opt/hf`, `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`.
- Проверка без сети: `docker run --network none factorminus:test-ml` → `Router().predict(...)` на русском тексте — `multilingual share` (и `fund` 0,96 на описании фонда). Сетевых обращений нет.
- `make docker-test-ml` (`Router(preload=True)`, три модели сразу) локально завершился кодом 137 (OOM): Docker Desktop здесь выделено 3,8 ГБ RAM.
- В CI ([прогон `ml.yml`](https://github.com/rombintu/factorminus/actions/runs/45469093975), раннер ubuntu-24.04, сеть в тесте заблокирована): `tests/test_ml_smoke.py` — `1 passed, 1 warning in 9.42s`. Сборка `runtime-ml` на amd64 с холодным кэшем — 13 мин 10 с.

## Критерии приёмки

| # | Критерий | Статус |
|---|---|---|
| 1 | `make lint`, `test`, `hygiene`, `ci`, `test-live` зелёные | да (вывод выше) |
| 2 | `docker-build`, `docker-test`, `demo` без `.env` | да |
| 3 | `nightly` с `.env` загружает, `fm db stats` показывает; без `.env` — ошибка конфигурации | да |
| 4 | Новый `universe.yaml` при существующем томе | да |
| 5 | `FM_HOME`, `FM_DATA_DIR` покрыты тестами, локально без изменений | да (`tests/test_config.py`, 8 тестов, включая подпроцесс с переменными) |
| 6 | Подменённый корневой отвергается | да |
| 7 | `make hygiene` ловит `.env`, `*.sqlite`, кассету, токен; молчит на `t.***` и текущем репозитории | да (`tests/test_hygiene.py`) |
| 8 | В образе нет `.env` и `*.sqlite`, не root, токена нет в `docker history` | да (`make docker-check`) |
| 9 | Размеры и время сборки | да (раздел «Замеры») |
| 10 | actionlint, hadolint; actions по SHA; нет `pull_request_target` | да локально; в CI — после push |
| 11 | PR в `main`, зелёные проверки, ссылка на прогон | да: коммиты этапа добавлены в PR #1 (по решению пользователя), [прогон CI](https://github.com/rombintu/factorminus/actions/runs/45468559985) — все job зелёные; публикация `:main` проверится после merge |
| 12 | `CI.md`, `DEPLOY.md`, `STAGES.md`, шаблон PR, `dependabot.yml`; `CONTEXT.md` и `README.md` | да |
| 13 | Отчёт | этот файл |

## Замеры

| Что | Значение |
|---|---|
| Образ `runtime` | 239 МБ (`docker image inspect … .Size`, arm64; в `docker image ls` — 251 МБ) |
| Образ `runtime-ml` | 3413 МБ: torch CPU 688 МБ, веса laya 2,3 ГБ |
| Сборка `runtime` с нуля | 7 мин 25 с, почти всё время — скачивание базового образа через медленный прокси Docker Hub; повторная сборка с кэшем — 11 с |
| Сборка `runtime-ml` | локально (arm64): 252 с с кэшем зависимостей, 457 с после смены слоя зависимостей; CI (amd64, холодный кэш): 13 мин 10 с |
| `make docker-test` | тесты в контейнере 5,9 с |
| `nightly` с нуля | 4 мин 3 с (75 бумаг, 123 177 свечей, равномерный лимит MCP) |
| Покрытие | 91,41%, порог `COV_MIN=89` (91 − 2) |
| Время CI (первый прогон, холодный кэш) | 2 мин 09 с всего; lint 27 с, test 42 с, hygiene 12 с, lockfiles 22 с, contract 20 с, docker 1 мин 46 с, audit 33 с, summary 17 с |

## Отклонения от ТЗ и решения

- **Ветка `infra` от `stage-1`, а не от `main`.** PR #1 ещё не влит, пользователь выбрал этот вариант. Пока PR #1 не влит, PR `infra` → `main` покажет и коммиты этапа 1.
- **ML-тесты в образе:** в `runtime-ml` нет pytest (`ml.txt` без dev-зависимостей). Добавлена цель `test-ml` (`runtime-ml` + `dev.txt` + ML-тесты), её запускает `make docker-test-ml`. Версии общих пакетов в `dev.txt` и `ml.txt` сверяет `lock-check`.
- **Веса laya скачиваются `snapshot_download`, а не `Router(preload=True)`:** загрузка трёх моделей при сборке упала с нехваткой памяти в Docker VM на 4 ГБ. Результат в кэше тот же.
- **Публикация после CI — через переиспользуемый `ci.yml` (`needs`), а не `workflow_run`.** Образ собирается из того же коммита, весь путь виден в одном прогоне, нет `workflow_run` с правами записи. Цена: на push в `main` CI идёт дважды. Обоснование в `docs/CI.md`.
- **Дополнительные теги образов** `:vX.Y.Z` и `:vX.Y.Z-ml` рядом с `:X.Y.Z`: ТЗ просит в `DEPLOY.md` `FM_TAG=v0.2.0`, а `docker/metadata-action` для semver даёт теги без `v`.
- **Защита релиза:** теги только вида `vX.Y.Z`, job `guard` проверяет, что коммит тега уже в `main` (по итогам security-review).
- **`requirements/build.txt`** (setuptools с хэшем) и сборка пакета без build isolation; `--only-binary=:all:` в образе (по итогам security-review).
- **`pip-audit`** проверяет все три lock-файла, а не только `base.txt`.
- **Промежуточные сертификаты:** отпечаток корневого взят из ТЗ; отпечатки двух Sub CA (действуют до 2027 и 2029) вычислены из локального бандла и проверены подписью корневого (`openssl verify`).
- **Тесты, которым нужен git** (`git ls-files`), помечены маркером `git` и пропускаются вне git-репозитория (в образе `test`).
- **`FM_HOME` и `FM_DATA_DIR` читаются только из окружения**, не из `.env`: от них зависит, где искать `.env`.
- **`make ci` требует сети:** `lock-check` перекомпилирует lock-файлы по индексам PyPI и PyTorch.
- **Шаблон для токена `t\.[A-Za-z0-9_-]{80,}`:** длина токена 88 символов (со слов пользователя), `.env` не открывался.
- **Закреплены по digest** также frontend `docker/dockerfile` и образ buildkit в `setup-buildx-action`. Dependabot их не обновляет, обновлять вручную.
- **Гигиена `.dockerignore` строже ТЗ:** закрыты ещё `**/cassettes`, `*.db`, `*.sqlite3`, `*token*`, `*.key`, `*.pickle`.

## Правки по ревью

- **Security-review** (Dockerfile, compose, workflow) — критичных и высоких находок нет. Исправлено:
  - незакреплённый setuptools при сборке;
  - тег `v*` с любого коммита;
  - ложный «зелёный» в `check_image.sh` при сбое `docker run`, токен в кавычках в `docker history`;
  - плавающие frontend и buildkit;
  - широкий `.dockerignore`;
  - `FM_HOME` и `TINVEST_INSECURE_SSL` из `.env` в контейнере;
  - audit только `base.txt`;
  - `XDG_CACHE_HOME` при read-only;
  - `demo` без сети, `pids_limit`.
  - Не исправлялось: двойной прогон CI на push в `main` — описан как осознанная цена.
- **Code-review ветки** — исправлено:
  - отчёт отсутствовал (этот файл); `release_notes.py` падал трейсбеком без отчёта и пропускал пустой раздел;
  - формулировки закоммиченного ТЗ этапа приведены к нейтральным во всех коммитах ветки (ветка не была запушена);
  - `contract-check` не замечал удалённую схему;
  - отмена прогона CI внутри `release.yml` при быстрых push в `main`;
  - `printf` с переменной в формате (SC2059) в `_image.yml`;
  - фильтр тегов;
  - сверка версий `dev.txt` и `ml.txt`.
  - Не исправлялось: `make ci` без сети (описано в `docs/CI.md`); пропуск удалённых в рабочей копии файлов в гигиене (в CI checkout чистый).

## Правки по ревью 1.5

По `docs/tz/STAGE_1_5_FIXES.md` (ревью 25.11.2026). Коммиты в `stage-1`, каждый пункт отдельно, тесты сначала красные, потом зелёные.

| № | Пункт | Коммит |
|---|---|---|
| 1 | гигиена: файлы данных вне разрешённых папок, тикеры во всех папках с данными, ответы MCP | `7a445a1` |
| 2 | один релиз `v0.1.5` для этапов 1 и 1.5, merge-коммит | `d2fbfc4` |
| 3 | ML smoke на ленивом `Router()`, пиковая память | `f66a00a` |
| 4 | `lock-check` по всем парам `base`/`dev`/`ml` | `4267fee` |
| 5 | литеральный `FROM`, `pip` убран из Dependabot, `make lock-upgrade`, `audit.yml` | `09ed57f` |
| 6 | пути: `FM_HOME` из переданного `env`, умолчания `Settings`, `.env.example` | `3334047` |
| 7 | SPDX-лицензия, заметки о локальной сборке в `DEPLOY.md`, строка 1.5 в `STAGES.md` | `9b38054`, `d2fbfc4` |

### 1. Гигиена

- Файлы с расширениями `csv`, `tsv`, `json`, `jsonl`, `parquet`, `feather`, `xlsx`, `pkl`, `pickle`, `npz`, `npy`, `db` разрешены только в `tests/fixtures/synthetic/`, `tests/cases/`, `docs/contract/`. В остальных местах это нарушение `data-file-outside-allowlist`; исключения — словарь `DATA_FILE_EXCEPTIONS` с причиной (пока пуст).
- Реальные тикеры (`REAL_ID_RE` и тикеры из `universe.yaml`) проверяются во всех трёх папках и в `tests/fixtures/` (правило `real-ticker-in-data`). В список исключений с причиной добавлены две JSON Schema контракта: в них `TMOS_TQBR` — пример формата `InstrumentId` из `contracts.py`, цен нет.
- Ответы MCP (`mcp-response`): в файлах, кроме `.py` и `.md`, ключи `instrumentUid`, `assetUid`, `positionUid`, `figi`, `brandUid` и пара `candles` + `close`. Синтетика повторяет форму ответа MCP (`instruments.json`), поэтому значение, начинающееся с `syn`, и `null` (кейс «нет бренда») нарушением не считаются.

Три пропущенных случая из ревью в одноразовом клоне репозитория (файлы добавлены в индекс, `scripts/check_repo_hygiene.py --root .`):

```
analysis/candles.csv: [data-file-outside-allowlist] файлы данных только в tests/fixtures/synthetic/, tests/cases/, docs/contract/
docs/real_prices.csv: [data-file-outside-allowlist] файлы данных только в tests/fixtures/synthetic/, tests/cases/, docs/contract/
tests/cassettes/invest_get_candles.json: [data-file-outside-allowlist] файлы данных только в tests/fixtures/synthetic/, tests/cases/, docs/contract/
tests/cassettes/invest_get_candles.json: [mcp-response] ключ ответа MCP "instrumentUid"
Гигиена: 4 нарушений в 110 файлах
exit=1
```

Текущий репозиторий: `make hygiene` → `Гигиена: ок, проверено файлов: 108`. Регрессионные тесты: `tests/test_hygiene.py` (51 тест, до правки 29 из них падали).

### 2. Релиз этапов 1 и 1.5

- `docs/STAGES.md`: у этапа 1 в колонке «Тег» — «в составе `v0.1.5`»; у этапа 1.5 ветка — «коммиты в `stage-1`, PR #1»; описано, что PR вливается merge-коммитом и что статус «принят» после merge записывается в PR следующего этапа.
- `scripts/release_notes.py`: `stages_for_tag` возвращает все строки журнала с тегом (в том числе с пометкой «в составе»), по порядку; в текст релиза идут разделы «Что сделано» всех этих отчётов и ссылка на каждый отчёт. Тег из ячейки сравнивается целиком, а не по подстроке.
- `docs/CI.md`: нумерация без отдельного `v0.1.0` (и почему), merge-коммит вместо squash, `"allowed_merge_methods": ["merge"]` в правиле `pull_request` команды ruleset, статус после merge. Ruleset не применялся.

```
$ RELEASE_TAG=v0.1.5 make release-notes && grep -n '^## \|^Отчёт' build/release.md
1:## Этап 1
44:## Этап 1.5
98:## Образы
105:Отчёт этапа 1: https://github.com/rombintu/factorminus/blob/v0.1.5/docs/reports/STAGE_1_REPORT.md
106:Отчёт этапа 1.5: https://github.com/rombintu/factorminus/blob/v0.1.5/docs/reports/STAGE_1_5_REPORT.md
```

### 3. laya на 4 ГБ

- ML smoke проверяет боевой путь: `laya.Router()` без `preload`, русский текст, `routing.model == "multilingual"`. Тест с `Router(preload=True)` помечен `ml_heavy` и запускается только с `--ml-heavy`; в `ml.yml` — `make docker-test-ml ML_PYTEST_ARGS=--ml-heavy`, в сводку прогона попадают итог pytest и пиковая память.
- `make docker-test-ml-run` после pytest печатает `/sys/fs/cgroup/memory.peak` контейнера.

Локально, Docker Desktop с 3,8 ГБ (`docker info`: 4 109 217 792 байт), образ `test-ml`:

```
$ make docker-test-ml
.s                                                                       [100%]
1 passed, 1 skipped in 3.80s
Пиковая память контейнера: 2609 МБ

$ make docker-test-ml-run            # ещё три прогона
1 passed, 1 skipped in 4.14s   Пиковая память контейнера: 2242 МБ
1 passed, 1 skipped in 2.57s   Пиковая память контейнера: 1861 МБ
1 passed, 1 skipped in 2.60s   Пиковая память контейнера: 1855 МБ

$ make docker-test-ml-run ML_PYTEST_ARGS=--ml-heavy
.Killed
Пиковая память контейнера: 3564 МБ
make: *** [docker-test-ml-run] Error 137
```

Ленивый режим помещается в 4 ГБ: пик 1,9–2,6 ГБ. `memory.peak` учитывает и страничный кэш файлов весов, отсюда разброс. `preload=True` на 3,8 ГБ убивается по OOM. `docs/DEPLOY.md`: для `runtime-ml` хватает 4 ГБ, 8 ГБ — только для `preload=True`. В `docs/CONTEXT.md` у описания вызова laya записано, что в проекте `Router()` вызывается лениво.

### 4. Сверка lock-файлов

`scripts/check_locks.py` принимает любое число файлов и сверяет каждую пару; `make lock-check` передаёт `base.txt`, `dev.txt`, `ml.txt`. Тест `test_base_dev_drift_caught`: numpy в `base.txt` отличается от `dev.txt` → код 1 и строка `base.txt / dev.txt: numpy: 2.5.4 != 2.5.5`.

```
$ python scripts/check_locks.py requirements/base.txt requirements/dev.txt requirements/ml.txt
base.txt и dev.txt: общие пакеты закреплены одинаково
base.txt и ml.txt: общие пакеты закреплены одинаково
dev.txt и ml.txt: общие пакеты закреплены одинаково
```

### 5. Dependabot и обновление зависимостей

- `Dockerfile`: `FROM python:3.12-slim@sha256:191083cd… AS base` литерально, без `ARG`.
- `.github/dependabot.yml`: остались `github-actions` и `docker`, `pip` убран (причина — в комментарии файла).
- `make lock-upgrade`: `uv pip compile --upgrade` для `base`, `dev`, `ml`, `build`, `lock_extra_index.py` и сверка пар.
- `.github/workflows/audit.yml`: `make audit` по понедельникам и вручную.
- `docs/CI.md`: раздел «Обновление зависимостей» (`make lock-upgrade` → `make ci` → PR), исправлена фраза про Dependabot и базовый образ, `audit.yml` в схеме.
- `make lint-docker` (actionlint по всем workflow, включая `audit.yml`, и hadolint по `Dockerfile`) — без замечаний, код 0.

### 6. Пути и `.env`

- `.env.example`: строки `FM_DB_PATH=` нет; в комментарии — что переменная есть, по умолчанию `<FM_DATA_DIR>/fm.sqlite`, относительный путь считается от корня.
- `load_settings(env=...)` берёт корень через `repo_root(env)`: от него считаются `.env`, `FM_DATA_DIR`, относительные `FM_DB_PATH` и `TINVEST_CA_BUNDLE`. Тест `test_load_settings_uses_fm_home_from_env`.
- `Settings()` по умолчанию: `data_dir = DATA_DIR`, `db_path = DATA_DIR / "fm.sqlite"` (не относительно текущей папки). Тест `test_settings_defaults_follow_data_dir`.

### 7. Прочее

- `pyproject.toml`: `license = "MIT"`, `license-files = ["LICENSE"]`, `build-system.requires = ["setuptools>=77"]`. Проверка `pip wheel -v --no-build-isolation` в образе с закреплённым setuptools 84.2.1: со старым `pyproject.toml` — `SetuptoolsDeprecationWarning: project.license as a TOML table is deprecated`, с новым предупреждения нет, `Successfully built factorminus`.
- `docs/DEPLOY.md`: в разделах «Демо» и «Обновление» — что локально собранный образ помечается тегом GHCR и после `git pull` нужен `docker compose build`; первая локальная сборка занимает несколько минут.
- `docs/STAGES.md`, строка 1.5: «коммиты в `stage-1`, PR #1».

### Как проверено

```
$ make lint hygiene contract-check test-cov
All checks passed!
52 files already formatted
Гигиена: ок, проверено файлов: 108
схема в docs/contract совпадает с кодом
Required test coverage of 89% reached. Total coverage: 91.48%
337 passed, 9 skipped in 8.43s

$ make docker-build docker-test docker-check docker-demo
332 passed, 14 skipped in 6.21s
ok: нет .env и *.sqlite
ok: нет строк, похожих на токен, в /app и /opt/factorminus
ok: процесс не root (uid 10001, USER 10001:10001)
ok: TINVEST_TOKEN нет в docker history и ENV
ok: fm mcp check без токена: код 2, сообщение о TINVEST_TOKEN, без трейсбека
размер образа: 239 МБ
Покрытие весов SYNIDX вселенной: 100.0% (нет во вселенной: нет)
```

**Не проверено локально:** `make lock-check`, `make lock-upgrade` и `make ci` целиком. С машины не открывался `pypi.org`: таймаут больше 45 минут, `download.pytorch.org` при этом отвечал. Сверка пар lock-файлов (`check_locks.py`) выполнена локально, вывод выше. `requirements/build.txt` не перегенерирован: закреплённый setuptools 84.2.1 удовлетворяет новому `setuptools>=77`, а перекомпиляцию проверит job `lockfiles` в CI.

### CI на `2eb58c0` (PR #1)

- ci: https://github.com/rombintu/factorminus/actions/runs/45564165729. Все jobs зелёные: lint, test, hygiene, lockfiles, contract, docker, audit, summary.
- ml: https://github.com/rombintu/factorminus/actions/runs/45564165643. Зелёный.

```
lockfiles / make lock-check
lock-файлы соответствуют pyproject.toml
base.txt и dev.txt: общие пакеты закреплены одинаково
base.txt и ml.txt: общие пакеты закреплены одинаково
dev.txt и ml.txt: общие пакеты закреплены одинаково

test / make test-cov
Required test coverage of 89% reached. Total coverage: 91.48%
337 passed, 9 skipped in 13.56s

ml / make docker-test-ml ML_PYTEST_ARGS=--ml-heavy
2 passed, 1 warning in 5.55s
Пиковая память контейнера: 4854 МБ
```

`lock-check` в CI подтверждает, что `requirements/build.txt` с `setuptools>=77` перегенерировать не нужно. На раннере GitHub (16 ГБ) `preload=True` проходит с пиком 4,8 ГБ. Это сходится с `docs/DEPLOY.md`: на 4 ГБ этот режим не помещается, 8 ГБ хватает. `make lock-upgrade` по-прежнему не запускался ни локально, ни в CI.

## Упрощение

ТЗ: `docs/tz/STAGE_1_5_SIMPLIFY.md`. Остаётся всё, что защищает секреты, данные, воспроизводимость и корректность; удалено то, что только собирало отчёты или дублировало проверки. Поведение продукта не менялось.

| Коммит | Что |
|---|---|
| `32e0cef` | `release.yml` только на теги `vX.Y.Z`: `guard` → `ci` → один job `image` (`linux/amd64,linux/arm64` через QEMU, binfmt по digest) → `github-release`. `_image.yml` удалён, `:main` и `:sha-…` не публикуются, ML-образ в GHCR не публикуется. compose: `ghcr.io/rombintu/factorminus:${FM_TAG:-latest}`, `fm-ml` — только `build:` и `factorminus:ml` |
| `c2abe16` | текст релиза — `gh release create --generate-notes` со ссылками на `docs/STAGES.md` и `docs/DEPLOY.md`; удалены `scripts/release_notes.py`, тесты, цель `release-notes` |
| `036ce78` | удалены `scripts/ci_summary.py`, тест, `scripts/timed.sh`, job `summary`, таймеры сборки, загрузка артефактов для сводки. `test` пишет в Summary итог pytest и покрытие, `docker` — вывод `check_image.sh`, `ml` — размер образа, итог и пиковую память. В `ci.yml` и `ml.yml` `shell: bash` (`-eo pipefail`), чтобы `| tee` не скрывал падение |
| `d7208cc` | удалены тест `preload=True`, маркер и опция `ml_heavy`, хак `marker.replace` в `conftest.py`, `ML_PYTEST_ARGS`; печать пиковой памяти осталась |
| `9492c7e` | job `audit` убран из `ci.yml`; `audit.yml` — PR с изменениями `requirements/**`, `pyproject.toml`, по понедельникам, вручную |
| `753047b` | `DEFAULT_DB_PATH` удалён, тесты сверяют с `DATA_DIR / DB_FILENAME` |
| `6b6a72e` | из `Makefile` удалены цели, которые никто не вызывал (`test-ml`, `ingest`, `docker-build-ml`, `clean-ci`, а с ними `ci-summary`, `release-notes`), `.PHONY` совпадает с целями; `docs/CI.md` описывает текущую схему (158 → 126 строк) |

`wc -l` инфраструктуры (workflow, `Makefile`, `Dockerfile`, `compose.yaml`, `scripts/`, тесты скриптов):

| Файл | До | После упрощения |
|---|---:|---:|
| `.github/workflows/_image.yml` | 138 | удалён |
| `.github/workflows/ci.yml` | 211 | 142 |
| `.github/workflows/release.yml` | 93 | 95 |
| `.github/workflows/audit.yml` | 27 | 31 |
| `.github/workflows/ml.yml` | 64 | 64 |
| `Makefile` | 192 | 163 |
| `scripts/release_notes.py` + тест | 123 + 128 | удалены |
| `scripts/ci_summary.py` + тест | 92 + 49 | удалены |
| `scripts/timed.sh` | 8 | удалён |
| остальное (`Dockerfile`, `compose.yaml` +1 строка комментария, `check_*`, `build_ca_bundle.py`, тесты) | 1081 | 1082 |
| **Итого** | **2206** | **1577** |

После правок по комментариям к PR (ниже: удалены `build_ca_bundle.py` и его тест, добавлена проверка TLS в `check_image.sh`) — **1415** строк.

Проверено локально после упрощения: `make ci` (с `lock-check`, PyPI снова открывался) — 322 passed, 8 skipped, покрытие 91,47%; `make docker-build docker-test docker-demo docker-check lint-docker` — exit 0, в образе 317 passed, 13 skipped, все проверки `ok`, 239 МБ; `docker compose run --rm demo` без образа в GHCR: `Head ".../manifests/latest": denied`, compose собрал образ локально и отработал (exit 0); `docker compose --profile ml build fm-ml` — `factorminus:ml` 3,58 ГБ, `fm --help` работает.

## Комментарии к PR #1

ТЗ: `docs/tz/STAGE_1_5_PR_REVIEW.md`. Коммиты: `a82c0ac` (TLS), `4a07f2f` (белый список), `6a98621` (песочница по умолчанию).

### 1. `certs/russian_trusted_root_ca.pem`: «найти обходной путь, например http»

**Сделано.** http не используется. Остался один корневой сертификат, он лежит в пакете: `src/factorminus/certs/russian_trusted_root_ca.pem` (`package-data`). `config.tls_context()` при каждом создании сверяет его SHA-256 с `ROOT_CA_SHA256`; подмена файла или не-PEM — `ConfigError`. Затем добавляет его к набору certifi (`certifi` теперь прямая зависимость, lock-файлы перегенерированы: изменилась только строка `via`). `Settings.ssl_verify()` возвращает этот контекст, при `TINVEST_INSECURE_SSL=1` — по-прежнему `False`. Удалены `scripts/build_ca_bundle.py` с тестом, стадия `ca` в `Dockerfile`, `COPY certs`, цель `ca-bundle`, `TINVEST_CA_BUNDLE` (код, compose, ENV образа, `.env.example`, документы). `check_image.sh` проверяет, что в `runtime` строится `tls_context()`. Гигиена: сертификаты и ключи (`.pem`, `.crt`, `.key` и т. п.) допускаются только по пути корневого в пакете (правило `certificate-path`); `.gitleaks.toml` правок не потребовал: путей сертификатов в нём не было. Тест на `http://` в `TINVEST_MCP_URL` → `ConfigError` уже был (`test_mcp_url_must_be_https`).

**Ответ для PR:**
> По http MCP T-Invest не работает (порт 80 не отвечает), а токен в заголовке `Authorization` по http мог бы перехватить любой в той же сети. Вместо этого упростили TLS: в пакете один публичный корневой сертификат Минцифры, его отпечаток проверяется при каждом подключении, промежуточные сертификаты серверы присылают сами. Сборки бандла и переменной `TINVEST_CA_BUNDLE` больше нет.

### 2–3. `certs/russian_trusted_sub_ca_*.pem`: «удалить ключи и вычистить коммиты»

**Сделано.** Оба файла удалены обычным коммитом `a82c0ac` вместе с папкой `certs/`. История не переписывалась, force-push не было. Закрытых ключей там не было: это публичные сертификаты (`BEGIN CERTIFICATE`) НУЦ Минцифры.

**Ответ для PR (к обоим комментариям):**
> Это не ключи, а публичные сертификаты промежуточных УЦ Минцифры: их раздают Госуслуги, закрытых ключей в репозитории нет. Файлы удалены коммитом `a82c0ac`: они не нужны, серверы присылают промежуточный сертификат сами. Историю не переписываем: секрета в ней нет (история проверена на токен и `PRIVATE KEY`, gitleaks в CI смотрит её целиком), а переписывание сломало бы PR и ссылки на коммиты.

### 4. `mcp/allowlist.py`: «проверить все ручки по http и с токеном песочницы»

**Сделано.** `READ_ONLY_TOOLS` сокращён с 16 до 9 инструментов, которые вызывает код: `invest_find_instrument`, `invest_get_share`, `invest_get_etf`, `invest_get_bond`, `invest_get_currency`, `invest_get_asset`, `invest_get_brand`, `invest_get_candles`, `invest_get_risk_rates`. В `tests/test_live.py` — `SMOKE_ARGS` и `SMOKE_FIELD`: параметризованный тест вызывает каждый инструмент и проверяет одно характерное поле (пустое — провал), ответы не печатаются и не сохраняются. Офлайн-тест в обычном CI: `set(SMOKE_ARGS) == READ_ONLY_TOOLS`. Упоминания «16» в README и `docs/CONTEXT.md` обновлены, в отчёте этапа 1 добавлена пометка. По http ничего не проверялось.

`make test-live` на песочнице (`.env` не открывался; адрес из настроек — `https://sandbox-invest-public-api.tbank.ru/mcp`, токен: задан):

```
$ pytest --live -m live -v --tb=no tests/test_live.py
tests/test_live.py::test_tool_smoke[invest_find_instrument] PASSED
tests/test_live.py::test_tool_smoke[invest_get_asset] PASSED
tests/test_live.py::test_tool_smoke[invest_get_bond] PASSED
tests/test_live.py::test_tool_smoke[invest_get_brand] PASSED
tests/test_live.py::test_tool_smoke[invest_get_candles] PASSED
tests/test_live.py::test_tool_smoke[invest_get_currency] PASSED
tests/test_live.py::test_tool_smoke[invest_get_etf] PASSED
tests/test_live.py::test_tool_smoke[invest_get_risk_rates] PASSED
tests/test_live.py::test_tool_smoke[invest_get_share] PASSED
tests/test_live.py::test_card_asset_brand_candles[SBER_TQBR] PASSED
tests/test_live.py::test_card_asset_brand_candles[TMOS_TQBR] PASSED
tests/test_live.py::test_card_asset_brand_candles[SU26238RMFS4_TQOB] PASSED
tests/test_live.py::test_iss_imoex_weights PASSED
tests/test_live.py::test_same_issuer_different_brand_live[SBER-SBERP] PASSED
tests/test_live.py::test_same_issuer_different_brand_live[MTSS-bond] PASSED
tests/test_live.py::test_imoex_index_candles_live PASSED
16 passed in 12.74s

$ make test-live
16 passed, 325 deselected in 13.41s
```

ISS (`test_iss_imoex_weights`) прошёл через `tls_context()` с одним корневым сертификатом. `invest_get_risk_rates` на песочнице вернул непустые ставки, хотя документация пишет, что ставки риска там «не рассчитываются».

**Решение по `DEFAULT_MCP_URL`:** все 9 инструментов прошли, поэтому `DEFAULT_MCP_URL` и `.env.example` переключены на песочницу (`https://sandbox-invest-public-api.tbank.ru/mcp`, тест `test_default_mcp_url_is_sandbox`). `docs/DEPLOY.md`: «для сбора данных нужен токен песочницы, боевой не нужен», где его выпустить и про 7 дней; запасной вариант — боевой адрес и токен «Только чтение».

**Ответ для PR:**
> Проверили на песочнице, по http — нет (по http MCP не работает, а токен ушёл бы открытым текстом). Белый список сократили до 9 инструментов, которые реально вызывает код; на каждый есть live-тест, и офлайн-тест в CI не даст добавить инструмент без такой проверки. Все 9 на песочнице проходят, поэтому адрес по умолчанию теперь песочница, а для сбора данных нужен только токен песочницы.

### Как проверено

```
$ make ci
All checks passed!
46 files already formatted
Гигиена: ок, проверено файлов: 99
lock-файлы соответствуют pyproject.toml
base.txt и dev.txt: общие пакеты закреплены одинаково
base.txt и ml.txt: общие пакеты закреплены одинаково
dev.txt и ml.txt: общие пакеты закреплены одинаково
схема в docs/contract совпадает с кодом
Required test coverage of 89% reached. Total coverage: 91.55%
325 passed, 17 skipped in 7.89s

$ make lint-docker
(actionlint и hadolint без замечаний, exit 0)
```

**Не проверено локально:** `make docker-build docker-test docker-demo docker-check` после TLS-правок. После добавления `certifi` в `dependencies` в `base.txt` изменилась строка `via`, и слой зависимостей образа пересобирается, а из контейнеров Docker Desktop TLS-рукопожатие с PyPI не проходило больше 45 минут (`_ssl.c: The handshake operation timed out`; с хоста PyPI отвечал, `make ci` с `lock-check` прошёл). Сборку образа, тесты в нём, демо и `check_image.sh` с новой проверкой `tls_context()` выполняет job `docker` в CI на PR #1.

## Открытые вопросы

1. **PR.** По решению пользователя коммиты этапа 1.5 добавлены в PR #1 (ветка `stage-1`, fast-forward), отдельного PR нет. Публикацию образа в GHCR можно проверить только после merge и тега `v0.1.5` (на push в `main` образы больше не публикуются).
2. **`ml.yml` на PR запускается при каждом push:** фильтр `paths` для `pull_request` сравнивает весь diff PR с базой, а в нём есть `Dockerfile`; новый push отменяет предыдущий прогон (около 16 минут). На следующих этапах, когда `Dockerfile` не меняется, `ml` будет запускаться только по расписанию и вручную.
3. **Защита `main` и видимость пакета GHCR** — настройки репозитория, инструкция и команда в `docs/CI.md`, не применялись.
4. **laya в Docker на Mac:** закрыто правками по ревью 1.5 (п. 3). Ленивый `Router()` проходит на 3,8 ГБ (пик 1,9–2,6 ГБ). Тест `preload=True` удалён при упрощении: в проекте этот путь не используется.
5. **`docs/tz/STAGE_2.md`** не закоммичен: он не относится к этапу 1.5.
