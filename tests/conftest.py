import shutil
import socket
from pathlib import Path

import pytest

# Тесты с маркером git читают `git ls-files`. В образе `test` нет ни git, ни .git:
# там они пропускаются, а в CI и локально выполняются.
IN_GIT_CHECKOUT = (
    shutil.which("git") is not None and (Path(__file__).resolve().parents[1] / ".git").exists()
)


def pytest_addoption(parser):
    parser.addoption("--live", action="store_true", help="запускать live-тесты с реальным MCP")
    parser.addoption(
        "--ml", action="store_true", help="запускать ML-тесты (laya, образ runtime-ml)"
    )
    parser.addoption(
        "--ml-heavy",
        action="store_true",
        help="запускать ML-тесты, которым нужно больше 4 ГБ памяти (все модели laya сразу)",
    )


OPT_IN = {
    "live": "live-тест: запустите make test-live",
    "ml": "ML-тест: запустите make test-ml (нужны laya и веса, образ runtime-ml)",
    "ml_heavy": "ML-тест с preload=True: нужно больше 4 ГБ памяти, запускается в CI (--ml-heavy)",
}


def pytest_collection_modifyitems(config, items):
    if not IN_GIT_CHECKOUT:
        skip_git = pytest.mark.skip(reason="нужен git-репозиторий (в образе test его нет)")
        for item in items:
            if "git" in item.keywords:
                item.add_marker(skip_git)
    for marker, reason in OPT_IN.items():
        if config.getoption(f"--{marker.replace('_', '-')}"):
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
