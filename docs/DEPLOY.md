# Запуск на любой машине (ноутбук, VPS)

Нужен только Docker: Python и зависимости внутри образа. Образы multi-arch (`linux/amd64`, `linux/arm64`): на Mac с Apple Silicon и на ARM-серверах эмуляция не нужна.

## 1. Docker

- **Linux (VPS):** Docker Engine и плагин compose из официального репозитория Docker для вашего дистрибутива (docs.docker.com/engine/install). Проверка: `docker compose version`.
- **macOS, Windows:** Docker Desktop. Для образа `runtime-ml` хватает 4 ГБ памяти Docker (Settings → Resources): laya грузит модели лениво (`Router()`), и на русском тексте в память попадает только multilingual; пиковая память контейнера в ML smoke — 1,9–2,6 ГБ в четырёх прогонах (вместе со страничным кэшем файлов весов). 8 ГБ нужны, только если держать в памяти все три модели сразу (`Router(preload=True)`; на 4 ГБ процесс убивается по OOM на 3,5 ГБ).

## 2. Код и настройки

```bash
git clone https://github.com/rombintu/factorminus.git && cd factorminus
cp .env.example .env      # затем впишите TINVEST_TOKEN (токен «только чтение»)
chmod 600 .env
```

`.env` нужен только для реальных данных (`nightly`, `fm`). Демо работает без него. В образ `.env` не попадает: compose передаёт переменные только при запуске (`env_file`). Пути (`FM_HOME`, `FM_DATA_DIR`, `FM_DB_PATH`, `TINVEST_CA_BUNDLE`) и `TINVEST_INSECURE_SSL=0` в контейнере задаёт `compose.yaml`, значения из `.env` их не переопределяют.

## 3. Демо на синтетике

```bash
docker compose pull            # готовый образ из GHCR (пока пакет приватный — см. docs/CI.md)
docker compose run --rm demo
```

Или собрать локально: `docker compose build && docker compose run --rm demo` (`make docker-build docker-demo` делает то же для образа `factorminus:local`). Первая локальная сборка занимает несколько минут: скачиваются базовый образ и зависимости.

Если пакета в GHCR нет или он приватный, `docker compose run` сам собирает образ локально и помечает его как `ghcr.io/rombintu/factorminus:main` (или `:$FM_TAG`). После `git pull` этот образ остаётся старым, пока не выполнить `docker compose build` (или `docker compose pull`, когда пакет станет публичным).

Демо загружает синтетический набор в том `fm-data` и печатает `fm db stats`. Контейнер демо запускается без сети (`network_mode: none`) и без `.env`.

## 4. Реальные данные

```bash
docker compose run --rm nightly          # карточки, бренды, свечи с 2020-01-01, свечи и веса IMOEX
docker compose run --rm fm db stats      # что загружено
docker compose run --rm fm mcp check     # рукопожатие с MCP
```

Первая загрузка — около 4 минут (лимит MCP соблюдается равномерным интервалом), следующие — только новые дни. Данные лежат в именованном томе `fm-data` (`/var/lib/factorminus` в контейнере), а конфигурация (`data/universe.yaml`) — в образе. Новый образ с обновлённой вселенной подхватывается сразу, том её не закрывает.

Любая команда CLI: `docker compose run --rm fm <команда>`, например `docker compose run --rm fm ingest --only SBER_TQBR`.

## 5. Расписание (cron хоста)

```cron
# каждый будний день в 19:30 МСК после закрытия основной сессии
30 19 * * 1-5  cd /opt/factorminus && docker compose run --rm nightly >> /var/log/factorminus-nightly.log 2>&1
```

Время в cron — локальное время сервера; на VPS в UTC это `30 16 * * 1-5`. На этапе 2 сервис `nightly` начнёт вызывать `fm nightly`, строка cron не меняется.

## 6. Обновление на новый релиз

```bash
cd /opt/factorminus && git pull                 # compose.yaml и .env.example могли измениться
FM_TAG=v0.2.0 docker compose pull
FM_TAG=v0.2.0 docker compose run --rm demo
```

Если образ собирался локально (пакет в GHCR приватный или его нет), `pull` его не обновит: после `git pull` выполните `docker compose build`.

Чтобы не писать `FM_TAG` каждый раз, добавьте строку `FM_TAG=v0.2.0` в файл `.env`: compose читает его для подстановки переменных. Теги образов: `vX.Y.Z` и `X.Y.Z`, `X.Y`, `latest`, `main` (последний коммит в `main`); ML-образ — `vX.Y.Z-ml` (`docker compose --profile ml pull fm-ml`).

## 7. Бэкап тома `fm-data`

```bash
# бэкап (SQLite и кассеты) в текущую папку
docker run --rm -v factorminus_fm-data:/data:ro -v "$PWD":/backup busybox \
  tar czf /backup/fm-data-$(date +%F).tar.gz -C /data .

# восстановление в пустой том
docker run --rm -v factorminus_fm-data:/data -v "$PWD":/backup busybox \
  tar xzf /backup/fm-data-2026-11-24.tar.gz -C /data
```

Не запускайте бэкап во время `nightly`: SQLite может быть в середине записи. Архив содержит реальные данные MCP: не публикуйте его и не кладите в git.

## 8. Если MCP не отвечает

| Симптом | Причина и что делать |
|---|---|
| `Ошибка: Токен не найден: задайте TINVEST_TOKEN…` | нет `.env` или в нём пустой `TINVEST_TOKEN`; `.env` должен лежать рядом с `compose.yaml` |
| `HTTP 401` / `403` | токен отозван или не тот: выпустите новый токен «только чтение» в настройках T-Invest |
| `CERTIFICATE_VERIFY_FAILED` | в образе бандл certifi + Russian Trusted Root/Sub CA (`/opt/factorminus/ca/ru-bundle.pem`). Если сертификат сервера сменился, обновите `certs/` (отпечаток сверяется с Госуслугами), пересоберите образ. `TINVEST_INSECURE_SSL=1` — только для локальной отладки |
| `ConnectError`, таймауты | нет сети до `invest-public-api.tbank.ru` (файрвол VPS, зарубежный хостинг): проверьте `curl -sI https://invest-public-api.tbank.ru` с хоста |
| `HTTP 429` | превышен лимит 200 запросов в минуту: не запускайте два `nightly` одновременно |

Без MCP сервис не ломается: демо и уже загруженные данные работают.
