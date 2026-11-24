"""CLI: понятные ошибки без трейсбека, без сети."""

import subprocess

import pytest
from typer.testing import CliRunner

from factorminus import cli
from factorminus.config import REPO_ROOT, Settings

runner = CliRunner()


@pytest.fixture
def no_token(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "_settings", lambda: Settings(token=None, db_path=tmp_path / "x.db"))


def test_mcp_check_without_token(no_token):
    r = runner.invoke(cli.app, ["mcp", "check"])
    assert r.exit_code == 2
    assert "задайте TINVEST_TOKEN" in r.output
    assert "Traceback" not in r.output


def test_iss_network_error_is_friendly(no_token, monkeypatch):
    import httpx

    import factorminus.iss as iss

    def down(*a, **kw):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(iss, "fetch_index_weights", down)
    r = runner.invoke(cli.app, ["iss", "weights", "--index", "IMOEX"])
    assert r.exit_code == 2, r.output
    assert "Ошибка" in r.output
    assert r.exception is None or isinstance(r.exception, SystemExit)


def test_unknown_only_id(no_token):
    r = runner.invoke(cli.app, ["ingest", "--only", "NOPE_TQBR", "--mode", "replay"])
    assert r.exit_code == 2
    assert "NOPE_TQBR" in r.output


def test_invalid_mode(no_token):
    r = runner.invoke(cli.app, ["ingest", "--mode", "turbo"])
    assert r.exit_code == 2
    assert "mode" in r.output


def test_db_init_and_stats(no_token, tmp_path):
    db = tmp_path / "t.sqlite"
    assert runner.invoke(cli.app, ["db", "init", "--db", str(db)]).exit_code == 0
    r = runner.invoke(cli.app, ["db", "stats", "--db", str(db)])
    assert r.exit_code == 0 and "candles" in r.output


def test_synth_generate_refuses_foreign_dir(tmp_path):
    (tmp_path / "keep.txt").write_text("x", encoding="utf-8")
    r = runner.invoke(cli.app, ["synth", "generate", "--out", str(tmp_path)])
    assert r.exit_code == 2
    assert (tmp_path / "keep.txt").exists()


@pytest.mark.git
def test_only_universe_yaml_tracked_under_data():
    out = subprocess.run(
        ["git", "ls-files", "data", ".env"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    assert out == ["data/universe.yaml"]
