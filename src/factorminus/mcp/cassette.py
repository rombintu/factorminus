"""Кассеты: запись и воспроизведение ответов MCP.

Файл `<root>/<tool>/<sha1(args)>.json` хранит `{"tool", "arguments", "result"}`.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Literal

from factorminus.mcp.errors import CassetteMissError

Mode = Literal["live", "record", "replay"]
MODES: tuple[str, ...] = ("live", "record", "replay")
_TOOL_RE = re.compile(r"^[a-z0-9_]+$")


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


class Cassette:
    def __init__(self, root: Path | str):
        self.root = Path(root)

    @staticmethod
    def key(tool: str, args: dict) -> str:
        return hashlib.sha1(canonical_json(args).encode("utf-8")).hexdigest()

    def path(self, tool: str, args: dict) -> Path:
        if not _TOOL_RE.match(tool):
            raise ValueError(f"Недопустимое имя инструмента для кассеты: {tool!r}")
        return self.root / tool / f"{self.key(tool, args)}.json"

    def load(self, tool: str, args: dict) -> Any:
        path = self.path(tool, args)
        if not path.is_file():
            raise CassetteMissError(tool, path)
        return json.loads(path.read_text(encoding="utf-8"))["result"]

    def save(self, tool: str, args: dict, result: Any) -> Path:
        path = self.path(tool, args)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"tool": tool, "arguments": args, "result": result}
        path.write_text(
            canonical_json(payload) + "\n",
            encoding="utf-8",
        )
        return path
