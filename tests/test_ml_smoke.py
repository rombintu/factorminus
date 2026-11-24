"""ML smoke: laya импортируется, веса берутся из образа без сети, predict отвечает.

Запуск: `make docker-test-ml` в образе `test-ml` (CI: .github/workflows/ml.yml). Сеть в тесте
заблокирована (conftest), поэтому загрузка весов из интернета сразу упадёт.

Боевой путь — `Router()` без `preload`: модель грузится при первом запросе, русский текст
уходит в multilingual, английская модель и typed-decisions в память не попадают. Так laya
помещается в Docker Desktop с 4 ГБ. `preload=True` держит в памяти все три модели и нужен
только серверу с запасом памяти: тест с ним помечен `ml_heavy` и идёт только в CI.
"""

import pytest

pytestmark = pytest.mark.ml

TEXT_RU = "Фонд повторяет индекс Мосбиржи: 40 крупнейших компаний."
QUESTIONS = {
    "same_index": {"type": "noul", "instructions": "Оба фонда повторяют один и тот же индекс?"},
    "kind": {
        "type": "choice",
        "instructions": "Что это за бумага?",
        "criteria": {"fund": "биржевой фонд", "share": "акция компании"},
    },
}


def _check_answers(res):
    answers = res["answers"]
    assert 0.0 <= answers["same_index"]["noul"] <= 1.0
    assert answers["kind"]["choice"] in {"fund", "share"}
    assert set(answers["kind"]["probabilities"]) == {"fund", "share"}


def test_laya_router_lazy_russian_goes_multilingual():
    laya = pytest.importorskip("laya")
    router = laya.Router()
    res = router.predict(TEXT_RU, QUESTIONS)
    _check_answers(res)
    assert res["routing"]["model"] == "multilingual"


@pytest.mark.ml_heavy
def test_laya_router_preload_all_models():
    laya = pytest.importorskip("laya")
    router = laya.Router(preload=True)
    res = router.predict(TEXT_RU, QUESTIONS)
    _check_answers(res)
    assert res["routing"]["model"] == "multilingual"
