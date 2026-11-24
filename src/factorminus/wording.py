"""Линтер формулировок плашки: только факты, без инвестиционных советов (39-ФЗ).

Переиспользуется на этапе 2 для всех вердиктов.
"""

from __future__ import annotations

import re
from typing import Any

# Основы слов-советов. «покупка», «продажа», «стоимость» — факты, они разрешены.
FORBIDDEN_PATTERNS: dict[str, re.Pattern[str]] = {
    "купите": re.compile(r"\b(до)?купи(те)?\b|\bпокупай(те)?\b", re.IGNORECASE),
    "продайте": re.compile(r"\bпрода(й|йте|вай|вайте)\b", re.IGNORECASE),
    "рекомендуем": re.compile(r"\bрекоменд\w*", re.IGNORECASE),
    "советуем": re.compile(r"\bсовет(ую|уем|уете)\b", re.IGNORECASE),
    "лучше": re.compile(r"\bлучше\b", re.IGNORECASE),
    "стоит": re.compile(r"\bстоит\b", re.IGNORECASE),
}
FORBIDDEN_WORDS: tuple[str, ...] = tuple(FORBIDDEN_PATTERNS)


def find_forbidden(text: str) -> list[str]:
    """Список запрещённых слов, найденных в тексте (пустой — текст чистый)."""
    return [word for word, rx in FORBIDDEN_PATTERNS.items() if rx.search(text or "")]


def check_response_wording(resp: Any) -> list[str]:
    """Проверяет `headline` и `facts` ответа. Возвращает описания нарушений."""
    problems = []
    texts = [("headline", resp.headline)] + [(f"facts[{i}]", f) for i, f in enumerate(resp.facts)]
    for where, text in texts:
        for word in find_forbidden(text):
            problems.append(f"{where}: «{word}» в «{text}»")
    return problems
