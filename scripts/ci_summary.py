#!/usr/bin/env python3
"""Сводка прогона CI → `$GITHUB_STEP_SUMMARY` (или stdout).

Источники в каталоге `build/`:
- `junit.xml` (pytest) — passed / skipped / failed;
- `coverage.xml` (pytest-cov) — покрытие;
- `ci/build-<цель>.txt` — время сборки образа в секундах (scripts/timed.sh);
- `ci/*.md` — готовые секции от целей Makefile, по порядку имён.

Расширение: новая цель Makefile пишет `build/ci/NN-имя.md`, скрипт менять не нужно
(так этап 2 добавит метрики `fm eval`, этап 4 — e2e).

    python scripts/ci_summary.py [--build build]
"""

from __future__ import annotations

import argparse
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def _tests(build: Path) -> list[str]:
    path = build / "junit.xml"
    if not path.is_file():
        return ["### Тесты", "", "нет данных (junit.xml не найден)"]
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else root.findall("testsuite")
    total = skipped = failed = 0
    for s in suites:
        total += int(s.get("tests", 0))
        skipped += int(s.get("skipped", 0))
        failed += int(s.get("failures", 0)) + int(s.get("errors", 0))
    passed = total - skipped - failed
    mark = "✅" if failed == 0 else "❌"
    return [
        f"### Тесты {mark}",
        "",
        "| passed | skipped | failed |",
        "|---:|---:|---:|",
        f"| {passed} | {skipped} | {failed} |",
    ]


def _coverage(build: Path) -> list[str]:
    path = build / "coverage.xml"
    if not path.is_file():
        return ["", "Покрытие: нет данных (coverage.xml не найден)"]
    rate = float(ET.parse(path).getroot().get("line-rate", 0))
    return ["", f"Покрытие: **{rate * 100:.1f}%**"]


def _build_times(build: Path) -> list[str]:
    files = sorted((build / "ci").glob("build-*.txt"))
    if not files:
        return []
    rows = ["### Время сборки образов", "", "| цель | время |", "|---|---:|"]
    for f in files:
        rows.append(f"| {f.stem.removeprefix('build-')} | {f.read_text().strip()} с |")
    return rows


def render(build: Path) -> str:
    build = Path(build)
    parts = ["## Сводка прогона", ""]
    parts += _tests(build) + _coverage(build)
    times = _build_times(build)
    if times:
        parts += [""] + times
    for section in sorted((build / "ci").glob("*.md")):
        parts += ["", section.read_text(encoding="utf-8").rstrip()]
    return "\n".join(parts) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--build", type=Path, default=Path("build"))
    args = parser.parse_args(argv)
    md = render(args.build)
    target = os.environ.get("GITHUB_STEP_SUMMARY")
    if target:
        with open(target, "a", encoding="utf-8") as f:
            f.write(md)
    else:
        sys.stdout.write(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
