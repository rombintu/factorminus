import os
import shutil
import socket
from pathlib import Path

import pytest

# Тесты с маркером git читают `git ls-files`. В образе `test` нет ни git, ни .git:
# там они пропускаются, а в CI и локально выполняются.
IN_GIT_CHECKOUT = (
    shutil.which("git") is not None and (Path(__file__).resolve().parents[1] / ".git").exists()
)


# Синтетический набор не хранится в git: он детерминирован по seed и строится за ~0,5 с.
# Локально и в CI conftest пересобирает его перед тестами. В образе `test` каталог только
# для чтения: набор там собран при сборке образа из того же кода (стадия synth в Dockerfile).
SYNTH_DIR = Path(__file__).resolve().parent / "fixtures" / "synthetic"
SYNTH_SEED = 42


def pytest_sessionstart(session):
    # В свежем checkout нет даже tests/fixtures/: write_dataset создаст каталоги сам.
    if (SYNTH_DIR / "manifest.json").exists() and not os.access(SYNTH_DIR, os.W_OK):
        return
    from factorminus.synth.generator import generate, write_dataset

    write_dataset(generate(SYNTH_SEED), SYNTH_DIR)


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
    if not IN_GIT_CHECKOUT:
        skip_git = pytest.mark.skip(reason="нужен git-репозиторий (в образе test его нет)")
        for item in items:
            if "git" in item.keywords:
                item.add_marker(skip_git)
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
