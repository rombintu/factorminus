import json

import pytest
from pydantic import ValidationError

from factorminus.config import REPO_ROOT
from factorminus.contracts import (
    Flag,
    Severity,
    Verdict,
    VerdictRequest,
    VerdictResponse,
    export_schemas,
)
from factorminus.wording import check_response_wording, find_forbidden

CONTRACT = REPO_ROOT / "docs" / "contract"
REQUEST = {
    "portfolio": {
        "positions": [{"instrument_id": "TMOS_TQTF", "value_rub": 270000}],
        "cash_rub": 30000,
    },
    "operation": "buy",
    "instrument_id": "SBMX_TQTF",
    "amount_rub": 50000,
}
RESPONSE = {
    "contract_version": "1.0",
    "verdict": "duplicate",
    "severity": "warning",
    "headline": "SBMX повторяет тот же индекс, что ваш TMOS",
    "facts": ["Корреляция дневных доходностей за 12 мес: 0,92",
              "После покупки 100% акций в портфеле — один индекс"],
    "overlaps": [{"instrument_id": "TMOS_TQTF", "kind": "same_index", "correlation": 0.92,
                  "duplicate_score": 0.98}],
    "factors_before": {"broad_market_ru": 90.0, "cash": 10.0},
    "factors_after": {"broad_market_ru": 93.3, "cash": 6.7},
    "issuers_before": {"Сбер": 13.1},
    "issuers_after": {"Сбер": 13.5},
    "correlation_to_portfolio": 0.92,
    "flags": [],
    "data_as_of": {"candles": "2026-11-21", "index_weights": "2026-11-20"},
    "trace": {"echelon": "rules", "rules_fired": ["same_index"], "laya_used": False,
              "latency_ms": 12},
}  # fmt: skip


def test_context_examples_valid():
    req = VerdictRequest.model_validate(REQUEST)
    assert req.operation.value == "buy"
    resp = VerdictResponse.model_validate(RESPONSE)
    assert resp.verdict is Verdict.duplicate
    assert resp.severity is Severity.warning


def test_enums_match_context():
    assert {v.value for v in Verdict} == {
        "duplicate",
        "increases_concentration",
        "increases_skew",
        "adds_factor",
        "reduces_skew",
        "neutral",
        "no_data",
        "unavailable",
    }
    assert {s.value for s in Severity} == {"warning", "info", "positive", "none"}
    assert {f.value for f in Flag} == {
        "preliminary",
        "portfolio_not_considered",
        "description_based",
        "index_weights_stale",
        "composition_unknown",
        "low_confidence",
    }


@pytest.mark.parametrize(
    "patch",
    [
        {"amount_rub": 0},
        {"amount_rub": -5},
        {"instrument_id": "sber"},
        {"instrument_id": "SBER"},
        {"operation": "short"},
        {"portfolio": {"positions": [{"instrument_id": "SBER_TQBR", "value_rub": -1}]}},
        {"portfolio": {"positions": [{"instrument_id": "bad id", "value_rub": 1}]}},
        {"portfolio": {"positions": [], "cash_rub": -1}},
    ],
)
def test_request_rejected(patch):
    with pytest.raises(ValidationError):
        VerdictRequest.model_validate({**REQUEST, **patch})


def test_request_accepts_synthetic_and_sell():
    r = VerdictRequest.model_validate({**REQUEST, "instrument_id": "SYN_IDXA", "operation": "sell"})
    assert r.instrument_id == "SYN_IDXA"


@pytest.mark.parametrize(
    "patch",
    [
        {"factors_after": {"broad_market_ru": 80.0, "cash": 10.0}},  # сумма 90
        {"factors_after": {"broad_market_ru": 101.0, "cash": -1.0}},  # доля вне 0..100
        {"issuers_after": {"Сбер": 120.0}},
        {"correlation_to_portfolio": 1.5},
        {
            "overlaps": [
                {"instrument_id": "TMOS_TQTF", "kind": "same_index", "duplicate_score": 1.3}
            ]
        },
        {"contract_version": "2.0"},
        {"verdict": "unavailable", "severity": "warning"},
    ],
)
def test_response_rejected(patch):
    with pytest.raises(ValidationError):
        VerdictResponse.model_validate({**RESPONSE, **patch})


def test_response_rounding_tolerance():
    ok = {**RESPONSE, "factors_after": {"a": 33.3, "b": 33.3, "c": 33.3}}  # 99.9
    VerdictResponse.model_validate(ok)


def test_unavailable_allows_empty_factors():
    VerdictResponse.model_validate(
        {
            **RESPONSE,
            "verdict": "unavailable",
            "severity": "none",
            "overlaps": [],
            "factors_before": {},
            "factors_after": {},
            "issuers_before": {},
            "issuers_after": {},
            "correlation_to_portfolio": None,
            "facts": [],
        }
    )


EXAMPLES = sorted((CONTRACT / "examples").glob("*.json"))


def test_five_examples_present():
    assert {p.stem for p in EXAMPLES} == {
        "duplicate",
        "increases_skew",
        "reduces_skew",
        "neutral",
        "unavailable",
    }


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.stem)
def test_examples_valid_and_wording_clean(path):
    resp = VerdictResponse.model_validate_json(path.read_text(encoding="utf-8"))
    assert resp.verdict.value == path.stem
    assert check_response_wording(resp) == []


@pytest.mark.parametrize(
    "text",
    [
        "Рекомендуем купить SBMX",
        "Купите фонд",
        "Продайте часть",
        "Лучше взять облигации",
        "Вам стоит подумать",
        "Советуем диверсифицировать",
        "Это наша рекомендация",
    ],
)
def test_find_forbidden_catches(text):
    assert find_forbidden(text)


@pytest.mark.parametrize(
    "text",
    [
        "Корреляция 0,92",
        "После покупки доля нефти 46%",
        "Стоимость позиции 50 000 ₽",
        "Продажа в MVP не поддерживается",
        "Покупка снижает перекос",
    ],
)
def test_find_forbidden_allows_facts(text):
    assert find_forbidden(text) == []


def test_exported_schemas_match_repo(tmp_path):
    written = export_schemas(tmp_path)
    assert {p.name for p in written} == {
        "verdict_request.schema.json",
        "verdict_response.schema.json",
    }
    for p in written:
        committed = CONTRACT / p.name
        assert committed.read_text(encoding="utf-8") == p.read_text(encoding="utf-8"), (
            "перегенерируйте: fm contract export"
        )
        schema = json.loads(p.read_text(encoding="utf-8"))
        assert schema["type"] == "object"


def test_contract_dir_has_no_real_ids():
    for p in EXAMPLES:
        assert "_TQ" not in p.read_text(encoding="utf-8"), p
