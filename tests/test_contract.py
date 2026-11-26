import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from factorminus import wording
from factorminus.contract import VerdictRequest, VerdictResponse

EXAMPLES = sorted((Path(__file__).parents[1] / "docs/contract/examples").glob("*.json"))
REQUEST = {
    "portfolio": {"positions": [{"instrument_id": "TMOS_TQBR", "value_rub": 270000}], "cash_rub": 30000},
    "operation": "buy",
    "instrument_id": "SBMX_TQBR",
    "amount_rub": 50000,
}  # fmt: skip


def test_five_examples_valid_and_factual():
    names = {p.stem for p in EXAMPLES}
    assert names == {"duplicate", "increases_skew", "reduces_skew", "neutral", "unavailable"}
    for path in EXAMPLES:
        resp = VerdictResponse.model_validate_json(path.read_text())
        assert resp.verdict.value == path.stem
        assert wording.check(resp) == [], path.name


def test_request_ok_and_synthetic_ids_allowed():
    VerdictRequest.model_validate(REQUEST)
    VerdictRequest.model_validate({**REQUEST, "instrument_id": "SYN_OIL1"})


@pytest.mark.parametrize(
    "patch",
    [
        {"amount_rub": 0},
        {"instrument_id": "sber tqbr"},
        {"operation": "short"},
        {"portfolio": {"positions": [{"instrument_id": "TMOS_TQBR", "value_rub": -1}]}},
    ],
)
def test_bad_request_rejected(patch):
    with pytest.raises(ValidationError):
        VerdictRequest.model_validate({**REQUEST, **patch})


@pytest.mark.parametrize(
    "patch",
    [
        {"verdict": "buy_more"},
        {"severity": "critical"},
        {"flags": ["unknown_flag"]},
        {"factors_after": {"oil": 120.0}},
        {"factors_before": {"oil": 40.0, "banks": 20.0}},  # сумма не около 100
    ],
)
def test_bad_response_rejected(patch):
    data = json.loads(EXAMPLES[0].read_text())
    with pytest.raises(ValidationError):
        VerdictResponse.model_validate({**data, **patch})


@pytest.mark.parametrize(
    "text",
    [
        "Рекомендуем продать TMOS",
        "Лучше купите SBMX",
        "Вам стоит сократить долю",
        "Советуем подождать",
    ],
)
def test_wording_catches_advice(text):
    assert wording.problems(text)


def test_wording_allows_facts():
    assert wording.problems("SBMX повторяет тот же индекс, что ваш TMOS: корреляция 0,92") == []
    assert wording.problems("Стоимость позиции выросла до 50 000 ₽") == []
