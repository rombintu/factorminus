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
    # модальные слова совета; «необходимые данные» и «фонд повторяет индекс» — факты
    "следует": re.compile(r"\bследует\b", re.IGNORECASE),
    "нужно": re.compile(r"\bнужно\b", re.IGNORECASE),
    "надо": re.compile(r"\bнадо\b", re.IGNORECASE),
    "необходимо": re.compile(r"\bнеобходимо\b", re.IGNORECASE),
    "стоило бы": re.compile(r"\bстоило\s+бы\b", re.IGNORECASE),
    # повелительное наклонение: только формы на -те, без изъявительных («фиксирует», «увеличит»)
    "избегайте": re.compile(r"\bизбегай(те)?\b", re.IGNORECASE),
    "не берите": re.compile(r"\b(не\s+)?бери(те)?\b", re.IGNORECASE),
    "сократите": re.compile(r"\bсократи(те)?\b", re.IGNORECASE),
    "уменьшите": re.compile(r"\bуменьши(те)?\b", re.IGNORECASE),
    "увеличьте": re.compile(r"\bувеличь(те)?\b", re.IGNORECASE),
    "замените": re.compile(r"\bзамени(те)?\b", re.IGNORECASE),
    "держите": re.compile(r"\bдержи(те)?\b", re.IGNORECASE),
    "фиксируйте": re.compile(r"\bфиксируй(те)?\b", re.IGNORECASE),
    "выгодно": re.compile(r"\bвыгодн(о|ее)\b", re.IGNORECASE),
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
