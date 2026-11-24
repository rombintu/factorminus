# Контракт вердикта v1.0

Описание полей: `docs/CONTEXT.md`, раздел 7. Модели: `src/factorminus/contracts.py`.

- `verdict_request.schema.json`, `verdict_response.schema.json` — JSON Schema, генерируются командой `fm contract export`. Руками не править: тест сверяет файлы с моделями.
- `examples/` — по одному примеру ответа на вердикты `duplicate`, `increases_skew`, `reduces_skew`, `neutral`, `unavailable`. Бумаги в примерах синтетические (`SYN_*`), числа иллюстративные, это не рыночные данные.

Правила, которые проверяют тесты:
- доли в `factors_*` и `issuers_*` в процентах, от 0 до 100; сумма `factors_*` равна 100 ± 0,5;
- `no_data` и `unavailable` идут только с `severity: none`;
- в `headline` и `facts` нет слов-советов (линтер `factorminus/wording.py`): «купите», «продайте», «рекомендуем», «советуем», «лучше», «стоит».
