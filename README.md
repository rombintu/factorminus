# Фактор-минус

Сервис показывает инвестору в момент покупки, как бумага ляжет в портфель: фонды-близнецы, скрытая концентрация, перекос в один фактор. Только факты, без советов и без заявок. Контекст продукта: `docs/CONTEXT.md`, ТЗ этапа: `docs/tz/`.

Этап 1 — данные: загрузка бумаг из T-Invest MCP в SQLite, веса IMOEX, синтетический рынок для тестов и демо, контракт вердикта.

## Запуск за 5 команд

```bash
git clone https://github.com/rombintu/factorminus && cd factorminus
uv sync                      # Python 3.12, зависимости из uv.lock
uv run fm demo               # синтетика + статистика, без токена и сети
cp .env.example .env         # вписать TINVEST_TOKEN (токен песочницы)
uv run fm check && uv run fm ingest && uv run fm weights
```

Docker: `docker compose run --rm app` (демо) или `docker compose run --rm app fm ingest`. База `data/fm.sqlite` смонтирована и видна на диске.

## Команды `fm`

| Команда | Что делает |
|---|---|
| `fm demo` | `synth` + `stats`, без токена и сети |
| `fm synth` | синтетический рынок в базу (id `SYN_*`, `source='synth'`) |
| `fm check` | рукопожатие с MCP, все 9 инструментов есть на сервере |
| `fm ingest [--only ID,ID] [--since 2020-01-01]` | загрузка бумаг из `src/factorminus/universe.csv` |
| `fm weights` | веса IMOEX из ISS Мосбиржи (без токена) |
| `fm stats` | строки по таблицам, диапазоны дат, отдельно real и synth |
| `fm call TOOL JSON` | сырой ответ инструмента MCP |
| `fm find QUERY` | поиск бумаги, чтобы пополнить `universe.csv` |
| `fm reset` | удалить базу (схема изменилась — `reset` и загрузка заново) |

## Отладка

- `fm call -v invest_get_share '{"instrumentId": "SBER_TQBR", "idType": "INSTRUMENT_ID_TYPE_ID"}'` — сырой JSON ответа.
- `-v` у любой команды печатает в stderr каждый вызов MCP: инструмент, аргументы, время.
- В таблицах `instruments` и `brands` лежит `raw_json` исходного ответа: `sqlite3 data/fm.sqlite "select raw_json from instruments where id='TMOS_TQBR'"`.
- Ожидаемые ошибки (нет токена, бумага не найдена, сеть) печатаются одной строкой.

## Безопасность

- MCP-клиент вызывает только 9 read-only инструментов (`mcp.ALLOWED`), остальные отклоняются до запроса.
- Токен читается из окружения или `.env`, уходит только по `https://*.tbank.ru`, в логи не пишется.
- TLS: certifi + корневой сертификат НУЦ Минцифры из пакета, отпечаток сверяется при запуске.
- Реальные цены и ответы MCP живут только в `data/` (в `.gitignore`).

## Разработка

`make lint`, `make test` (без сети, меньше секунды), `uv run pytest -m live` (песочница, нужен токен), `make docker`.
