import socket

import pytest


def pytest_addoption(parser):
    parser.addoption("--live", action="store_true", help="запускать live-тесты с реальным MCP")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--live"):
        return
    skip = pytest.mark.skip(reason="live-тест: запустите make test-live")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def _no_network(request, monkeypatch):
    """Любая попытка открыть сокет в обычных тестах — ошибка."""
    if "live" in request.keywords:
        return

    def guard(*args, **kwargs):
        raise RuntimeError("network disabled in tests")

    monkeypatch.setattr(socket.socket, "connect", guard)
    monkeypatch.setattr(socket.socket, "connect_ex", guard)
    monkeypatch.setattr(socket, "create_connection", guard)
