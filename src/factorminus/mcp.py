"""Клиент T-Invest MCP (Streamable HTTP, JSON-RPC 2.0). Только чтение, белый список."""

import itertools
import json
import sys
import time

import httpx

from . import config

ALLOWED = frozenset(
    {
        "invest_find_instrument",
        "invest_get_share",
        "invest_get_etf",
        "invest_get_bond",
        "invest_get_currency",
        "invest_get_asset",
        "invest_get_brand",
        "invest_get_candles",
        "invest_get_risk_rates",
    }
)
PAUSE = 0.33  # лимит 200 запросов в минуту, равномерно
ATTEMPTS = 3


class McpError(Exception):
    """Ожидаемая ошибка MCP: CLI печатает её без трейсбека."""


class _SessionExpired(McpError):
    def __init__(self):
        super().__init__("сессия MCP истекла и после переподключения")


class Mcp:
    def __init__(self, token, url, transport=None, verbose=False, pause=PAUSE):
        self.url = config.check_url(url)
        self.verbose, self.pause = verbose, pause
        self.session, self.ready = None, False
        self._ids = itertools.count(1)
        self._last = 0.0
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json, text/event-stream",
        }
        verify = config.tls_context()
        self.http = httpx.Client(timeout=30, headers=headers, verify=verify, transport=transport)

    def __repr__(self):
        return f"Mcp({self.url!r})"

    def close(self):
        self.http.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def call(self, tool: str, args: dict | None = None):
        """Вызвать инструмент и вернуть разобранный JSON из result.content."""
        if tool not in ALLOWED:
            raise McpError(f"инструмент {tool} не в белом списке, запрос не отправлен")
        args = args or {}
        started = time.monotonic()
        try:
            return parse_result(
                tool, self._request("tools/call", {"name": tool, "arguments": args})
            )
        finally:
            if self.verbose:
                shown = json.dumps(args, ensure_ascii=False)
                print(f"mcp {tool} {shown} {time.monotonic() - started:.2f}s", file=sys.stderr)

    def tools(self) -> list[str]:
        return [t["name"] for t in self._request("tools/list", {}).get("tools", [])]

    def _request(self, method, params):
        if not self.ready:
            self._initialize()
        try:
            return self._rpc(method, params)
        except _SessionExpired:
            self._initialize()
            return self._rpc(method, params)

    def _initialize(self):
        self.session, self.ready = None, False
        info = {"name": "factorminus", "version": "0.1"}
        params = {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": info}
        self._rpc("initialize", params)
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        self.ready = True

    def _rpc(self, method, params):
        rid = next(self._ids)
        resp = self._post({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        msg = read_message(resp, rid)
        if "error" in msg:
            err = msg["error"]
            raise McpError(f"{method}: {err.get('message')} (код {err.get('code')})")
        return msg.get("result", {})

    def _post(self, body):
        headers = {"Mcp-Session-Id": self.session} if self.session else {}
        problem = ""
        for attempt in range(ATTEMPTS):
            if attempt:
                time.sleep(self.pause * 3**attempt)
            self._throttle()
            try:
                resp = self.http.post(self.url, json=body, headers=headers)
            except httpx.TransportError as e:
                problem = f"сеть недоступна ({type(e).__name__})"
                continue
            if resp.status_code == 429 or resp.status_code >= 500:
                problem = f"HTTP {resp.status_code}"
                if retry_after := self._retry_after(resp):
                    time.sleep(retry_after)
                continue
            return self._check(resp)
        raise McpError(f"{body.get('method')}: {problem}, {ATTEMPTS} попытки")

    @staticmethod
    def _retry_after(resp: httpx.Response) -> float:
        """Пауза из Retry-After (в секундах), но не больше 5 с: иначе лимит попыток гаснет."""
        try:
            return min(float(resp.headers.get("retry-after", "")), 5.0)
        except ValueError:
            return 0.0

    def _check(self, resp):
        if resp.status_code == 404 and self.session:
            raise _SessionExpired
        if resp.status_code in (401, 403):
            raise McpError(f"токен отклонён (HTTP {resp.status_code})")
        if resp.status_code >= 400:
            raise McpError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        self.session = resp.headers.get("mcp-session-id", self.session)
        return resp

    def _throttle(self):
        wait = self.pause - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()


def read_message(resp: httpx.Response, rid: int) -> dict:
    """Ответ JSON-RPC из обычного JSON или из SSE (берётся data: с нужным id)."""
    if "text/event-stream" not in resp.headers.get("content-type", ""):
        try:
            return resp.json()
        except ValueError:
            raise McpError(f"ответ MCP не JSON: {resp.text[:200]}") from None
    for line in resp.text.splitlines():
        if line.startswith("data:"):
            try:
                msg = json.loads(line[5:])
            except json.JSONDecodeError:
                continue
            if msg.get("id") == rid:
                return msg
    raise McpError(f"в SSE-ответе нет сообщения с id={rid}")


def parse_result(tool: str, result: dict):
    """JSON из result.content[]; isError превращается в McpError."""
    texts = [c.get("text", "") for c in result.get("content", []) if c.get("type") == "text"]
    if result.get("isError"):
        raise McpError(f"{tool}: {' '.join(texts)[:300]}")
    if "structuredContent" in result:
        return result["structuredContent"]
    parsed = []
    for text in texts:
        try:
            parsed.append(json.loads(text))
        except json.JSONDecodeError:
            parsed.append(text)
    return parsed[0] if len(parsed) == 1 else parsed
