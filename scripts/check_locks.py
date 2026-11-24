#!/usr/bin/env python3
"""Проверки lock-файлов.

check_locks.py A.txt B.txt ...  — в каждой паре файлов общие пакеты закреплены одинаково:
                                  runtime собран из base.txt, а тесты идут на dev.txt; образ
                                  test-ml ставит dev.txt поверх ml.txt и не должен менять версии;
check_locks.py --build-requires — напечатать build-system.requires из pyproject.toml
                                  (вход для requirements/build.txt).
"""

from __future__ import annotations

import re
import sys
import tomllib
from itertools import combinations
from pathlib import Path

PIN_RE = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s;\\]+)(?:\s*;\s*([^\\\n]+?))?\s*\\?$", re.M)
ROOT = Path(__file__).resolve().parents[1]


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def pins(text: str) -> dict[tuple[str, str], str]:
    """(пакет, маркер) → версия; маркер различает, например, torch для linux и macOS."""
    return {(_norm(n), (m or "").strip()): v for n, v, m in PIN_RE.findall(text)}


def mismatches(a: str, b: str) -> list[str]:
    pa, pb = pins(a), pins(b)
    out = []
    for key in sorted(set(pa) & set(pb)):
        if pa[key] != pb[key]:
            marker = f" ; {key[1]}" if key[1] else ""
            out.append(f"{key[0]}{marker}: {pa[key]} != {pb[key]}")
    return out


def build_requires(pyproject: Path) -> list[str]:
    return tomllib.loads(pyproject.read_text(encoding="utf-8"))["build-system"]["requires"]


def main(argv: list[str]) -> int:
    if argv == ["--build-requires"]:
        print("\n".join(build_requires(ROOT / "pyproject.toml")))
        return 0
    if len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    paths = [Path(x) for x in argv]
    texts = {p: p.read_text(encoding="utf-8") for p in paths}
    failed = False
    for a, b in combinations(paths, 2):
        bad = mismatches(texts[a], texts[b])
        for line in bad:
            print(f"{a.name} / {b.name}: {line}")
        if bad:
            failed = True
        else:
            print(f"{a.name} и {b.name}: общие пакеты закреплены одинаково")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
