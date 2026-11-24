import socket

import pytest


def pytest_addoption(parser):
    parser.addoption("--live", action="store_true", help="запускать live-тесты с реальным MCP")
    parser.addoption(
        "--ml", action="store_true", help="запускать ML-тесты (laya, образ runtime-ml)"
    )


OPT_IN = {
    "live": "live-тест: запустите make test-live",
    "ml": "ML-тест: запустите make test-ml (нужны laya и веса, образ runtime-ml)",
}


def pytest_collection_modifyitems(config, items):
    for marker, reason in OPT_IN.items():
        if config.getoption(f"--{marker}"):
            continue
        skip = pytest.mark.skip(reason=reason)
        for item in items:
            if marker in item.keywords:
                item.add_marker(skip)


@pytest.fixture(autouse=True)
def _no_network(request, monkeypatch):
    """Любая попытка открыть сокет в обычных тестах — ошибка.

    ML-тесты сеть тоже не получают: веса laya должны лежать в образе заранее.
    """
    if "live" in request.keywords:
        return

    def guard(*args, **kwargs):
        raise RuntimeError("network disabled in tests")

    monkeypatch.setattr(socket.socket, "connect", guard)
    monkeypatch.setattr(socket.socket, "connect_ex", guard)
    monkeypatch.setattr(socket, "create_connection", guard)
