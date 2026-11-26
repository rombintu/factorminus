import json

import httpx
import pytest

from factorminus.mcp import Mcp

URL = "https://sandbox-invest-public-api.tbank.ru/mcp"
TOKEN = "t.fake-test-token-0123456789"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Каждый тест в пустой папке: реальный .env и data/ недоступны."""
    monkeypatch.chdir(tmp_path)
    for name in ("TINVEST_TOKEN", "TINVEST_MCP_URL", "FM_DB"):
        monkeypatch.delenv(name, raising=False)


class FakeServer:
    """Фейковый MCP для httpx.MockTransport: tools — {имя: функция(arguments) -> ответ}."""

    def __init__(self, tools, sse=False):
        self.tools, self.sse = tools, sse
        self.requests = []  # (заголовки, тело) каждого запроса
        self.fail = []  # коды ответов, которые вернуть первыми

    def __call__(self, request):
        body = json.loads(request.content)
        self.requests.append((request.headers, body))
        if self.fail:
            return httpx.Response(self.fail.pop(0))
        if "id" not in body:
            return httpx.Response(202)
        if body["method"] == "initialize":
            return self.reply(body, {"protocolVersion": "2025-03-26"}, {"Mcp-Session-Id": "s1"})
        if body["method"] == "tools/list":
            return self.reply(body, {"tools": [{"name": n} for n in self.tools]})
        params = body["params"]
        out = self.tools[params["name"]](params["arguments"])
        if isinstance(out, Exception):
            return self.reply(
                body, {"isError": True, "content": [{"type": "text", "text": str(out)}]}
            )
        text = json.dumps(out, ensure_ascii=False)
        return self.reply(body, {"content": [{"type": "text", "text": text}]})

    def reply(self, body, result, headers=None):
        msg = json.dumps({"jsonrpc": "2.0", "id": body["id"], "result": result})
        ctype = "text/event-stream" if self.sse else "application/json"
        if self.sse:
            noise = '{"jsonrpc": "2.0", "method": "notifications/progress"}'
            msg = f"event: message\ndata: {noise}\n\nevent: message\ndata: {msg}\n\n"
        return httpx.Response(200, text=msg, headers={"content-type": ctype, **(headers or {})})

    def methods(self):
        return [b.get("method") for _, b in self.requests]


def client(server, **kw):
    return Mcp(TOKEN, URL, transport=httpx.MockTransport(server), pause=0, **kw)
