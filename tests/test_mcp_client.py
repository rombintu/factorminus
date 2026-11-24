import json
import logging

import httpx
import pytest

from factorminus.config import ConfigError, Settings
from factorminus.mcp.client import McpClient, RateLimiter
from factorminus.mcp.errors import (
    CassetteMissError,
    ForbiddenToolError,
    McpToolError,
    McpTransportError,
)

TOKEN = "t.FAKE-TOKEN-must-not-leak"


def settings(**kw) -> Settings:
    base = dict(token=TOKEN, mcp_url="https://mcp.test/mcp")
    base.update(kw)
    return Settings(**base)


class FakeServer:
    """Минимальный MCP-сервер на MockTransport. Сценарии задаются через атрибуты."""

    def __init__(self):
        self.requests: list[httpx.Request] = []
        self.session_counter = 0
        self.valid_sessions: set[str] = set()
        self.tool_results: dict[str, dict] = {}
        self.queue: list[httpx.Response] = []  # ответы, которые вернуть до обычной обработки
        self.sse = False
        self.sse_noise = False

    @property
    def transport(self):
        return httpx.MockTransport(self.handle)

    def bodies(self):
        return [json.loads(r.content) for r in self.requests]

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        body = json.loads(request.content)
        if self.queue and body.get("method") == "tools/call":
            return self.queue.pop(0)
        method = body.get("method")
        if method == "initialize":
            self.session_counter += 1
            sid = f"sess-{self.session_counter}"
            self.valid_sessions.add(sid)
            return self._reply(
                body["id"],
                {"protocolVersion": "2025-03-26", "capabilities": {}, "serverInfo": {"name": "f"}},
                headers={"Mcp-Session-Id": sid},
            )
        if method == "notifications/initialized":
            return httpx.Response(202)
        if request.headers.get("Mcp-Session-Id") not in self.valid_sessions:
            return httpx.Response(404, json={"error": "session not found"})
        if method == "tools/list":
            tools = [{"name": n} for n in ["invest_get_share", "invest_create_order"]]
            return self._reply(body["id"], {"tools": tools})
        if method == "tools/call":
            name = body["params"]["name"]
            result = self.tool_results.get(
                name, {"content": [{"type": "text", "text": json.dumps({"ok": name})}]}
            )
            return self._reply(body["id"], result)
        return httpx.Response(400, json={"error": "bad method"})

    def _reply(self, rid, result, headers=None, error=None):
        msg = {"jsonrpc": "2.0", "id": rid}
        if error:
            msg["error"] = error
        else:
            msg["result"] = result
        headers = dict(headers or {})
        if self.sse:
            events = []
            if self.sse_noise:
                note = {"jsonrpc": "2.0", "method": "notifications/progress", "params": {}}
                other = {"jsonrpc": "2.0", "id": 99999, "result": {"content": []}}
                events.append("event: message\ndata: " + json.dumps(note))
                events.append("data: " + json.dumps(other))
            events.append("event: message\nid: 1\ndata: " + json.dumps(msg))
            text = "\n\n".join(events) + "\n\n"
            headers["Content-Type"] = "text/event-stream"
            return httpx.Response(200, text=text, headers=headers)
        return httpx.Response(200, json=msg, headers=headers)


def make(server, **kw):
    sleeps = []
    kw.setdefault("sleep", sleeps.append)
    client = McpClient(settings(), transport=server.transport, **kw)
    return client, sleeps


def test_handshake_and_session_header():
    server = FakeServer()
    client, _ = make(server)
    assert client.call_tool("invest_get_share", {"instrumentId": "SYN_A"}) == {
        "ok": "invest_get_share"
    }
    methods = [b.get("method") for b in server.bodies()]
    assert methods == ["initialize", "notifications/initialized", "tools/call"]
    init = server.bodies()[0]["params"]
    assert init["protocolVersion"] == "2025-03-26"
    assert init["clientInfo"]["name"] == "factorminus"
    assert server.requests[1].headers["Mcp-Session-Id"] == "sess-1"
    assert server.requests[2].headers["Mcp-Session-Id"] == "sess-1"
    assert server.requests[2].headers["Authorization"] == f"Bearer {TOKEN}"
    assert "text/event-stream" in server.requests[2].headers["Accept"]


def test_sse_picks_matching_id():
    server = FakeServer()
    server.sse = True
    server.sse_noise = True
    client, _ = make(server)
    assert client.call_tool("invest_get_etf", {}) == {"ok": "invest_get_etf"}


def test_non_json_text_returned_as_string():
    server = FakeServer()
    server.tool_results["invest_get_news"] = {"content": [{"type": "text", "text": "просто текст"}]}
    client, _ = make(server)
    assert client.call_tool("invest_get_news", {}) == "просто текст"


def test_is_error_raises():
    server = FakeServer()
    server.tool_results["invest_get_share"] = {
        "isError": True,
        "content": [{"type": "text", "text": "instrument not found"}],
    }
    client, _ = make(server)
    with pytest.raises(McpToolError, match="instrument not found"):
        client.call_tool("invest_get_share", {"instrumentId": "X_Y"})


def test_jsonrpc_error_raises():
    server = FakeServer()
    server.queue.append(
        httpx.Response(
            200, json={"jsonrpc": "2.0", "id": 2, "error": {"code": -32602, "message": "bad args"}}
        )
    )
    client, _ = make(server)
    with pytest.raises(McpToolError, match="bad args"):
        client.call_tool("invest_get_share", {})


