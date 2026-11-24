"""CLI `fm`. Токен никогда не печатается: только «задан / не задан»."""

from __future__ import annotations

import functools
import json
import logging
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

import typer

from factorminus.config import REPO_ROOT, ConfigError, Settings, load_settings
from factorminus.mcp.errors import McpError

app = typer.Typer(
    no_args_is_help=True, add_completion=False, help="Фактор-минус: данные и проверки"
)
db_app = typer.Typer(no_args_is_help=True, help="База данных")
mcp_app = typer.Typer(no_args_is_help=True, help="T-Invest MCP")
universe_app = typer.Typer(no_args_is_help=True, help="Вселенная бумаг")
iss_app = typer.Typer(no_args_is_help=True, help="ISS Мосбиржи")
synth_app = typer.Typer(no_args_is_help=True, help="Синтетический набор")
contract_app = typer.Typer(no_args_is_help=True, help="Контракт вердикта")
for name, sub in [
    ("db", db_app),
    ("mcp", mcp_app),
    ("universe", universe_app),
    ("iss", iss_app),
    ("synth", synth_app),
    ("contract", contract_app),
]:
    app.add_typer(sub, name=name)

ModeOpt = Annotated[str, typer.Option("--mode", help="live | record | replay")]
DbOpt = Annotated[Path | None, typer.Option("--db", help="Путь к SQLite (по умолчанию FM_DB_PATH)")]
UNIVERSE_PATH = REPO_ROOT / "data" / "universe.yaml"


