"""Загрузка синтетического набора в SQLite обычным конвейером в режиме replay.

Кассеты в git не хранятся: если в каталоге набора нет `cassettes/`, они строятся
во временном каталоге из того же seed (генератор детерминирован, а то, что CSV в git
совпадает с генератором, проверяет тест `test_committed_fixtures_match_generator`).
"""

from __future__ import annotations

import csv
import json
import tempfile
from datetime import date
from pathlib import Path

from factorminus.config import Settings
from factorminus.db import connect, migrate
from factorminus.ingest.index_candles import ingest_index_candles
from factorminus.ingest.pipeline import IngestSummary, run_ingest
from factorminus.ingest.universe import load_universe
from factorminus.iss import store_index_weights
from factorminus.mcp.client import McpClient


def _load(db_path: Path, fixtures: Path, cassettes: Path, manifest: dict) -> IngestSummary:
    from factorminus.synth.generator import INDEX_ID, INDEX_MCP_ID

    params = manifest["params"]
    since = date.fromisoformat(params["start"])
    until = date.fromisoformat(params["end"])
    conn = connect(db_path)
    migrate(conn)
    entries = load_universe(fixtures / "universe.yaml")
    # replay не требует токена и не ходит в сеть
    client = McpClient(Settings(token=None), mode="replay", cassette_dir=cassettes)
    summary = run_ingest(
        conn, client, entries, since=since, until=until, mode="replay", source="synthetic"
    )
    summary.candles += ingest_index_candles(
        conn,
        client,
        INDEX_ID,
        since=since,
        until=until,
        sources={INDEX_ID: INDEX_MCP_ID},
        source="synthetic",
    )
    with open(fixtures / "index_weights.csv", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    by_index: dict[str, list[dict]] = {}
    for r in rows:
        by_index.setdefault(r["index_id"], []).append(
            {
                "trade_date": r["trade_date"],
                "ticker": r["ticker"],
                "secids": r["secids"],
                "shortname": r["shortname"],
                "weight": float(r["weight"]),
            }
        )
    for index_id, idx_rows in by_index.items():
        store_index_weights(conn, index_id, idx_rows)
    conn.close()
    return summary


def load_synth(
    db_path: Path | str, fixtures: Path | str, cassettes: Path | str | None = None
) -> IngestSummary:
    fixtures = Path(fixtures)
    manifest = json.loads((fixtures / "manifest.json").read_text(encoding="utf-8"))
    if cassettes is None and (fixtures / "cassettes").is_dir():
        cassettes = fixtures / "cassettes"
    if cassettes is not None:
        return _load(Path(db_path), fixtures, Path(cassettes), manifest)
    from factorminus.synth.generator import generate, write_cassettes

    with tempfile.TemporaryDirectory(prefix="fm-synth-cassettes-") as tmp:
        write_cassettes(generate(manifest["seed"]), Path(tmp) / "cassettes")
        return _load(Path(db_path), fixtures, Path(tmp) / "cassettes", manifest)


def expected_errors(fixtures: Path | str) -> set[tuple[str, str]]:
    """Ошибки загрузки, заложенные в набор как особенности данных (фонд без бренда)."""
    manifest = json.loads((Path(fixtures) / "manifest.json").read_text(encoding="utf-8"))
    return {(e["instrument_id"], e["step"]) for e in manifest.get("expected_ingest_errors", [])}
