"""Read-only клиент T-Invest MCP (Streamable HTTP, JSON-RPC 2.0).

Безопасность:
- инструмент проверяется по белому списку до любого сетевого запроса;
- токен живёт только в заголовке `Authorization` и не попадает в логи и repr;
- TLS проверяется всегда (`TINVEST_CA_BUNDLE` для российского УЦ).
"""

from __future__ import annotations

import json
import logging
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from factorminus import __version__
from factorminus.config import REPO_ROOT, Settings
from factorminus.mcp.allowlist import ensure_allowed
from factorminus.mcp.cassette import MODES, Cassette, Mode
from factorminus.mcp.errors import McpError, McpToolError, McpTransportError

log = logging.getLogger("factorminus.mcp")

PROTOCOL_VERSION = "2025-03-26"
TIMEOUT_S = 30.0
META_TOOL = "_meta"
TOOLS_LIST_ARGS = {"method": "tools/list"}
DEFAULT_CASSETTE_DIR = REPO_ROOT / "data" / "cassettes"
MAX_ERROR_LEN = 300
MAX_RETRY_AFTER_S = 30.0


class RateLimiter:
    """Не больше `max_per_minute` событий в скользящем окне 60 секунд."""

    def __init__(
        self,
        max_per_minute: int,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.max = max_per_minute
        self.clock = clock
        self.sleep = sleep
        self.stamps: deque[float] = deque()

    def _drop_old(self, now: float) -> None:
        while self.stamps and now - self.stamps[0] >= 60.0:
            self.stamps.popleft()

    def acquire(self) -> None:
        now = self.clock()
        self._drop_old(now)
        if len(self.stamps) >= self.max:
            wait = 60.0 - (now - self.stamps[0])
            if wait > 0:
                self.sleep(wait)
            self._drop_old(self.clock())
        self.stamps.append(self.clock())


class _SessionExpired(Exception):
    pass


def _parse_body(response: httpx.Response, rid: int) -> dict:
    """Достаёт JSON-RPC сообщение с нужным `id` из JSON- или SSE-ответа."""
    ctype = response.headers.get("content-type", "")
    messages: list[Any] = []
    if "text/event-stream" in ctype:
        data_lines: list[str] = []
        for line in response.text.splitlines() + [""]:
            if line.startswith("data:"):
                data_lines.append(line[5:].lstrip())
            elif line.strip() == "" and data_lines:
                try:
                    messages.append(json.loads("\n".join(data_lines)))
                except json.JSONDecodeError:
                    pass
                data_lines = []
    else:
        try:
            messages.append(response.json())
        except json.JSONDecodeError as e:
            raise McpTransportError(f"Нечитаемый ответ MCP (HTTP {response.status_code})") from e
    flat: list[Any] = []
    for m in messages:
        flat.extend(m if isinstance(m, list) else [m])
    for m in flat:
        if isinstance(m, dict) and m.get("id") == rid:
            return m
    raise McpTransportError(f"В ответе MCP нет сообщения с id={rid}")


def _unwrap_result(name: str, msg: dict, scrub: Callable[[str], str]) -> Any:
    if "error" in msg:
        err = msg["error"] or {}
        raise McpToolError(name, scrub(str(err.get("message") or err)))
    result = msg.get("result") or {}
    texts = [c.get("text", "") for c in result.get("content", []) if c.get("type") == "text"]
    if result.get("isError"):
        raise McpToolError(name, scrub("\n".join(texts) or "isError без текста"))
    if not texts:
        return result.get("structuredContent", result)
    parsed: list[Any] = []
    for t in texts:
        try:
            parsed.append(json.loads(t))
        except (json.JSONDecodeError, TypeError):
            parsed.append(t)
    return parsed[0] if len(parsed) == 1 else parsed


class McpClient:
    def __init__(
        self,
        settings: Settings,
        *,
        mode: Mode = "live",
        cassette_dir: Path | str = DEFAULT_CASSETTE_DIR,
        transport: httpx.BaseTransport | None = None,
        max_rpm: int = 180,
        retries: int = 3,
        backoff: float = 0.5,
        sleep: Callable[[float], None] = time.sleep,
    ):
        if mode not in MODES:
            raise ValueError(f"mode должен быть одним из {MODES}")
        self.settings = settings
        self.mode = mode
        self.cassette = Cassette(cassette_dir)
        self.retries = retries
        self.backoff = backoff
        self.sleep = sleep
        self.limiter = RateLimiter(max_rpm, sleep=sleep)
        self._session_id: str | None = None
        self._initialized = False
        self._next_id = 0
        self._http: httpx.Client | None = None
        self._token: str | None = None
        if mode != "replay":
            token = settings.require_token()
            self._token = token
            self._http = httpx.Client(
                timeout=TIMEOUT_S,
                verify=settings.ssl_verify(),
                transport=transport,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json, text/event-stream",
                    "Content-Type": "application/json",
                    "User-Agent": f"factorminus/{__version__}",
                },
            )

    def __repr__(self) -> str:
        return f"McpClient(url={self.settings.mcp_url!r}, mode={self.mode!r})"

    def __enter__(self) -> McpClient:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        if self._http is not None:
            self._http.close()

    def _scrub(self, text: str) -> str:
        """Убирает токен из текста ошибки и обрезает длинные сообщения."""
        if self._token:
            text = text.replace(self._token, "t.***")
        if len(text) > MAX_ERROR_LEN:
            text = text[:MAX_ERROR_LEN] + "…"
        return text

    # --- публичный API ---

    def call_tool(self, name: str, arguments: dict | None = None) -> Any:
        ensure_allowed(name)
        arguments = dict(arguments or {})
        if self.mode == "replay":
            return self.cassette.load(name, arguments)
        started = time.perf_counter()
        msg, size = self._request("tools/call", {"name": name, "arguments": arguments})
        result = _unwrap_result(name, msg, self._scrub)
        log.info(
            "mcp %s args=%s %.0f ms %d B",
            name,
            json.dumps(arguments, ensure_ascii=False, sort_keys=True),
            (time.perf_counter() - started) * 1000,
            size,
        )
        if self.mode == "record":
            self.cassette.save(name, arguments, result)
        return result

    def list_tools(self) -> list[str]:
        if self.mode == "replay":
            return list(self.cassette.load(META_TOOL, TOOLS_LIST_ARGS))
        msg, size = self._request("tools/list", {})
        if "error" in msg:
            raise McpToolError("tools/list", self._scrub(str(msg["error"])))
        names = [t["name"] for t in (msg.get("result") or {}).get("tools", [])]
        log.info("mcp tools/list -> %d tools, %d B", len(names), size)
        if self.mode == "record":
            self.cassette.save(META_TOOL, TOOLS_LIST_ARGS, names)
        return names

    # --- протокол ---

    def _new_id(self) -> int:
        self._next_id += 1
        return self._next_id

    def _initialize(self) -> None:
        self._session_id = None
        rid = self._new_id()
        params = {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "factorminus", "version": __version__},
        }
        resp = self._post({"jsonrpc": "2.0", "id": rid, "method": "initialize", "params": params})
        msg = _parse_body(resp, rid)
        if "error" in msg:
            raise McpTransportError(self._scrub(f"initialize отклонён: {msg['error']}"))
        self._session_id = resp.headers.get("mcp-session-id")
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        self._initialized = True
        log.info("mcp session initialized (session id %s)", "есть" if self._session_id else "нет")

    def _request(self, method: str, params: dict) -> tuple[dict, int]:
        if self._http is None:
            raise McpError("Клиент в режиме replay не ходит в сеть")
        if not self._initialized:
            self._initialize()
        reinitialized = False
        while True:
            rid = self._new_id()
            payload = {"jsonrpc": "2.0", "id": rid, "method": method, "params": params}
            try:
                resp = self._post(payload)
            except _SessionExpired:
                if reinitialized:
                    raise McpTransportError("Сессия MCP истекла повторно") from None
                reinitialized = True
                log.info("mcp session expired, reinitializing")
                self._initialize()
                continue
            return _parse_body(resp, rid), len(resp.content)

    def _post(self, payload: dict) -> httpx.Response:
        assert self._http is not None
        headers = {"Mcp-Session-Id": self._session_id} if self._session_id else {}
        last = ""
        retry_after: float | None = None
        for attempt in range(self.retries):
            if attempt:
                delay = self.backoff * 2 ** (attempt - 1)
                if retry_after is not None:
                    delay = max(delay, min(retry_after, MAX_RETRY_AFTER_S))
                self.sleep(delay)
                retry_after = None
            self.limiter.acquire()
            try:
                resp = self._http.post(self.settings.mcp_url, json=payload, headers=headers)
            except httpx.TransportError as e:
                last = f"сетевая ошибка: {type(e).__name__}"
                continue
            if resp.status_code == 429 or resp.status_code >= 500:
                last = f"HTTP {resp.status_code}"
                try:
                    retry_after = float(resp.headers.get("retry-after", ""))
                except ValueError:
                    retry_after = None
                continue
            if self._session_id and (
                resp.status_code == 404
                or (resp.status_code == 400 and "session" in resp.text.lower())
            ):
                raise _SessionExpired()
            if resp.status_code in (401, 403):
                raise McpTransportError(
                    f"HTTP {resp.status_code}: токен отклонён (проверьте TINVEST_TOKEN)"
                )
            if resp.status_code >= 400:
                raise McpTransportError(self._scrub(f"HTTP {resp.status_code}: {resp.text}"))
            return resp
        raise McpTransportError(f"MCP недоступен после {self.retries} попыток: {last}")