@app.callback()
def main(verbose: Annotated[bool, typer.Option("-v", "--verbose")] = False) -> None:
    """Фактор-минус."""
    logging.basicConfig(
        level=logging.INFO if verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # httpx на INFO пишет URL запросов; заголовки он не логирует, но держим его тише.
    logging.getLogger("httpx").setLevel(logging.WARNING)


def friendly_errors(fn: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (ConfigError, McpError, FileNotFoundError, ValueError) as e:
            typer.echo(f"Ошибка: {e}", err=True)
            raise typer.Exit(2) from None

    return wrapper


def _settings() -> Settings:
    return load_settings()


def _db(settings: Settings, db: Path | None):
    from factorminus.db import connect, migrate

    conn = connect(db or settings.db_path)
    migrate(conn)
    return conn


def _client(settings: Settings, mode: str = "live", cassette_dir: Path | None = None):
    from factorminus.mcp.client import DEFAULT_CASSETTE_DIR, McpClient

    return McpClient(settings, mode=mode, cassette_dir=cassette_dir or DEFAULT_CASSETTE_DIR)


# --- db ---


@db_app.command("init")
@friendly_errors
def db_init(db: DbOpt = None) -> None:
    """Применить миграции."""
    from factorminus.db import connect, migrate

    s = _settings()
    path = db or s.db_path
    applied = migrate(connect(path))
    typer.echo(f"БД {path}: применены миграции {applied or 'нет новых'}")


@db_app.command("stats")
@friendly_errors
def db_stats(db: DbOpt = None) -> None:
    """Счётчики по таблицам и диапазон дат свечей."""
    from factorminus.db import candle_ranges, table_counts

    s = _settings()
    conn = _db(s, db)
    typer.echo(f"БД: {db or s.db_path}")
    for table, n in table_counts(conn).items():
        typer.echo(f"  {table:18s} {n:>8}")
    r = candle_ranges(conn)
    typer.echo(f"Свечи: {r['instruments']} инструментов, даты {r['min_date']} … {r['max_date']}")
    row = conn.execute(
        "SELECT COUNT(*) FROM instruments i JOIN brands b ON b.brand_uid = i.brand_uid "
        "WHERE b.sector IS NOT NULL"
    ).fetchone()
    typer.echo(f"Инструментов с брендом и сектором: {row[0]}")
    for idx, d, n in conn.execute(
        "SELECT index_id, MAX(trade_date), COUNT(*) FROM index_weights "
        "WHERE trade_date = (SELECT MAX(trade_date) FROM index_weights w2 "
        "WHERE w2.index_id = index_weights.index_id) GROUP BY index_id"
    ):
        typer.echo(f"Веса {idx}: {n} бумаг на {d}")


# --- mcp ---


@mcp_app.command("check")
@friendly_errors
def mcp_check() -> None:
    """Рукопожатие, число инструментов, наличие инструментов белого списка."""
    from factorminus.mcp.allowlist import READ_ONLY_TOOLS

    s = _settings()
    typer.echo(f"MCP: {s.mcp_url}")
    typer.echo(f"Токен: {s.token_status}")
    typer.echo(f"TLS: {'CA-бандл ' + s.ca_bundle if s.ca_bundle else 'системные сертификаты'}")
    with _client(s) as client:
        tools = client.list_tools()
    typer.echo(f"Рукопожатие: ок, инструментов на сервере: {len(tools)}")
    missing = sorted(READ_ONLY_TOOLS - set(tools))
    present = len(READ_ONLY_TOOLS) - len(missing)
    typer.echo(f"Белый список: {present}/{len(READ_ONLY_TOOLS)} есть на сервере")
    if missing:
        typer.echo(f"Нет на сервере: {', '.join(missing)}")
        raise typer.Exit(1)


@mcp_app.command("find")
@friendly_errors
def mcp_find(
    query: str,
    kind: Annotated[str, typer.Option(help="share|etf|bond|currency|any")] = "any",
) -> None:
    """Поиск бумаги (`invest_find_instrument`): помогает собрать universe.yaml."""
    kinds = {
        "share": "INSTRUMENT_TYPE_SHARE",
        "etf": "INSTRUMENT_TYPE_ETF",
        "bond": "INSTRUMENT_TYPE_BOND",
        "currency": "INSTRUMENT_TYPE_CURRENCY",
    }
    args: dict[str, Any] = {"query": query, "responseView": ["IDENTIFIERS", "TRADING_FLAGS"]}
    if kind in kinds:
        args["instrumentKind"] = kinds[kind]
    with _client(_settings()) as client:
        res = client.call_tool("invest_find_instrument", args)
    items = res.get("instruments", []) if isinstance(res, dict) else res
    for it in items or []:
        typer.echo(
            f"{it.get('ticker', '?')}_{it.get('classCode', '?')}\t{it.get('instrumentType', '')}\t"
            f"api={it.get('apiTradeAvailableFlag')}\t{it.get('name', '')}"
        )


# --- universe ---


@universe_app.command("verify")
@friendly_errors
def universe_verify(
    path: Annotated[Path, typer.Option("--universe")] = UNIVERSE_PATH,
    mode: ModeOpt = "live",
) -> None:
    """Проверить каждую бумагу вселенной через `get_*`."""
    from factorminus.ingest.universe import load_universe, verify_universe

    entries = load_universe(path)
    with _client(_settings(), mode=mode) as client:
        report = verify_universe(client, entries)
    out = REPO_ROOT / "data" / "universe_resolved.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    typer.echo(
        f"Всего {len(entries)}: найдено {len(report['found'])}, "
        f"не найдено {len(report['not_found'])}, "
        f"без apiTradeAvailableFlag {len(report['no_api_flag'])}"
    )
    for i in report["not_found"]:
        typer.echo(f"  не найдена: {i}: {report['details'][i]['error']}")
    for i in report["no_api_flag"]:
        typer.echo(f"  без API-торговли (пометка): {i}")
    typer.echo(f"Подробности: {out}")


# --- iss ---


@iss_app.command("weights")
@friendly_errors
def iss_weights(index: Annotated[str, typer.Option("--index")] = "IMOEX", db: DbOpt = None) -> None:
    """Веса индекса из ISS Мосбиржи в `index_weights`."""
    from factorminus.iss import fetch_index_weights, store_index_weights

    s = _settings()
    rows = fetch_index_weights(index, verify=s.ssl_verify())
    if not rows:
        typer.echo(f"ISS не вернул весов для {index}", err=True)
        raise typer.Exit(1)
    n = store_index_weights(_db(s, db), index, rows)
    total = sum(r["weight"] for r in rows)
    typer.echo(f"{index}: {n} бумаг на {rows[0]['trade_date']}, сумма весов {total:.2f}")


def run() -> None:  # pragma: no cover
    try:
        app()
    except KeyboardInterrupt:
        sys.exit(130)
