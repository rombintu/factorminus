# CI/CD

Все проверки — цели `Makefile`. Workflow в `.github/workflows/` только вызывают их, поэтому локально проверяется то же, что в CI: `make ci` (всё, кроме Docker и gitleaks). `make ci` нужна сеть до PyPI и индекса PyTorch: `lock-check` перекомпилирует lock-файлы.

## Схема

| Workflow | Когда | Что делает |
|---|---|---|
| `ci.yml` | PR в `main`, push в `main`, вручную; вызывается из `release.yml` | проверки ниже + сводка прогона |
| `ml.yml` | вручную, по понедельникам, PR с изменениями `analysis/labeler*`, `requirements/ml.txt`, `Dockerfile` | сборка `runtime-ml` и ML smoke без сети; merge не блокирует |
| `release.yml` | push в `main`, теги `v*` | CI → публикация образов в GHCR → GitHub Release (на тег) |
| `_image.yml` | только из `release.yml` | сборка образа на нативных раннерах amd64/arm64, multi-arch манифест, SBOM, provenance |

### Задачи `ci.yml`

| Job | Цель Makefile | Блокирует merge |
|---|---|---|
| `lint` | `make lint` (ruff check + format --check), `make lint-docker` (actionlint, hadolint) | да |
| `test` | `make test-cov`: pytest офлайн, покрытие с порогом `COV_MIN` | да |
| `hygiene` | `make hygiene` (`scripts/check_repo_hygiene.py`): секреты, `.env`, SQLite; файлы данных (`csv`, `json`, `parquet`, `db` и т. п.) только в `tests/fixtures/synthetic/`, `tests/cases/`, `docs/contract/`; там же нет реальных тикеров; в файлах, кроме `.py` и `.md`, нет ключей ответа MCP. `make gitleaks` по всей истории | да |
| `lockfiles` | `make lock-check`: перекомпиляция lock-файлов не даёт diff; общие пакеты закреплены одинаково в каждой паре `base.txt`, `dev.txt`, `ml.txt` (runtime собран из `base.txt`, тесты идут на `dev.txt`) | да |
| `contract` | `make contract-check`: схемы в `docs/contract/` совпадают с кодом, набор файлов тот же | да |
| `docker` | сборка `runtime` и `test`, `make docker-test-run`, `make docker-demo` (smoke на синтетике без `.env`), `make docker-check` | да |
| `audit` | `make audit` (pip-audit по `requirements/base.txt`) | нет: `continue-on-error`, исключения с причиной в `.github/pip-audit-ignore.txt` |
| `summary` | `make ci-summary` | нет |

Порог покрытия `COV_MIN` в `Makefile`: замер этапа 1.5 (91,4%) минус 2 п.п. = 89. Порог только растёт.

## Как добавить проверку для нового этапа

1. Новая цель в `Makefile` (например, `eval`), которая работает локально.
2. Вызов этой цели шагом `- run: make eval` в существующем job `ci.yml` (обычно `test`).
3. Цель пишет секцию сводки в `build/ci/NN-имя.md` (Markdown); job загружает `build/ci/` артефактом `ci-<job>`, и `summary` её подхватит. `scripts/ci_summary.py` менять не нужно.
4. Если проверка должна блокировать merge, а job новый — добавить его в обязательные проверки (раздел «Защита main»).

Новый job нужен, только если проверке нужен другой образ или раннер. Цель добавляется и в `make ci`, если она быстрая и не требует Docker.

## Как читать сводку прогона

Страница прогона → job `summary` → Summary:
- **Тесты**: passed / skipped / failed из JUnit, покрытие из coverage XML;
- **Время сборки образов**: секунды сборки `runtime` (job `docker`);
- **Гигиена репозитория**: результат `make hygiene` и список нарушений;
- **Образ**: размер и проверки (нет `.env` и `*.sqlite`, не root, токена нет в `docker history`, `fm mcp check` без токена — понятная ошибка);
- **Задачи**: результат каждого job.

