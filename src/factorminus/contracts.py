"""Контракт вердикта v1.0 (docs/CONTEXT.md, раздел 7). Меняется только с версией."""

from __future__ import annotations

import json
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CONTRACT_VERSION = "1.0"
INSTRUMENT_ID_RE = r"^([A-Z0-9]+_[A-Z0-9]+|SYN_[A-Z0-9_]+)$"
SHARE_TOLERANCE = 0.05  # допуск округления для одной доли, п.п.
SUM_TOLERANCE = 0.5  # допуск для суммы долей факторов, п.п.

InstrumentId = Annotated[str, Field(pattern=INSTRUMENT_ID_RE, examples=["TMOS_TQBR", "SYN_IDXA"])]


class Operation(StrEnum):
    buy = "buy"
    sell = "sell"  # в MVP отвечает no_data, кроме одного заготовленного примера


class Verdict(StrEnum):
    duplicate = "duplicate"
    increases_concentration = "increases_concentration"
    increases_skew = "increases_skew"
    adds_factor = "adds_factor"
    reduces_skew = "reduces_skew"
    neutral = "neutral"
    no_data = "no_data"
    unavailable = "unavailable"


class Severity(StrEnum):
    warning = "warning"
    info = "info"
    positive = "positive"
    none = "none"


class Flag(StrEnum):
    preliminary = "preliminary"
    portfolio_not_considered = "portfolio_not_considered"
    description_based = "description_based"
    index_weights_stale = "index_weights_stale"
    composition_unknown = "composition_unknown"
    low_confidence = "low_confidence"


class OverlapKind(StrEnum):
    same_index = "same_index"
    same_issuer = "same_issuer"
    lookthrough = "lookthrough"  # бумага есть внутри индексного фонда портфеля
    high_correlation = "high_correlation"
    similar_description = "similar_description"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Position(_Model):
    instrument_id: InstrumentId
    value_rub: float = Field(ge=0)


class Portfolio(_Model):
    positions: list[Position] = Field(default_factory=list)
    cash_rub: float = Field(default=0.0, ge=0)


class VerdictRequest(_Model):
    portfolio: Portfolio
    operation: Operation
    instrument_id: InstrumentId
    amount_rub: float = Field(gt=0)


class Overlap(_Model):
    instrument_id: InstrumentId
    kind: OverlapKind
    correlation: float | None = Field(default=None, ge=-1, le=1)
    duplicate_score: float | None = Field(default=None, ge=0, le=1)


class DataAsOf(_Model):
    candles: date | None = None
    index_weights: date | None = None


class Trace(_Model):
    echelon: Literal["rules", "laya", "none"]
    rules_fired: list[str] = Field(default_factory=list)
    laya_used: bool = False
    latency_ms: float = Field(ge=0)


Shares = dict[str, float]


def _check_shares(name: str, shares: Shares, *, sum_100: bool) -> Shares:
    for key, v in shares.items():
        if not (-SHARE_TOLERANCE <= v <= 100 + SHARE_TOLERANCE):
            raise ValueError(f"{name}[{key}] = {v}: доля в процентах должна быть 0–100")
    total = sum(shares.values())
    if sum_100 and shares and abs(total - 100) > SUM_TOLERANCE:
        raise ValueError(f"{name}: сумма долей {total:.2f}, ожидается 100 ± {SUM_TOLERANCE}")
    if not sum_100 and total > 100 + SUM_TOLERANCE:
        raise ValueError(f"{name}: сумма долей {total:.2f} больше 100")
    return shares


class VerdictResponse(_Model):
    contract_version: Literal["1.0"] = CONTRACT_VERSION
    verdict: Verdict
    severity: Severity
    headline: str
    facts: list[str] = Field(default_factory=list)
    overlaps: list[Overlap] = Field(default_factory=list)
    factors_before: Shares = Field(default_factory=dict, description="Доли факторов, %")
    factors_after: Shares = Field(default_factory=dict, description="Доли факторов, %")
    issuers_before: Shares = Field(default_factory=dict, description="Сквозные доли эмитентов, %")
    issuers_after: Shares = Field(default_factory=dict, description="Сквозные доли эмитентов, %")
    correlation_to_portfolio: float | None = Field(default=None, ge=-1, le=1)
    flags: list[Flag] = Field(default_factory=list)
    data_as_of: DataAsOf = Field(default_factory=DataAsOf)
    trace: Trace

    @field_validator("factors_before", "factors_after")
    @classmethod
    def _factors(cls, v: Shares, info) -> Shares:
        return _check_shares(info.field_name, v, sum_100=True)

    @field_validator("issuers_before", "issuers_after")
    @classmethod
    def _issuers(cls, v: Shares, info) -> Shares:
        return _check_shares(info.field_name, v, sum_100=False)

    @model_validator(mode="after")
    def _silent_verdicts(self) -> VerdictResponse:
        if (
            self.verdict in (Verdict.no_data, Verdict.unavailable)
            and self.severity is not Severity.none
        ):
            raise ValueError(f"verdict={self.verdict.value} допускает только severity=none")
        return self


SCHEMAS = {
    "verdict_request.schema.json": VerdictRequest,
    "verdict_response.schema.json": VerdictResponse,
}


def export_schemas(out: Path | str) -> list[Path]:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for name, model in SCHEMAS.items():
        schema = model.model_json_schema()
        schema["$id"] = f"factorminus/{name}"
        schema["description"] = f"Фактор-минус, контракт вердикта v{CONTRACT_VERSION}"
        path = out / name
        path.write_text(
            json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        written.append(path)
    return written
