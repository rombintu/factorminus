"""Линтер формулировок плашки: только факты, без советов (39-ФЗ)."""

import re

ADVICE = re.compile(
    r"\b(купите|купи|покупайте|продайте|продавайте|продай|рекомендуем|рекомендую|"
    r"советуем|советую|лучше|стоит|следует)\b",
    re.IGNORECASE,
)


def problems(text: str) -> list[str]:
    """Слова-советы, найденные в тексте."""
    return [m.group(0) for m in ADVICE.finditer(text)]


def check(resp) -> list[str]:
    """Проверить заголовок и факты вердикта; пустой список — формулировки чистые."""
    found = []
    for text in [resp.headline, *resp.facts]:
        found += [f"«{word}» в: {text}" for word in problems(text)]
    return found
