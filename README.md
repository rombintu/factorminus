# Фактор-минус

Сервис показывает инвестору в момент покупки, как бумага ляжет в портфель: ловит фонды-близнецы, скрытую концентрацию и перекос в один фактор. Сделку он не блокирует и ничего не советует. Подробности: `docs/CONTEXT.md`.

Сейчас готов этап 1: данные и фундамент. Есть read-only клиент T-Invest MCP, загрузка бумаг и свечей в SQLite, веса IMOEX, синтетический набор для тестов и контракт вердикта.

## Установка

```bash
python3.12 -m venv .venv && .venv/bin/pip install -e '.[dev]'   # или: make install
.venv/bin/pip install -e '.[ml]'                                # laya, нужна с этапа 2
```

## Токен и TLS

Токен T-Invest (нужен только для чтения) кладётся в `.env` в корне репозитория:

```
TINVEST_TOKEN=t.ваш_токен
```

Файл `.env` в `.gitignore`. Образец лежит в `.env.example`. Переменная окружения важнее `.env`. CLI токен не печатает.

Сертификаты `invest-public-api.tbank.ru` и `iss.moex.com` выпущены российским УЦ (Russian Trusted Root CA). Если появляется ошибка `CERTIFICATE_VERIFY_FAILED`, соберите бандл из сертификатов certifi и Минцифры и укажите путь к нему:

```bash
mkdir -p data/ca
cat "$(.venv/bin/python -c 'import certifi; print(certifi.where())')" \
    russian_trusted_root_ca.pem russian_trusted_sub_ca.pem > data/ca/ru-bundle.pem
echo 'TINVEST_CA_BUNDLE=data/ca/ru-bundle.pem' >> .env
```

Сертификаты Минцифры можно скачать на Госуслугах. `TINVEST_INSECURE_SSL=1` отключает проверку сертификата. Он нужен только для локальной отладки и запрещён в тестах.

## Команды

| Команда | Что делает |
|---|---|
| `fm db init`, `fm db stats` | миграции; счётчики таблиц и диапазон свечей |
| `fm mcp check` | рукопожатие с MCP, наличие инструментов белого списка |
| `fm universe verify` | проверка `data/universe.yaml` через MCP |
| `fm ingest [--only A,B] [--since 2024-01-01] [--mode live\|record\|replay]` | загрузка карточек, брендов, свечей и ставок риска |
| `fm iss weights --index IMOEX` | веса индекса из ISS Мосбиржи |
| `fm synth generate --seed 42`, `fm synth load` | синтетический набор и его загрузка без сети |
| `fm contract export` | JSON Schema контракта в `docs/contract/` |

Проверки: `make lint`, `make test` (без сети), `make test-live` (живой MCP, нужен токен).

## Безопасность

- Клиент MCP вызывает только 16 read-only инструментов из `src/factorminus/mcp/allowlist.py`. Вызов любого другого инструмента отклоняется до сетевого запроса.
- Токен уходит только в заголовке `Authorization` и только на `https://*.tbank.ru`. В логах, ошибках и кассетах его нет.
- Реальные ответы MCP и свечи хранятся только в локальной папке `data/`, она в `.gitignore`. В git лежат только синтетические фикстуры `tests/fixtures/synthetic/`.
