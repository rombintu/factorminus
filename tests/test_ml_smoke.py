"""ML smoke: laya импортируется, веса берутся из образа без сети, predict отвечает.

Запуск: `make test-ml` в образе `runtime-ml` (CI: .github/workflows/ml.yml). Сеть в тесте
заблокирована (conftest), поэтому загрузка весов из интернета сразу упадёт.
"""

import pytest

pytestmark = pytest.mark.ml

QUESTIONS = {
    "same_index": {"type": "noul", "instructions": "Оба фонда повторяют один и тот же индекс?"},
    "kind": {
        "type": "choice",
        "instructions": "Что это за бумага?",
        "criteria": {"fund": "биржевой фонд", "share": "акция компании"},
    },
}


def test_laya_router_offline_predict():
    laya = pytest.importorskip("laya")
    router = laya.Router(preload=True)
    res = router.predict("Фонд повторяет индекс Мосбиржи: 40 крупнейших компаний.", QUESTIONS)
    answers = res["answers"]
    assert 0.0 <= answers["same_index"]["noul"] <= 1.0
    assert answers["kind"]["choice"] in {"fund", "share"}
    assert set(answers["kind"]["probabilities"]) == {"fund", "share"}
    assert res["routing"]["model"]
