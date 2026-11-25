#!/usr/bin/env python3
"""Гигиена публичного репозитория: секреты и рыночные данные (CONTEXT, раздел 6).

Проверяются файлы, которые отслеживает git (`git ls-files`):
- нет `.env*` (кроме `.env.example`), `*.sqlite*`, `*.log`, кассет и CA-бандла из `data/`;
- в `data/` только `*.yaml` верхнего уровня (конфигурация);
- нет строк, похожих на токен T-Invest;
- нет файлов больше 1 МБ, кроме явного списка;
- файлы данных (`csv`, `json`, `parquet`, `db` и т. п.) лежат только в `DATA_DIRS`, кроме
  списка исключений с причиной;
- в `DATA_DIRS` и `tests/fixtures/` нет реальных тикеров (синтетика начинается с `SYN`),
  кроме списка исключений с причиной;
- в файлах, кроме `.py` и `.md`, нет ответов MCP: ключей `instrumentUid`, `assetUid`,
  `positionUid`, `figi`, `brandUid` с несинтетическим значением и `candles` вместе с `close`.

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
# Файлы данных разрешены только здесь (синтетика, кейсы eval, схема контракта)
DATA_DIRS = ("tests/fixtures/synthetic/", "tests/cases/", "docs/contract/")
DATA_EXTS = {
    ".csv", ".tsv", ".json", ".jsonl", ".parquet", ".feather", ".xlsx",
    ".pkl", ".pickle", ".npz", ".npy", ".db",
}  # fmt: skip
DATA_FILE_EXCEPTIONS: dict[str, str] = {}
SCHEMA_ID_EXAMPLE = (
    "пример формата InstrumentId в JSON Schema (examples из src/factorminus/contracts.py); "
    "цен и ответов MCP нет"
)
TICKER_EXCEPTIONS = {
    "tests/fixtures/synthetic/manifest.json": (
        "в пояснении к ожидаемому свойству упомянуты TGLD, LQDT, TBRU как пример особенности "
        "данных (пустой сектор бренда); цен и ответов MCP нет"
    ),
    "docs/contract/verdict_request.schema.json": SCHEMA_ID_EXAMPLE,
    "docs/contract/verdict_response.schema.json": SCHEMA_ID_EXAMPLE,
}
FORBIDDEN = [
    "*.sqlite",
    "*.sqlite-*",
    "*.sqlite3",
    "*.log",
    "data/cassettes/*",
    "data/universe_resolved.json",
]
# Токен T-Invest: «t.» и 86 символов [A-Za-z0-9_-]. Порог 80 с запасом; «t.***» и короткие
# фейковые токены из тестов не подходят.
TOKEN_RE = re.compile(r"(?<![A-Za-z0-9_.-])t\.[A-Za-z0-9_-]{80,}")
CLASS_CODES = "TQBR|TQTF|TQCB|TQOB|TQIF|TQPI|SPEQ|SPBXM|CETS"
REAL_ID_RE = re.compile(rf"\b(?!SYN)[A-Z0-9]{{2,12}}_(?:{CLASS_CODES})\b")
# Ключи ответа MCP. Синтетика повторяет форму ответа, но её значения начинаются с «syn»
# или пусты (null — кейс «нет бренда»).
MCP_KEY_RE = re.compile(
    r'"(instrumentUid|assetUid|positionUid|figi|brandUid)"\s*:\s*+(?!"syn|null\b)', re.I
)
CODE_SUFFIXES = {".py", ".md"}
# Сертификаты и ключи: в git только корневой сертификат Минцифры в пакете
CERT_SUFFIXES = {".pem", ".crt", ".cer", ".der", ".p12", ".pfx", ".key"}
ROOT_CA_PATH = "src/factorminus/certs/russian_trusted_root_ca.pem"


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


def _in_data_dir(path: str) -> bool:
    return path.startswith(DATA_DIRS)


def _mcp_response(text: str) -> str | None:
    m = MCP_KEY_RE.search(text)
    if m:
        return f'ключ ответа MCP "{m.group(1)}"'
    if '"candles"' in text and '"close"' in text:
        return 'ключи ответа MCP "candles" и "close"'
    return None


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
        suffix = PurePosixPath(path).suffix.lower()
        if suffix in CERT_SUFFIXES and path != ROOT_CA_PATH:
            out.append(Violation(path, "certificate-path", f"сертификат только {ROOT_CA_PATH}"))
        if suffix in DATA_EXTS and not _in_data_dir(path) and path not in DATA_FILE_EXCEPTIONS:
            out.append(
                Violation(
                    path,
                    "data-file-outside-allowlist",
                    f"файлы данных только в {', '.join(DATA_DIRS)}",
                )
            )
        if suffix not in CODE_SUFFIXES and (reason := _mcp_response(text)):
            out.append(Violation(path, "mcp-response", reason))
        in_scope = _in_data_dir(path) or path.startswith("tests/fixtures/")
        if in_scope and path not in TICKER_EXCEPTIONS:
            found = set(REAL_ID_RE.findall(text))
            if ticker_re:
                found |= set(ticker_re.findall(text))
            if found:
                sample = ", ".join(sorted(found)[:5])
                out.append(Violation(path, "real-ticker-in-data", f"реальные тикеры: {sample}"))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--summary", type=Path, help="Markdown-секция для сводки CI")
    args = parser.parse_args(argv)
    files = git_files(args.root)
    violations = check(args.root, files)
    for v in violations:
        print(v)
    if violations:
        result = f"{len(violations)} нарушений в {len(files)} файлах"
    else:
        result = f"ок, проверено файлов: {len(files)}"
    print(f"Гигиена: {result}")
    if args.summary:
        lines = ["### Гигиена репозитория", "", ("❌ " if violations else "✅ ") + result]
        lines += [f"- `{v.path}`: {v.rule}" for v in violations[:20]]
        args.summary.parent.mkdir(parents=True, exist_ok=True)
        args.summary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
