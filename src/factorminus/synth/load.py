"""Загрузка синтетического набора в SQLite обычным конвейером в режиме replay."""

from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path

from factorminus.config import Settings
from factorminus.db import connect, migrate
from factorminus.ingest.pipeline import IngestSummary, run_ingest
from factorminus.ingest.universe import load_universe
from factorminus.iss import store_index_weights
from factorminus.mcp.client import McpClient


def load_synth(db_path: Path | str, fixtures: Path | str) -> IngestSummary:
    fixtures = Path(fixtures)
    manifest = json.loads((fixtures / "manifest.json").read_text(encoding="utf-8"))
    params = manifest["params"]
    conn = connect(db_path)
    migrate(conn)
    entries = load_universe(fixtures / "universe.yaml")
    # replay не требует токена и не ходит в сеть
    client = McpClient(Settings(token=None), mode="replay", cassette_dir=fixtures / "cassettes")
    summary = run_ingest(
        conn,
        client,
        entries,
        since=date.fromisoformat(params["start"]),
        until=date.fromisoformat(params["end"]),
        mode="replay",
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
