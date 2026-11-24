# Этап 1.5: CI/CD, Docker и контроль этапов. План

**Цель:** проект собирается и проверяется одинаково локально, в Docker и в GitHub Actions; релиз по тегу публикует образы в GHCR. Логика анализа и контракт не меняются.

**ТЗ:** `docs/tz/STAGE_1_5_INFRA.md`. Ветка `infra` от `stage-1`: PR #1 ещё не влит, пользователь выбрал этот вариант.

## Общие ограничения

- В образе и слоях нет `.env`, токена, `*.sqlite`, кассет, `data/ca`. Токен приходит только при запуске (`env_file`).
- Live-тесты и `TINVEST_TOKEN` в CI не попадают.
- Только `pull_request`, actions закреплены по SHA, `permissions: contents: read` по умолчанию.
- Новые проверки — цели `Makefile`, YAML только вызывает их.
- Правки в `src/` — только пути, CA-бандл и запуск в контейнере.

## Задачи

### 1. Пути: `FM_HOME`, `FM_DATA_DIR`
- `config.repo_root(env)`: `FM_HOME`, иначе поиск `pyproject.toml`; `config.data_dir(env, root)`: `FM_DATA_DIR` (относительный — от корня), иначе `<корень>/data`. Константы `REPO_ROOT`, `DATA_DIR`, `CONFIG_DIR = REPO_ROOT/"data"`.
- Пишется в `DATA_DIR`: `fm.sqlite` (если нет `FM_DB_PATH`), `fm_synth.sqlite`, `cassettes/`, `universe_resolved.json`. Читается из `CONFIG_DIR`: `universe.yaml`.
- Тесты: оба режима, относительные пути, `FM_DB_PATH` важнее, подпроцесс с переменными видит новые константы.

### 2. CA-бандл
- `certs/`: российские корневой и промежуточный сертификаты из локального бандла, которых нет в certifi.
- `scripts/build_ca_bundle.py`: сверка SHA-256 каждого файла `certs/*.pem` с зашитыми отпечатками (корневой — из ТЗ), лишний или подменённый файл — ошибка; вывод certifi + `certs/*.pem`.
- Тесты: настоящий набор проходит, подмена и лишний файл отвергаются.

### 3. Гигиена
- `scripts/check_repo_hygiene.py` по `git ls-files`: запрещённые пути, только `data/*.yaml`, строка-токен `t\.[A-Za-z0-9_-]{80,}` (токен 88 символов), файлы > 1 МБ кроме списка, не-`SYN_` тикеры в `tests/fixtures/` кроме списка исключений.
- `.gitignore`: `data/*` + `!data/*.yaml`. `.gitleaks.toml`, `.pre-commit-config.yaml`.
- Тесты на «да» и «нет», текущий репозиторий чистый.

### 4. Makefile, зависимости, ML-маркер
- `PY` с автоопределением `.venv`; цели `install`, `lock`, `lock-check`, `test-cov`, `hygiene`, `contract-check`, `ci`, `ca-bundle`, `docker-*`, `test-ml`.
- `dev`: `pytest-cov`, `pre-commit`, `pip-audit`, `uv`. Lock-файлы `requirements/{base,dev,ml}.txt`, torch CPU.
- `--ml` и маркер `ml` в `conftest.py`, `tests/test_ml_smoke.py`.

### 5. Docker
- `Dockerfile`: `runtime`, `runtime-ml`, `test`; non-root 10001, `FM_HOME=/app`, `FM_DATA_DIR=/var/lib/factorminus`, бандл собирается при сборке, веса laya в образе.
- `.dockerignore`, `compose.yaml` (`demo`, `fm`, `nightly`, `fm-ml`, место под `api`).
- `scripts/check_image.sh`: нет `.env` и `*.sqlite`, не root, `docker history` без токена, `fm mcp check` без токена — понятная ошибка.
- Проверка: пересборка с изменённым `universe.yaml` при существующем томе.

### 6. CI/CD
- `ci.yml`: `lint` (+ actionlint, hadolint), `test`, `hygiene` (+ gitleaks), `lockfiles`, `contract`, `docker`, `audit`; сводка `scripts/ci_summary.py` из JUnit, coverage и `build/ci/*.md`.
- `ml.yml`, `release.yml` (multi-arch на нативных раннерах, публикация после зелёного CI), `scripts/release_notes.py`.
- `dependabot.yml`, шаблон PR.

### 7. Документы и сдача
- `docs/CI.md`, `docs/DEPLOY.md`, `docs/STAGES.md`, `CONTEXT.md`, `README.md`.
- Security-review Docker/compose/workflow, code-review ветки, исправления.
- Отчёт `docs/reports/STAGE_1_5_REPORT.md`, затем вопрос пользователю о push и PR.
