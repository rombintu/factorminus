"""Командная строка `fm`. Ожидаемые ошибки печатаются одной строкой, без трейсбека."""

import argparse
import json
import sqlite3
import sys

import httpx

from . import config, db, ingest, iss, synth
from .mcp import ALLOWED, Mcp, McpError


def open_db() -> sqlite3.Connection:
    return db.connect(config.db_path())


def open_mcp(args) -> Mcp:
    return Mcp(config.token(), config.mcp_url(), verbose=args.verbose)


def cmd_synth(args) -> None:
    counts = synth.write(open_db())
    print(f"синтетика записана в {config.db_path()}: {counts}")


def cmd_stats(args) -> None:
    print("\n".join(db.stats(open_db())))


def cmd_demo(args) -> None:
    cmd_synth(args)
    cmd_stats(args)


def cmd_check(args) -> int:
    client = open_mcp(args)
    missing = sorted(ALLOWED - set(client.tools()))
    print(f"MCP {client.url}: рукопожатие ok")
    print(f"нет на сервере: {', '.join(missing)}" if missing else "все 9 инструментов на месте")
    return 1 if missing else 0


def cmd_ingest(args) -> int:
    only = set(args.only.split(",")) if args.only else None
    rows = ingest.load_universe(only=only)
    if only and len(rows) != len(only):
        unknown = only - {r["id"] for r in rows}
        raise config.ConfigError(f"нет в universe.csv: {', '.join(sorted(unknown))}")
    client, conn = open_mcp(args), open_db()
    print(f"загрузка {len(rows)} бумаг с {args.since}")
    s = ingest.run(client, conn, rows, since=args.since)
    print(f"бумаги {s['instruments']}, новые бренды {s['brands']}, новые свечи {s['candles']}, "
          f"ошибки {len(s['errors'])}, время {s['seconds']} с")  # fmt: skip
    for err in s["errors"]:
        print(f"  {err}")
    return 1 if s["errors"] and not s["instruments"] else 0


def cmd_weights(args) -> None:
    rows = iss.fetch_weights()
    if not rows:
        raise config.ConfigError("ISS вернул пустой список весов IMOEX, попробуйте позже")
    iss.save_weights(open_db(), rows)
    print(f"IMOEX: {len(rows)} бумаг на {rows[0][1]}, сумма весов {sum(r[3] for r in rows):.2f}")


def cmd_call(args) -> None:
    try:
        params = json.loads(args.json)
    except json.JSONDecodeError as e:
        raise config.ConfigError(f"аргументы не JSON: {e}") from None
    print(json.dumps(open_mcp(args).call(args.tool, params), ensure_ascii=False, indent=2))


def cmd_find(args) -> None:
    query = {"query": args.query, "responseView": ["IDENTIFIERS", "STATIC_DATA"]}
    found = open_mcp(args).call("invest_find_instrument", query).get("instruments", [])
    for i in found:
        kind = i.get("instrumentKind", "").removeprefix("INSTRUMENT_TYPE_").lower()
        print(f"{i.get('ticker')}_{i.get('classCode')}\t{kind}\t{i.get('name')}")
    if not found:
        print("ничего не найдено")


def cmd_reset(args) -> None:
    path = config.db_path()
    path.unlink(missing_ok=True)
    print(f"удалено: {path}")


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-v", "--verbose", action="store_true", help="печатать вызовы MCP")
    parser = argparse.ArgumentParser(prog="fm", description="Фактор-минус: данные этапа 1")
    sub = parser.add_subparsers(required=True, metavar="КОМАНДА")

    def add(name, func, text):
        p = sub.add_parser(name, help=text, parents=[common])
        p.set_defaults(func=func)
        return p

    add("demo", cmd_demo, "синтетика и статистика, без токена и сети")
    add("synth", cmd_synth, "записать синтетический рынок в базу")
    add("check", cmd_check, "рукопожатие с MCP и наличие 9 инструментов")
    p = add("ingest", cmd_ingest, "загрузить вселенную из MCP")
    p.add_argument("--only", help="через запятую: SBER_TQBR,TMOS_TQBR")
    p.add_argument("--since", default="2020-01-01", help="первая дата свечей")
    add("weights", cmd_weights, "веса IMOEX из ISS Мосбиржи")
    add("stats", cmd_stats, "строки по таблицам, real и synth")
    p = add("call", cmd_call, "сырой ответ инструмента MCP (только белый список)")
    p.add_argument("tool")
    p.add_argument("json", nargs="?", default="{}")
    p = add("find", cmd_find, "найти бумагу, чтобы пополнить universe.csv")
    p.add_argument("query")
    add("reset", cmd_reset, "удалить базу")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args) or 0
    except (config.ConfigError, McpError) as e:
        print(f"ошибка: {e}", file=sys.stderr)
    except httpx.HTTPError as e:
        print(f"ошибка сети: {e}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
