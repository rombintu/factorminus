#!/usr/bin/env python3
"""Добавить в lock-файл индекс CPU-сборок torch (uv не пишет явные индексы в вывод)."""

import sys
from pathlib import Path

PYPI = "--index-url https://pypi.org/simple\n"
TORCH_CPU = "--extra-index-url https://download.pytorch.org/whl/cpu\n"


def main(path: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if TORCH_CPU not in text:
        if PYPI not in text:
            sys.exit(f"{path}: нет строки {PYPI.strip()!r}")
        text = text.replace(PYPI, PYPI + TORCH_CPU, 1)
        p.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1])
