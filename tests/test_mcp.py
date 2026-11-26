import httpx
import pytest
from conftest import TOKEN, FakeServer, client

from factorminus import mcp
from factorminus.mcp import McpError

SHARE = {"instrument": {"ticker": "SBER", "classCode": "TQBR"}}


def tools(**extra):
    return {"invest_get_share": lambda a: SHARE, **extra}


@pytest.mark.parametrize("sse", [False, True])
def test_handshake_then_call(sse):
    server = FakeServer(tools(), sse=sse)
    assert client(server).call("invest_get_share", {"instrumentId": "SBER_TQBR"}) == SHARE
    assert server.methods() == ["initialize", "notifications/initialized", "tools/call"]
    headers, _ = server.requests[-1]
    assert headers["mcp-session-id"] == "s1"
    assert headers["authorization"] == f"Bearer {TOKEN}"


def test_is_error_becomes_exception():
    server = FakeServer(tools(invest_get_bond=lambda a: Exception("instrument not found")))
    with pytest.raises(McpError, match="not found"):
        client(server).call("invest_get_bond", {})


def test_retry_on_429():
    server = FakeServer(tools())
    server.fail = [429, 503]
    assert client(server).call("invest_get_share", {}) == SHARE


def test_gives_up_after_three_attempts():
    server = FakeServer(tools())
    server.fail = [500, 500, 500]
    with pytest.raises(McpError, match="500"):
        client(server).call("invest_get_share", {})


def test_reinitializes_once_when_session_expired():
    server = FakeServer(tools())
    mcp = client(server)
    mcp.call("invest_get_share", {})
    server.fail = [404]
    assert mcp.call("invest_get_share", {}) == SHARE
    assert server.methods().count("initialize") == 2


@pytest.mark.parametrize("tool", ["invest_create_order", "invest_get_portfolio", "anything"])
def test_tool_outside_whitelist_rejected_before_network(tool):
    def no_network(request):
        raise AssertionError("запрос не должен уходить")

    mcp = client(no_network)
    with pytest.raises(McpError, match="белом списке"):
        mcp.call(tool, {})


def test_token_not_in_verbose_log_or_repr(capsys):
    mcp = client(FakeServer(tools()), verbose=True)
    mcp.call("invest_get_share", {"instrumentId": "SBER_TQBR"})
    err = capsys.readouterr().err
    assert "invest_get_share" in err and "SBER_TQBR" in err
    assert TOKEN not in err and TOKEN not in repr(mcp)


def test_network_error_is_friendly():
    def down(request):
        raise httpx.ConnectError("boom")

    with pytest.raises(McpError, match="сеть"):
        client(down).call("invest_get_share", {})


def test_context_manager_closes_client():
    server = FakeServer(tools())
    with client(server) as mcp:
        assert not mcp.http.is_closed
        mcp.call("invest_get_share", {})
    assert mcp.http.is_closed


def test_retry_after_on_429_is_respected(monkeypatch):
    sleeps = []
    monkeypatch.setattr(mcp.time, "sleep", sleeps.append)
    server = FakeServer(tools())
    server.fail = [(429, {"Retry-After": "2"}), (429, {"Retry-After": "bogus"})]
    assert client(server).call("invest_get_share", {}) == SHARE
    assert 2.0 in sleeps  # bogus-заголовок даёт 0 и не падает
