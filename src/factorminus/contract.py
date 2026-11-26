"""Контракт вердикта v1.0 (раздел 7 docs/CONTEXT.md): запрос POST /api/v1/verdict и ответ."""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

CONTRACT_VERSION = "1.0"
# TICKER_CLASSCODE (SBER_TQBR, RU000A101012_TQCB) или синтетика SYN_*
InstrumentId = Annotated[str, Field(pattern=r"^[A-Z0-9][A-Z0-9.@-]*(_[A-Z0-9.@-]+)+$")]
Percent = Annotated[float, Field(ge=0, le=100)]
Correlation = Annotated[float, Field(ge=-1, le=1)]


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


class Operation(StrEnum):
    buy = "buy"
    sell = "sell"


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Position(Strict):
    instrument_id: InstrumentId
    value_rub: float = Field(ge=0)


class Portfolio(Strict):
    positions: list[Position] = []
    cash_rub: float = Field(0, ge=0)


class VerdictRequest(Strict):
    portfolio: Portfolio
    operation: Operation
    instrument_id: InstrumentId
    amount_rub: float = Field(gt=0)


class Overlap(Strict):
    instrument_id: InstrumentId
    kind: str
    correlation: Correlation | None = None
    duplicate_score: float | None = Field(None, ge=0, le=1)


class Trace(Strict):
    echelon: str
    rules_fired: list[str] = []
    laya_used: bool = False
    latency_ms: float = Field(ge=0)


class VerdictResponse(Strict):
    contract_version: Literal["1.0"] = CONTRACT_VERSION
    verdict: Verdict
    severity: Severity
    headline: str
    facts: list[str] = []
    overlaps: list[Overlap] = []
    factors_before: dict[str, Percent] = {}
    factors_after: dict[str, Percent] = {}
    issuers_before: dict[str, Percent] = {}
    issuers_after: dict[str, Percent] = {}
    correlation_to_portfolio: Correlation | None = None
    flags: list[Flag] = []
    data_as_of: dict[str, str | None] = {}
    trace: Trace

    @model_validator(mode="after")
    def factors_sum_to_100(self):
        for name in ("factors_before", "factors_after"):
            shares = getattr(self, name)
            if shares and abs(sum(shares.values()) - 100) > 0.5:
                raise ValueError(f"{name}: сумма долей {sum(shares.values()):.1f}, ожидается 100")
        return self
