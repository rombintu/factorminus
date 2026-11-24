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
- `make docker-test-ml` (`Router(preload=True)`, три модели сразу) локально завершился кодом 137 (OOM): Docker Desktop здесь выделено 3,8 ГБ RAM. На раннере GitHub 16 ГБ, тест запускается в `ml.yml`. Результата прогона в CI пока нет: ветка не запушена.

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
| 11 | PR `infra` → `main`, зелёные проверки, ссылка на прогон | **нет**: push и PR ждут разрешения пользователя |
| 12 | `CI.md`, `DEPLOY.md`, `STAGES.md`, шаблон PR, `dependabot.yml`; `CONTEXT.md` и `README.md` | да |
| 13 | Отчёт | этот файл |

## Замеры

| Что | Значение |
|---|---|
| Образ `runtime` | 239 МБ (`docker image inspect … .Size`, arm64; в `docker image ls` — 251 МБ) |
| Образ `runtime-ml` | 3413 МБ: torch CPU 688 МБ, веса laya 2,3 ГБ |
| Сборка `runtime` с нуля | 7 мин 25 с, почти всё время — скачивание базового образа через медленный прокси Docker Hub; повторная сборка с кэшем — 11 с |
| Сборка `runtime-ml` | 252 с (с кэшем зависимостей) и 457 с (после смены слоя зависимостей: заново torch и 2,2 ГБ весов) |
| `make docker-test` | тесты в контейнере 5,9 с |
| `nightly` с нуля | 4 мин 3 с (75 бумаг, 123 177 свечей, равномерный лимит MCP) |
| Покрытие | 91,41%, порог `COV_MIN=89` (91 − 2) |
| Время CI | будет известно после первого прогона на GitHub |

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

## Открытые вопросы

1. **Push и PR.** Ветка `infra` готова, но не запушена. После разрешения: push `infra`, PR `infra` → `main`, ссылка на прогон CI в этом отчёте. Публикацию `:main` в GHCR можно проверить только после merge.
2. **Порядок merge:** сначала PR #1 (`stage-1`), потом PR этапа 1.5. Иначе PR `infra` включит этап 1 целиком.
3. **Защита `main` и видимость пакета GHCR** — настройки репозитория, инструкция и команда в `docs/CI.md`, не применялись.
4. **ML smoke `Router(preload=True)`** локально не помещается в 3,8 ГБ Docker Desktop; для `fm-ml` нужно не меньше 8 ГБ (`docs/DEPLOY.md`). Первый настоящий прогон — `ml.yml` на GitHub.
5. **`docs/tz/STAGE_2.md`** не закоммичен: он не относится к этапу 1.5.
