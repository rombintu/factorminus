# Фактор-минус

[![ci](https://github.com/rombintu/factorminus/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/rombintu/factorminus/actions/workflows/ci.yml)

Сервис показывает инвестору в момент покупки, как бумага ляжет в портфель: ловит фонды-близнецы, скрытую концентрацию и перекос в один фактор. Сделку он не блокирует и ничего не советует.

Сейчас готов этап 1: данные и фундамент. Есть read-only клиент T-Invest MCP, загрузка бумаг и свечей в SQLite, веса IMOEX, синтетический набор для тестов и контракт вердикта.

## Быстрый старт в Docker

```bash
docker compose run --rm demo              # синтетика: без токена и без сети
docker compose run --rm nightly           # реальные данные: токен из .env
docker compose run --rm fm db stats       # любая команда CLI
```

Подробно — запуск на ноутбуке или VPS, cron, обновление, бэкап: [`docs/DEPLOY.md`](docs/DEPLOY.md). Проверки и выпуск релиза: [`docs/CI.md`](docs/CI.md).

## Установка

```bash
make install                                  # .venv из requirements/dev.txt (lock-файл) + пакет
.venv/bin/pip install -r requirements/ml.txt  # laya и torch CPU, нужны с этапа 2
.venv/bin/pre-commit install                  # ruff, гигиена и gitleaks перед каждым коммитом
```

## Токен и TLS

Для сбора данных нужен **токен песочницы** T-Invest API (Sandbox token), боевой не нужен: все 9 инструментов, которые вызывает код, работают на песочнице `https://sandbox-invest-public-api.tbank.ru/mcp` (адрес по умолчанию), а токен песочницы не видит реальных счетов. Токен кладётся в `.env` в корне репозитория:

```
TINVEST_TOKEN=t.ваш_токен
```

Файл `.env` в `.gitignore`. Образец лежит в `.env.example`. Переменная окружения важнее `.env`. CLI токен не печатает.

Сертификаты `invest-public-api.tbank.ru` и `iss.moex.com` выпущены российским УЦ. Серверы присылают цепочку до промежуточного сертификата сами, поэтому в пакете лежит только корневой Russian Trusted Root CA Минцифры (`src/factorminus/certs/`, SHA-256 сверен с Госуслугами). `config.tls_context()` проверяет его отпечаток и добавляет к набору certifi; это работает и локально, и в Docker без настройки.

`TINVEST_INSECURE_SSL=1` отключает проверку сертификата. Он нужен только для локальной отладки и запрещён в тестах.

## Команды

| Команда | Что делает |
|---|---|
| `fm db init`, `fm db stats` | миграции; счётчики таблиц и диапазон свечей |
| `fm mcp check` | рукопожатие с MCP, наличие инструментов белого списка |
| `fm universe verify` | проверка `data/universe.yaml` через MCP |
| `fm ingest [--only A,B] [--since 2020-01-01] [--mode live\|record\|replay]` | загрузка карточек, брендов, свечей и ставок риска |
| `fm iss weights --index IMOEX` | веса индекса из ISS Мосбиржи |
| `fm synth generate --seed 42`, `fm synth load` | синтетический набор и его загрузка без сети |
| `fm contract export` | JSON Schema контракта в `docs/contract/` |

Проверки: `make ci` (то же, что CI, кроме Docker), `make lint`, `make test` (без сети), `make test-live` (живой MCP, нужен токен).

## Безопасность

- Клиент MCP вызывает только 9 read-only инструментов из `src/factorminus/mcp/allowlist.py`: те, что использует код. Вызов любого другого инструмента отклоняется до сетевого запроса. Новый инструмент добавляется вместе с кодом, который его вызывает, и с live-проверкой (`make test-live`).
- Токен уходит только в заголовке `Authorization` и только на `https://*.tbank.ru`. В логах, ошибках и кассетах его нет.
- Реальные ответы MCP и свечи хранятся только в локальной папке `data/`, она в `.gitignore`. В git лежат только синтетические фикстуры `tests/fixtures/synthetic/`.
