#!/usr/bin/env python3
"""Текст GitHub Release для тега vX.Y.Z.

Этапы и отчёты берутся из строк `docs/STAGES.md` с этим тегом в колонке «Тег» (в том числе
«в составе `vX.Y.Z`», когда несколько этапов сдаются одним PR и одним релизом). Из каждого
отчёта — раздел «## Что сделано» целиком (с подразделами), по порядку этапов в журнале.
Плюс ссылки на образы GHCR и на прогон CI.

    python scripts/release_notes.py --tag v0.1.5 [--docs docs] > build/release.md
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

IMAGE = "ghcr.io/rombintu/factorminus"
TAG_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
CELL_TAG_RE = re.compile(r"v\d+\.\d+\.\d+")
LINK_RE = re.compile(r"\]\(([^)]+)\)")


class ReleaseError(Exception):
    pass


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def stages_for_tag(stages_md: Path, tag: str) -> list[dict[str, str]]:
    """Строки журнала этапов с этим тегом: этап и путь к отчёту (относительно docs/).

    Порядок — как в журнале. Тег в ячейке может стоять с пометкой («в составе `v0.1.5`»).
    """
    lines = [ln for ln in stages_md.read_text(encoding="utf-8").splitlines() if ln.startswith("|")]
    if len(lines) < 3:
        raise ReleaseError(f"{stages_md}: нет таблицы этапов")
    header = [h.lower() for h in _cells(lines[0])]
    col = {name: header.index(name) for name in ("этап", "тег", "отчёт")}
    rows = []
    for line in lines[2:]:
        cells = _cells(line)
        if tag not in CELL_TAG_RE.findall(cells[col["тег"]]):
            continue
        link = LINK_RE.search(cells[col["отчёт"]])
        if not link:
            raise ReleaseError(f"{stages_md}: у этапа {cells[col['этап']]} нет ссылки на отчёт")
        rows.append({"stage": cells[col["этап"]], "report": link.group(1)})
    if not rows:
        raise ReleaseError(f"{stages_md}: тег {tag} не найден в журнале этапов")
    return rows


def done_section(report: Path) -> str:
    """Раздел «## Что сделано» до следующего заголовка второго уровня."""
    if not report.is_file():
        raise ReleaseError(f"нет отчёта этапа {report}")
    out: list[str] = []
    inside = found = False
    for line in report.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            if inside:
                break
            inside = line[3:].strip().lower() == "что сделано"
            found = found or inside
            continue
        if inside:
            out.append(line)
    text = "\n".join(out).strip()
    if not found or not text:
        raise ReleaseError(f"{report}: нет раздела «## Что сделано» или он пуст")
    return text


def render(docs: Path, tag: str, *, repo: str, run_url: str) -> str:
    m = TAG_RE.match(tag)
    if not m:
        raise ReleaseError(f"тег {tag!r}: ожидается vX.Y.Z (тег stage-N не используется)")
    version = tag[1:]
    rows = stages_for_tag(docs / "STAGES.md", tag)
    lines: list[str] = []
    for row in rows:
        lines += [f"## Этап {row['stage']}", "", done_section(docs / row["report"]), ""]
    lines += [
        "## Образы",
        "",
        f"- `{IMAGE}:{version}` (также `:{m.group(1)}.{m.group(2)}` и `:latest`) — runtime",
        f"- `{IMAGE}:{version}-ml` — runtime-ml (laya, torch CPU, веса модели)",
        "",
        "Платформы: linux/amd64, linux/arm64. Запуск: `docs/DEPLOY.md`.",
        "",
    ]
    for row in rows:
        url = f"https://github.com/{repo}/blob/{tag}/docs/{row['report']}"
        lines.append(f"Отчёт этапа {row['stage']}: {url}")
    if run_url:
        lines.append(f"Сводка CI: {run_url}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tag", required=True)
    parser.add_argument("--docs", type=Path, default=Path(__file__).resolve().parents[1] / "docs")
    args = parser.parse_args(argv)
    repo = os.environ.get("GITHUB_REPOSITORY", "rombintu/factorminus")
    run_id = os.environ.get("GITHUB_RUN_ID")
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    run_url = f"{server}/{repo}/actions/runs/{run_id}" if run_id else ""
    try:
        sys.stdout.write(render(args.docs, args.tag, repo=repo, run_url=run_url))
    except ReleaseError as e:
        print(f"Ошибка: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
