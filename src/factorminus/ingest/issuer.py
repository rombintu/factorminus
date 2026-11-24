"""Эмитент бумаги: кто несёт риск («один эмитент» — слой 1).

Правило (ТЗ правок этапа 1, п. 1):
1. `issuer:` из universe.yaml — ручное переопределение (облигации через финансовые «дочки»);
2. иначе `brands.company`. Для фондов company — это управляющая компания, а не эмитент риска,
   поэтому у фондов (kind=etf) берётся имя бренда фонда;
3. бренда нет — NULL.
"""

from __future__ import annotations


def normalize_issuer(name: str | None) -> tuple[str | None, str | None]:
    """(вид для показа, ключ для сравнения): пробелы схлопнуты, ключ в casefold."""
    if not name:
        return None, None
    display = " ".join(name.split())
    if not display:
        return None, None
    return display, display.casefold()


def pick_issuer(
    *, override: str | None, kind: str, brand_name: str | None, brand_company: str | None
) -> tuple[str | None, str | None]:
    if override:
        return normalize_issuer(override)
    if kind == "etf":
        return normalize_issuer(brand_name)
    return normalize_issuer(brand_company)