def test_retry_on_429_then_success():
    server = FakeServer()
    server.queue.append(httpx.Response(429, text="too many"))
    server.queue.append(httpx.Response(503, text="unavailable"))
    client, sleeps = make(server)
    assert client.call_tool("invest_get_share", {}) == {"ok": "invest_get_share"}
    assert sleeps == [0.5, 1.0]


def test_retries_exhausted():
    server = FakeServer()
    server.queue.extend([httpx.Response(500) for _ in range(3)])
    client, _ = make(server)
    with pytest.raises(McpTransportError):
        client.call_tool("invest_get_share", {})


def test_reinitialize_on_expired_session():
    server = FakeServer()
    client, _ = make(server)
    client.call_tool("invest_get_share", {})
    server.valid_sessions.clear()  # сервер «забыл» сессию
    assert client.call_tool("invest_get_share", {}) == {"ok": "invest_get_share"}
    methods = [b.get("method") for b in server.bodies()]
    assert methods.count("initialize") == 2
    assert server.requests[-1].headers["Mcp-Session-Id"] == "sess-2"


def test_forbidden_tool_sends_nothing():
    server = FakeServer()
    client, _ = make(server)
    with pytest.raises(ForbiddenToolError):
        client.call_tool("invest_create_order", {"quantity": 1})
    assert server.requests == []


def test_list_tools():
    server = FakeServer()
    client, _ = make(server)
    assert client.list_tools() == ["invest_get_share", "invest_create_order"]


def test_record_then_replay_without_network(tmp_path):
    server = FakeServer()
    with McpClient(
        settings(), transport=server.transport, mode="record", cassette_dir=tmp_path
    ) as client:
        client.call_tool("invest_get_share", {"instrumentId": "SYN_A"})
        client.list_tools()
    assert len(list(tmp_path.rglob("*.json"))) == 2

    # replay: без токена и без транспорта, сеть отключена guard-ом в conftest
    replay = McpClient(Settings(token=None), mode="replay", cassette_dir=tmp_path)
    assert replay.call_tool("invest_get_share", {"instrumentId": "SYN_A"}) == {
        "ok": "invest_get_share"
    }
    assert replay.list_tools() == ["invest_get_share", "invest_create_order"]
    with pytest.raises(CassetteMissError):
        replay.call_tool("invest_get_share", {"instrumentId": "SYN_B"})
    with pytest.raises(ForbiddenToolError):
        replay.call_tool("invest_create_order", {})


def test_live_requires_token():
    with pytest.raises(ConfigError, match="TINVEST_TOKEN"):
        McpClient(Settings(token=None), transport=FakeServer().transport)


def test_token_not_in_logs(caplog):
    caplog.set_level(logging.DEBUG)
    server = FakeServer()
    client, _ = make(server)
    client.call_tool("invest_get_share", {"instrumentId": "SYN_A"})
    client.list_tools()
    assert caplog.records, "клиент должен логировать вызовы"
    assert "invest_get_share" in caplog.text
    assert TOKEN not in caplog.text
    assert "FAKE-TOKEN" not in caplog.text
    assert TOKEN not in repr(client)


def test_insecure_refused_under_pytest():
    with pytest.raises(ConfigError, match="TINVEST_INSECURE_SSL"):
        McpClient(settings(insecure_ssl=True), transport=FakeServer().transport)


def test_rate_limiter_waits_when_window_full():
    now = [0.0]
    sleeps = []

    def sleep(s):
        sleeps.append(s)
        now[0] += s

    limiter = RateLimiter(3, clock=lambda: now[0], sleep=sleep)
    for _ in range(3):
        limiter.acquire()
        now[0] += 1.0
    assert sleeps == []
    limiter.acquire()  # 4-й в окне 60 с ждёт, пока выйдет первый
    assert sleeps == [pytest.approx(57.0)]


def test_transport_error_message_scrubbed():
    def boom(request):
        raise httpx.ConnectError(f"failed with Bearer {TOKEN}")

    client = McpClient(settings(), transport=httpx.MockTransport(boom), sleep=lambda s: None)
    with pytest.raises(McpTransportError) as ei:
        client.call_tool("invest_get_share", {})
    assert TOKEN not in str(ei.value)
    assert "FAKE-TOKEN" not in str(ei.value)


def test_server_error_text_scrubbed_and_capped():
    server = FakeServer()
    server.tool_results["invest_get_share"] = {
        "isError": True,
        "content": [{"type": "text", "text": f"echo Bearer {TOKEN} " + "x" * 5000}],
    }
    client, _ = make(server)
    with pytest.raises(McpToolError) as ei:
        client.call_tool("invest_get_share", {})
    assert TOKEN not in str(ei.value)
    assert len(str(ei.value)) < 1000


def test_cassette_rejects_bad_tool_name(tmp_path):
    from factorminus.mcp.cassette import Cassette

    with pytest.raises(ValueError):
        Cassette(tmp_path).path("../evil", {})


def test_default_cassette_dir_anchored_to_repo():
    from factorminus.config import REPO_ROOT

    client = McpClient(Settings(token=None), mode="replay")
    assert client.cassette.root == REPO_ROOT / "data" / "cassettes"


def test_retry_after_respected_and_capped():
    server = FakeServer()
    server.queue.append(httpx.Response(429, headers={"Retry-After": "3"}))
    server.queue.append(httpx.Response(429, headers={"Retry-After": "9999"}))
    client, sleeps = make(server)
    client.call_tool("invest_get_share", {})
    assert sleeps == [3.0, 30.0]
