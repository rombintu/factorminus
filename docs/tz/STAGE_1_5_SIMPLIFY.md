# Упрощение инфраструктуры этапа 1.5

Ревью правок 25.11.2026. Все 7 пунктов `STAGE_1_5_FIXES.md` проверены и приняты:
- локально `make lint`, `hygiene`, `contract-check`, `test-cov`: 337 passed, покрытие 91,48%;
- сверка всех пар lock-файлов чистая;
- гигиена ловит все подложенные файлы из ревью, включая ответ MCP в `data/*.yaml`;
- CI на PR #1 зелёный.

Теперь главное замечание. Инфраструктура этапа 1.5 занимает около 2 400 строк (workflow, Makefile, Dockerfile, скрипты и их тесты), а весь продуктовый код — около 3 000. Для MVP хакатона это перегруз. Часть его заложило само ТЗ этапа 1.5: сводка из файлов `build/ci/*.md`, текст релиза из отчётов, multi-arch на нативных раннерах. Это решение пересматривается.

**Принцип:** оставляем всё, что защищает:
- секреты и рыночные данные (гигиена, gitleaks, проверки образа);
- воспроизводимость (lock-файлы с хэшами, закрепление по SHA и digest);
- корректность (тесты, контракт, CA с отпечатком).

Убираем то, что только собирает отчёты или дублирует проверки. Ветка `stage-1`, отдельные коммиты, без изменения поведения продукта. В конце допиши раздел «Упрощение» в отчёт этапа 1.5: что удалено и сколько строк стало (`wc -l` до и после).

---

## 1. Релиз только по тегу, одна сборка multi-arch, без ML-образа в GHCR

Сейчас:
- push в `main` запускает CI дважды (`ci.yml` и `release.yml` → `ci.yml`);
- `_image.yml` (138 строк) собирает платформы на разных раннерах и склеивает манифест;
- ML-образ публикуется только по тегу, а compose по умолчанию ищет `:main-ml`, которого не бывает.

Сделать:
- `release.yml` срабатывает **только на теги** `vX.Y.Z`: `guard` → `ci` (переиспользуемый) → один job `docker/build-push-action` с `platforms: linux/amd64,linux/arm64` (QEMU) → `gh release create`. В `runtime` только колёса numpy, pydantic и подобные, под QEMU это пара минут. Публикация `:main` и `:sha-…` убирается.
- `_image.yml` удалить.
- ML-образ в GHCR не публиковать: он нужен только для `fm build` с laya, и его собирают локально (`docker compose --profile ml build fm-ml`). У `fm-ml` в compose остаётся только `build:` и локальное имя `factorminus:ml`.
- compose: образ по умолчанию `ghcr.io/rombintu/factorminus:${FM_TAG:-latest}`. Пока релиза нет, compose соберёт образ локально, это уже проверено.
- Поправь `docs/DEPLOY.md` и `docs/CI.md` под новую схему: теги образов `X.Y.Z`, `X.Y`, `latest`, `vX.Y.Z`.

## 2. Текст релиза без разбора `docs/STAGES.md`

`scripts/release_notes.py` (123 строки) и его тесты (128 строк) разбирают Markdown-таблицу журнала и вырезают разделы из отчётов. Это хрупко: любая правка таблицы ломает релиз.

Сделать:
- `gh release create "$TAG" --verify-tag --generate-notes --notes "Отчёты этапов: docs/STAGES.md. Запуск: docs/DEPLOY.md."` (GitHub сам перечислит PR и коммиты).
- Удалить `scripts/release_notes.py`, `tests/test_release_notes.py`, цель `release-notes`.
- В `docs/STAGES.md` колонка «Тег» остаётся как справка для людей.

## 3. Сводка CI без отдельного скрипта и job

`scripts/ci_summary.py`, `tests/test_ci_summary.py`, `scripts/timed.sh`, таймеры сборки, job `summary` со скачиванием артефактов и `build/ci/*.md`. Всё это повторяет то, что уже видно в логах и в статусах проверок.

Сделать:
- удалить скрипт, тест, `timed.sh`, job `summary`, таймеры и upload артефактов, нужных только для сводки;
- где строка в сводке действительно полезна, job пишет её сам одной командой, например `tail -1` вывода pytest или вывод `check_image.sh` → `>> "$GITHUB_STEP_SUMMARY"`;
- этап 2 будет добавлять метрики eval так же: шаг в существующем job печатает markdown в `$GITHUB_STEP_SUMMARY`.

## 4. Убрать `ml_heavy`

В проекте laya вызывается только лениво (`Router()`). Тест `preload=True` проверяет путь, которым никто не пользуется. Ради него появились опция `--ml-heavy`, маркер, хак `marker.replace('_', '-')` в `conftest.py` и `ML_PYTEST_ARGS`.

Удалить:
- тест;
- маркер и опцию;
- хак в `conftest.py`;
- `ML_PYTEST_ARGS`.

Печать пиковой памяти в `docker-test-ml-run` оставить: это полезный замер.

## 5. Аудит зависимостей — в одном месте

Сейчас `make audit` идёт в `ci.yml` на каждом PR (не блокирует, то есть шум) и в `audit.yml` по расписанию.

Сделать: job `audit` из `ci.yml` убрать. В `audit.yml` добавить триггер `pull_request` с `paths: ["requirements/**", "pyproject.toml"]`, чтобы новые версии проверялись в момент обновления.

## 6. Мелочи

- `DEFAULT_DB_PATH` в `config.py` используется только в одном тесте. Убери константу, тест пусть проверяет `DATA_DIR / DB_FILENAME`.
- После всех удалений пройди по `Makefile` и убери цели, которые никто не вызывает (`.PHONY` тоже). Каждая оставшаяся цель вызывается из CI, из `docs/` или из другой цели.
- `docs/CI.md` сократи под новую схему. Документ описывает, что есть, а не историю решений: история — в отчёте.

---

## Что НЕ трогать

- `check_repo_hygiene.py` с тестами, gitleaks, `check_image.sh`;
- `build_ca_bundle.py` и `certs/`: их переделывает следующее ТЗ `STAGE_1_5_PR_REVIEW.md`, в этом не трогать;
- lock-файлы с хэшами, `check_locks.py`, `lock-check`, `lock-upgrade`;
- закрепление actions по SHA и образов по digest;
- `contract-check`, `lint-docker` (actionlint, hadolint);
- `ml.yml` (ленивый smoke + память), цели Dockerfile `runtime`, `runtime-ml`, `test`, `test-ml`;
- `FM_HOME`, `FM_DATA_DIR`, compose-харднинг (`read_only`, `cap_drop`, `network_mode: none` у демо).

## Критерии приёмки

1. `make ci`, `make docker-test`, `make docker-demo`, `make docker-check`, `make lint-docker` зелёные.
2. Нет `_image.yml`, `release_notes.py`, `ci_summary.py`, `timed.sh`, `ml_heavy`, job `summary` и `audit` в `ci.yml`.
3. `release.yml` срабатывает только на теги `vX.Y.Z`. На push в `main` CI идёт один раз.
4. Compose: `demo` без `.env` работает, а если образа в GHCR нет, собирает его локально. `fm-ml` собирается локально.
5. CI на PR #1 зелёный, ссылка в отчёте. В разделе «Упрощение»: список удалённого и `wc -l` инфраструктуры до и после.
