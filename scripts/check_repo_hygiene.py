#!/usr/bin/env python3
"""Гигиена публичного репозитория: секреты и рыночные данные (CONTEXT, раздел 6).

Проверяются файлы, которые отслеживает git (`git ls-files`):
- нет `.env*` (кроме `.env.example`), `*.sqlite*`, `*.log`, кассет и CA-бандла из `data/`;
- в `data/` только `*.yaml` верхнего уровня (конфигурация);
- нет строк, похожих на токен T-Invest;
- нет файлов больше 1 МБ, кроме явного списка;
- в `tests/fixtures/` нет реальных тикеров (синтетика начинается с `SYN`), кроме списка
  исключений с причиной.

    python scripts/check_repo_hygiene.py [--root .]
"""

from __future__ import annotations

import argparse
import fnmatch
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

MAX_BYTES = 1024 * 1024
LARGE_ALLOWED = {
    "tests/fixtures/synthetic/candles.csv": "синтетические свечи: 32 бумаги × 1500 дней",
}
FIXTURE_EXCEPTIONS = {
    "tests/fixtures/synthetic/manifest.json": (
        "в пояснении к ожидаемому свойству упомянуты TGLD, LQDT, TBRU как пример особенности "
        "данных (пустой сектор бренда); цен и ответов MCP нет"
    ),
}
FORBIDDEN = [
    "*.sqlite",
    "*.sqlite-*",
    "*.sqlite3",
    "*.log",
    "data/cassettes/*",
    "data/ca/*",
    "data/universe_resolved.json",
]
# Токен T-Invest: «t.» и 86 символов [A-Za-z0-9_-]. Порог 80 с запасом; «t.***» и короткие
# фейковые токены из тестов не подходят.
TOKEN_RE = re.compile(r"(?<![A-Za-z0-9_.-])t\.[A-Za-z0-9_-]{80,}")
CLASS_CODES = "TQBR|TQTF|TQCB|TQOB|TQIF|TQPI|SPEQ|SPBXM|CETS"
REAL_ID_RE = re.compile(rf"\b(?!SYN)[A-Z0-9]{{2,12}}_(?:{CLASS_CODES})\b")


@dataclass(frozen=True)
class Violation:
    path: str
    rule: str
    detail: str

    def __str__(self) -> str:
        return f"{self.path}: [{self.rule}] {self.detail}"


def git_files(root: Path) -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True
    ).stdout
    return sorted(p for p in out.decode("utf-8").split("\0") if p)


def _is_env(name: str) -> bool:
    return name != ".env.example" and (name == ".env" or name.startswith(".env."))


def _forbidden(path: str) -> bool:
    p = PurePosixPath(path)
    if _is_env(p.name):
        return True
    return any(fnmatch.fnmatch(path, pat) or fnmatch.fnmatch(p.name, pat) for pat in FORBIDDEN)


def _real_tickers(root: Path) -> set[str]:
    universe = root / "data" / "universe.yaml"
    if not universe.is_file():
        return set()
    ids = re.findall(r"^\s*-?\s*id:\s*([A-Za-z0-9]+)_", universe.read_text("utf-8"), re.M)
    # ISIN облигаций (RU000A...) в синтетике не встретятся; короче 3 знаков — шум
    return {t for t in ids if len(t) >= 3 and not t.startswith("SYN")}


def check(root: Path, files: list[str]) -> list[Violation]:
    root = Path(root)
    out: list[Violation] = []
    tickers = _real_tickers(root)
    ticker_re = (
        re.compile(r"(?<![A-Za-z0-9_])(" + "|".join(sorted(map(re.escape, tickers))) + r")\b")
        if tickers
        else None
    )
    for path in files:
        full = root / path
        if not full.is_file():  # удалён в рабочей копии
            continue
        if _forbidden(path):
            out.append(Violation(path, "forbidden-path", "файл не должен быть в git"))
            continue
        parts = PurePosixPath(path).parts
        if parts[0] == "data" and not (len(parts) == 2 and path.endswith(".yaml")):
            out.append(Violation(path, "data-not-yaml", "в data/ в git только *.yaml"))
        size = full.stat().st_size
        if size > MAX_BYTES and path not in LARGE_ALLOWED:
            out.append(Violation(path, "large-file", f"{size} байт > {MAX_BYTES}"))
        text = full.read_bytes().decode("utf-8", errors="ignore")
        for m in TOKEN_RE.finditer(text):
            line = text.count("\n", 0, m.start()) + 1
            out.append(Violation(path, "token", f"строка {line}: похоже на токен T-Invest"))
        if path.startswith("tests/fixtures/") and path not in FIXTURE_EXCEPTIONS:
            found = set(REAL_ID_RE.findall(text))
            if ticker_re:
                found |= set(ticker_re.findall(text))
            if found:
                sample = ", ".join(sorted(found)[:5])
                out.append(Violation(path, "real-ticker-in-fixture", f"реальные тикеры: {sample}"))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    files = git_files(args.root)
    violations = check(args.root, files)
    for v in violations:
        print(v)
    if violations:
        print(f"Гигиена: {len(violations)} нарушений в {len(files)} файлах")
        return 1
    print(f"Гигиена: ок, проверено файлов: {len(files)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
