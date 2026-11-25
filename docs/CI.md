# CI/CD

Все проверки — цели `Makefile`, workflow в `.github/workflows/` только вызывают их. Локально то же, что в CI, кроме Docker и gitleaks: `make ci` (нужна сеть до PyPI и индекса PyTorch: `lock-check` перекомпилирует lock-файлы).

## Схема

| Workflow | Когда | Что делает |
|---|---|---|
| `ci.yml` | PR в `main`, push в `main`, вручную; вызывается из `release.yml` | проверки ниже |
| `ml.yml` | вручную, по понедельникам, PR с изменениями `analysis/labeler*`, `requirements/ml.txt`, `Dockerfile` | сборка `runtime-ml` и ML smoke без сети (ленивый `Router()`), размер образа и пиковая память в Summary; merge не блокирует |
| `audit.yml` | PR с изменениями `requirements/**`, `pyproject.toml`; по понедельникам; вручную | `make audit` (pip-audit по `base`, `dev`, `ml`); merge не блокирует, исключения с причиной — `.github/pip-audit-ignore.txt` |
| `release.yml` | только теги `vX.Y.Z` | проверка тега → CI → образ `runtime` в GHCR → GitHub Release |

### Задачи `ci.yml`

Все блокируют merge.

| Job | Что проверяет |
|---|---|
| `lint` | `make lint` (ruff check и format --check), `make lint-docker` (actionlint, hadolint) |
| `test` | `make test-cov`: pytest офлайн, покрытие не ниже `COV_MIN`; итог в Summary |
| `hygiene` | `make hygiene`: секреты, `.env`, SQLite; файлы данных (`csv`, `json`, `parquet`, `db` и т. п.) только в `tests/fixtures/synthetic/`, `tests/cases/`, `docs/contract/`, без реальных тикеров; ключи ответа MCP только в `.py` и `.md`. `make gitleaks` по всей истории |
| `lockfiles` | `make lock-check`: перекомпиляция lock-файлов не даёт diff, общие пакеты в `base.txt`, `dev.txt`, `ml.txt` закреплены одинаково |
| `contract` | `make contract-check`: схемы в `docs/contract/` совпадают с кодом |
| `docker` | сборка `runtime` и `test`, `make docker-test-run`, `make docker-demo` (синтетика без `.env`), `make docker-check` (вывод в Summary) |

Порог покрытия `COV_MIN` в `Makefile` — 89 (замер этапа 1.5 минус 2 п.п.), только растёт.

## Как добавить проверку

1. Цель в `Makefile` (например, `eval`), которая работает локально; если быстрая и без Docker — и в `make ci`.
2. Шаг `- run: make eval` в существующем job `ci.yml` (обычно `test`).
3. Если строка нужна в Summary прогона, шаг пишет её сам: `... >> "$GITHUB_STEP_SUMMARY"` (так этап 2 добавит метрики eval).
4. Новый job — только если нужен другой образ или раннер; если он блокирует merge, добавить его в обязательные проверки («Защита `main`»).

## Как выпустить релиз

Нумерация: `v0.1.5` — этапы 1 и 1.5 (один PR #1), `v0.2.0` — этап 2, `v0.3.0` — этап 3, `v1.0.0` — Demo Day. PR этапа вливается merge-коммитом, не squash.

1. PR влит в `main`, CI зелёный, строка этапа в `docs/STAGES.md` заполнена.
2. Пользователь ставит тег на коммит в `main`:
   ```bash
   git switch main && git pull
   git tag -a v0.1.5 -m "Этапы 1 и 1.5"
   git push origin v0.1.5
   ```
3. `release.yml`: job `guard` (`make release-guard`) проверяет формат тега и то, что коммит уже в `main`; затем CI на этом коммите (переиспользуемый `ci.yml`); затем одна сборка `runtime` для `linux/amd64` и `linux/arm64` (QEMU) с SBOM и provenance и публикация `ghcr.io/rombintu/factorminus` с тегами `0.1.5`, `0.1`, `latest`, `v0.1.5`; затем GitHub Release с текстом от GitHub (`--generate-notes`: PR и коммиты) и ссылками на `docs/STAGES.md` и `docs/DEPLOY.md`.

На push в `main` идёт только `ci.yml`, образы не публикуются. ML-образ в GHCR не публикуется: `docker compose --profile ml build fm-ml`.

## Пакет GHCR

После первой публикации пакет `factorminus` приватный. Сделать публичным (решает пользователь): GitHub → профиль `rombintu` → Packages → `factorminus` → Package settings → Change visibility → Public. Пока пакет приватный, `docker compose pull` требует `docker login ghcr.io` с токеном `read:packages`; без этого compose соберёт образ локально.

## Защита `main`

Настраивает пользователь. Нужно: merge только через PR и только merge-коммитом; обязательные проверки `lint`, `test`, `hygiene`, `lockfiles`, `contract`, `docker`; без force push и удаления ветки.

**Через веб-интерфейс:** Settings → Rules → Rulesets → New branch ruleset → имя `main`, Enforcement: Active, Target: Default branch → Restrict deletions, Block force pushes, Require a pull request before merging (Required approvals: 0; Allowed merge methods: только Merge), Require status checks to pass (Require branches to be up to date; шесть проверок выше) → Create.

**Одной командой** (только по явной просьбе пользователя):

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

## Обновление зависимостей

Lock-файлы `requirements/{base,dev,ml,build}.txt` собирает `uv pip compile` (universal, с хэшами; в `ml.txt` ещё индекс torch CPU). Dependabot обновляет только actions и базовый образ: lock-файлы он правил бы по одному, и они разошлись бы.

1. `git switch -c deps-YYYY-MM-DD` от `main`.
2. `make lock-upgrade`: все четыре файла пересобираются с `--upgrade`, затем сверка пар.
3. `make ci`, затем PR (на нём запустится `audit.yml`). Если поменялся numpy, может понадобиться `make synth`.

## Безопасность workflow

- Только `pull_request`, без `pull_request_target`: PR из форков не получают секретов и прав записи.
- Actions закреплены по SHA коммита; базовый образ (литерально в `FROM`), frontend `docker/dockerfile`, buildkit, binfmt (QEMU) и контейнеры инструментов — по digest. Frontend и digest инструментов обновляются вручную.
- Зависимости только из lock-файлов с хэшами (`--require-hashes`, в образе ещё `--only-binary=:all:`), setuptools для сборки тоже закреплён (`requirements/build.txt`).
- `permissions: contents: read` везде; `packages: write` только у job `image`, `contents: write` только у job `github-release`.
- `persist-credentials: false` у `actions/checkout`.
- Секретов, кроме `GITHUB_TOKEN`, нет; `TINVEST_TOKEN` в GitHub Secrets не добавляется.

## Почему live-тестов нет в CI

Репозиторий публичный, логи видны всем, а ответы MCP и реальные цены нельзя публиковать (условия T-Invest). Раннеры GitHub за рубежом, доступ к API оттуда не гарантирован. Live-проверка локальная: `make test-live` с `.env`.

## Локально

```bash
make install          # .venv из requirements/dev.txt + пакет в editable-режиме
pre-commit install    # ruff, гигиена и gitleaks перед каждым коммитом
make ci               # lint, hygiene, lock-check, contract-check, test-cov
make docker-build docker-test docker-demo docker-check
make docker-test-ml   # ML smoke в образе test-ml, пиковая память
make lock             # перегенерировать lock-файлы после правки pyproject.toml
make lock-upgrade     # поднять все закреплённые версии
```
