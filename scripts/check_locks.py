#!/usr/bin/env python3
"""Проверки lock-файлов.

check_locks.py A.txt B.txt      — общие пакеты закреплены одинаково (образ test-ml ставит
                                  dev.txt поверх ml.txt и не должен менять версии);
check_locks.py --build-requires — напечатать build-system.requires из pyproject.toml
                                  (вход для requirements/build.txt).
"""

from __future__ import annotations

import re
import sys
import tomllib
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
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    a, b = (Path(x) for x in argv)
    bad = mismatches(a.read_text(encoding="utf-8"), b.read_text(encoding="utf-8"))
    for line in bad:
        print(f"{a.name} / {b.name}: {line}")
    if bad:
        return 1
    print(f"{a.name} и {b.name}: общие пакеты закреплены одинаково")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
