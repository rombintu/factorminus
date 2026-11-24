"""Вселенная бумаг: `data/universe.yaml`, проверка через MCP."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ValidationError, field_validator, model_validator

from factorminus.ingest.parse import parse_instrument
from factorminus.mcp.errors import McpError

Kind = Literal["share", "etf", "bond", "currency"]
Role = Literal[
    "index_fund", "bond_fund", "money_fund", "gold_fund", "active_fund", "share", "ofz", "corp_bond"
]
ID_RE = re.compile(r"^([A-Z0-9]+_[A-Z0-9]+|SYN_[A-Z0-9_]+)$")

GET_TOOL: dict[str, str] = {
    "share": "invest_get_share",
    "etf": "invest_get_etf",
    "bond": "invest_get_bond",
    "currency": "invest_get_currency",
}


class UniverseEntry(BaseModel):
    id: str
    kind: Kind
    role: Role
    index: str | None = None
    note: str = ""

    @field_validator("id")
    @classmethod
    def _id_format(cls, v: str) -> str:
        if not ID_RE.match(v):
            raise ValueError(f"id {v!r} не в формате TICKER_CLASSCODE или SYN_*")
        return v

    @model_validator(mode="after")
    def _index_only_for_index_funds(self) -> UniverseEntry:
        if (self.role == "index_fund") != (self.index is not None):
            raise ValueError("поле index задаётся ровно для role=index_fund")
        return self

    @property
    def ticker(self) -> str:
        return self.id if self.id.startswith("SYN_") else self.id.rsplit("_", 1)[0]


def load_universe(path: Path | str) -> list[UniverseEntry]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("universe.yaml должен быть списком записей")
    entries: list[UniverseEntry] = []
    seen: set[str] = set()
    for i, raw in enumerate(data):
        try:
            e = UniverseEntry.model_validate(raw)
        except ValidationError as ex:
            raise ValueError(f"Запись {i}: {ex}") from ex
        if e.id in seen:
            raise ValueError(f"Запись {i}: дубликат id {e.id}")
        seen.add(e.id)
        entries.append(e)
    return entries


def instrument_args(entry: UniverseEntry) -> dict:
    return {
        "instrumentId": entry.id,
        "idType": "INSTRUMENT_ID_TYPE_ID",
        "responseView": ["FULL"],
    }


def verify_universe(client: Any, entries: list[UniverseEntry]) -> dict:
    """Проверяет каждую бумагу через `get_*`. Ненайденные не валят проверку."""
    report: dict[str, Any] = {"found": [], "not_found": [], "no_api_flag": [], "details": {}}
    for e in entries:
        try:
            row = parse_instrument(client.call_tool(GET_TOOL[e.kind], instrument_args(e)), e.kind)
        except (McpError, ValueError) as ex:
            report["not_found"].append(e.id)
            report["details"][e.id] = {"status": "not_found", "error": str(ex)}
            continue
        report["found"].append(e.id)
        if row["api_trade_flag"] == 0:
            report["no_api_flag"].append(e.id)
        report["details"][e.id] = {
            "status": "found",
            "ticker": row["ticker"],
            "class_code": row["class_code"],
            "name": row["name"],
            "isin": row["isin"],
            "api_trade_flag": row["api_trade_flag"],
            "maturity_date": row["maturity_date"],
        }
    return report