Этап 2 добавит сюда метрики `fm eval`, этап 4 — e2e (через `build/ci/*.md`).

## Как выпустить релиз

Нумерация: `v0.1.5` — этапы 1 и 1.5 (сданы одним PR #1, поэтому релиз один), `v0.2.0` — этап 2, `v0.3.0` — этап 3, `v1.0.0` — Demo Day. Тег вида `stage-1` не используется: он совпадает с именем ветки. Отдельного `v0.1.0` нет: в последнем коммите этапа 1 ещё нет workflow релиза, а тег на merge-коммите дал бы два релиза одного кода.

PR этапа вливается **merge-коммитом**, не squash: в `main` остаются отдельные коммиты этапа и правок по ревью, и отчёт ссылается на реальные коммиты. Прямой push в `main` закрыт, поэтому статус этапа «принят» и тег в `docs/STAGES.md` после merge обновляются в PR следующего этапа.

1. PR этапа влит в `main` merge-коммитом, CI зелёный, строка этапа в `docs/STAGES.md` с тегом и ссылкой на отчёт есть (у этапов, вошедших в общий релиз, — «в составе `vX.Y.Z`»).
2. Пользователь ставит тег на коммит в `main`:
   ```bash
   git switch main && git pull
   git tag -a v0.1.5 -m "Этап 1.5: CI/CD, Docker и контроль этапов"
   git push origin v0.1.5
   ```
3. `release.yml` реагирует только на теги вида `vX.Y.Z`. Job `guard` (`make release-guard`) проверяет формат тега и то, что его коммит уже входит в `main`; иначе публикация не начинается. Затем `release.yml` прогоняет CI на этом коммите, публикует `ghcr.io/rombintu/factorminus:0.1.5`, `:0.1`, `:latest`, `:v0.1.5` (runtime) и `:0.1.5-ml`, `:v0.1.5-ml` (runtime-ml), затем создаёт GitHub Release. Текст: разделы «Что сделано» из отчётов всех этапов с этим тегом, по порядку (`scripts/release_notes.py`), ссылки на образы и на прогон CI. Проверить текст заранее: `RELEASE_TAG=v0.1.5 make release-notes && cat build/release.md`.

Push в `main` публикует `:main` и `:sha-<коротк>` (только runtime).

**Почему публикация через переиспользуемый `ci.yml`, а не `workflow_run`.** Job-ы публикации зависят (`needs`) от вызова `ci.yml` в том же прогоне, поэтому образ собирается ровно из проверенного коммита, а весь путь «проверки → публикация» виден на одной странице. `workflow_run` запускается в контексте основной ветки с правами записи и требует вручную сверять `head_sha`; для публичного репозитория это лишний риск. Цена: на push в `main` CI идёт дважды (сам `ci.yml` и вызов из `release.yml`). Новый push отменяет предыдущий прогон `ci.yml` той же ветки, но не прогон внутри `release.yml`: каждый коммит в `main` доходит до публикации `:sha-<коротк>`.

## Пакет GHCR

После первой публикации пакет `factorminus` приватный. Сделать публичным (решает пользователь):
GitHub → профиль `rombintu` → Packages → `factorminus` → Package settings → Danger Zone → Change visibility → Public. Там же: Manage Actions access → репозиторий `factorminus` с ролью Write (обычно выставляется автоматически при первой публикации из workflow).

Пока пакет приватный, `docker compose pull` требует `docker login ghcr.io` с личным токеном `read:packages`; без этого используйте `docker compose build`.

## Защита `main`

Настраивает пользователь (это настройка репозитория). Нужно:
- merge только через PR и только merge-коммитом (без squash и rebase);
- обязательные проверки `lint`, `test`, `hygiene`, `lockfiles`, `contract`, `docker`;
- без force push и удаления ветки.

**Через веб-интерфейс:** Settings → Rules → Rulesets → New branch ruleset → имя `main`, Enforcement: Active, Target: Default branch → включить Restrict deletions, Block force pushes, Require a pull request before merging (Required approvals: 0, если в команде один разработчик; Allowed merge methods: только Merge), Require status checks to pass (Require branches to be up to date; добавить `lint`, `test`, `hygiene`, `lockfiles`, `contract`, `docker` — они появятся в списке после первого прогона CI) → Create.

**Одной командой** (применяется только по явной просьбе пользователя):

```bash
gh api -X POST repos/rombintu/factorminus/rulesets --input - <<'EOF'
{
  "name": "main",
  "target": "branch",
  "enforcement": "active",
  "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
  "rules": [
    {"type": "deletion"},
    {"type": "non_fast_forward"},
    {"type": "pull_request", "parameters": {
      "required_approving_review_count": 0,
      "dismiss_stale_reviews_on_push": false,
      "require_code_owner_review": false,
      "require_last_push_approval": false,
      "required_review_thread_resolution": false,
      "allowed_merge_methods": ["merge"]
    }},
    {"type": "required_status_checks", "parameters": {
      "strict_required_status_checks_policy": true,
      "required_status_checks": [
        {"context": "lint"}, {"context": "test"}, {"context": "hygiene"},
        {"context": "lockfiles"}, {"context": "contract"}, {"context": "docker"}
      ]
    }}
  ]
}
EOF
```

Проверка: `gh api repos/rombintu/factorminus/rulesets`.

## Безопасность workflow

- Только `pull_request`, нигде нет `pull_request_target`: PR из чужих форков не получают секретов и прав записи.
- Все сторонние actions закреплены по полному SHA коммита с комментарием версии; базовый образ, frontend `docker/dockerfile`, образ buildkit (`driver-opts` у `setup-buildx-action`) и контейнеры инструментов (actionlint, hadolint, gitleaks) — по digest. Dependabot обновляет actions и базовый образ; digest buildkit и инструментов обновляются вручную.
- Зависимости ставятся только из lock-файлов с хэшами (`--require-hashes`, в образе ещё `--only-binary=:all:`). setuptools для сборки пакета тоже закреплён (`requirements/build.txt`), сборка идёт без build isolation.
- `permissions` на уровне workflow — `contents: read`; `packages: write` только у job-ов публикации в `_image.yml`, `contents: write` только у job создания Release.
- `actions/checkout` с `persist-credentials: false`: токен не остаётся в `.git/config`.
- Секретов, кроме встроенного `GITHUB_TOKEN`, нет. `TINVEST_TOKEN` в GitHub Secrets не добавляется.
- Артефакты CI (JUnit, покрытие, сводка, SBOM) содержат только синтетику.

## Почему live-тестов нет в CI

- Репозиторий публичный: логи и артефакты видны всем.
- Ответы MCP и реальные цены не должны попадать в логи и артефакты; условия T-Invest запрещают передавать данные MCP третьим лицам.
- Раннеры GitHub находятся за рубежом, доступ к API T-Invest оттуда не гарантирован.

Live-проверка остаётся локальной: `make test-live` с `.env`.

**Если позже понадобится live-проверка в CI** (не сделано, только описание): отдельный workflow `live.yml` только с `workflow_dispatch`, job с `environment: live`, у окружения — обязательное подтверждение (Required reviewers) и секрет `TINVEST_TOKEN` (токен «только чтение») в окружении, а не в репозитории. Вывод тестов — только «прошёл / не прошёл» и счётчики, без ответов MCP; артефакты не загружаются; self-hosted раннер в РФ, если доступ с раннеров GitHub не работает.

## Локально

```bash
make install          # .venv из requirements/dev.txt + пакет в editable-режиме
pre-commit install    # ruff, гигиена и gitleaks перед каждым коммитом
make ci               # lint, hygiene, lock-check, contract-check, test-cov
make docker-build docker-test docker-demo docker-check
make lock             # перегенерировать lock-файлы после правки pyproject.toml
```
