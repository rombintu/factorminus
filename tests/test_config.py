import pytest

from factorminus.config import (
    DEFAULT_DB_PATH,
    DEFAULT_MCP_URL,
    ConfigError,
    load_settings,
    mask_secret,
)


@pytest.fixture
def env_file(tmp_path):
    p = tmp_path / ".env"
    p.write_text("TINVEST_TOKEN=t.fake-file\n", encoding="utf-8")
    return p


def test_env_has_priority_over_dotenv(env_file):
    s = load_settings(env={"TINVEST_TOKEN": "t.fake-env"}, env_file=env_file)
    assert s.token == "t.fake-env"


def test_dotenv_used_when_env_missing(env_file):
    s = load_settings(env={}, env_file=env_file)
    assert s.token == "t.fake-file"


def test_dotenv_quotes_export_comments(tmp_path):
    p = tmp_path / ".env"
    p.write_text(
        "# comment\nexport TINVEST_TOKEN=\"t.quoted\"\nTINVEST_MCP_URL='https://sandbox-invest-public-api.tbank.ru/mcp'\n\n",
        encoding="utf-8",
    )
    s = load_settings(env={}, env_file=p)
    assert s.token == "t.quoted"
    assert s.mcp_url == "https://sandbox-invest-public-api.tbank.ru/mcp"


def test_empty_token_is_none(tmp_path):
    p = tmp_path / ".env"
    p.write_text("TINVEST_TOKEN=\n", encoding="utf-8")
    assert load_settings(env={}, env_file=p).token is None
    assert load_settings(env={"TINVEST_TOKEN": "  "}, env_file=p).token is None


def test_missing_dotenv_is_fine(tmp_path):
    s = load_settings(env={}, env_file=tmp_path / "nope.env")
    assert s.token is None
    assert s.mcp_url == DEFAULT_MCP_URL
    assert str(s.db_path).endswith(DEFAULT_DB_PATH)


def test_require_token_error(tmp_path):
    s = load_settings(env={}, env_file=tmp_path / "nope.env")
    with pytest.raises(ConfigError, match="задайте TINVEST_TOKEN в .env"):
        s.require_token()


def test_repr_masks_token(env_file):
    s = load_settings(env={"TINVEST_TOKEN": "t.super-secret-value"}, env_file=env_file)
    for text in (repr(s), str(s)):
        assert "super-secret-value" not in text
        assert "t.***" in text


def test_mask_secret():
    assert mask_secret("t.abcdef") == "t.***"
    assert mask_secret(None) == "<не задан>"


def test_verify_default_and_ca_bundle(tmp_path):
    assert load_settings(env={}, env_file=tmp_path / "x").verify() is True
    s = load_settings(env={"TINVEST_CA_BUNDLE": "/tmp/ca.pem"}, env_file=tmp_path / "x")
    assert s.verify() == "/tmp/ca.pem"


def test_insecure_forbidden_under_pytest(tmp_path):
    s = load_settings(env={"TINVEST_INSECURE_SSL": "1"}, env_file=tmp_path / "x")
    assert s.insecure_ssl is True
    with pytest.raises(ConfigError, match="TINVEST_INSECURE_SSL"):
        s.verify()


def test_db_path_override(tmp_path):
    s = load_settings(env={"FM_DB_PATH": str(tmp_path / "a.sqlite")}, env_file=tmp_path / "x")
    assert s.db_path == tmp_path / "a.sqlite"


def test_mcp_url_must_be_https(tmp_path):
    with pytest.raises(ConfigError, match="https"):
        load_settings(
            env={"TINVEST_MCP_URL": "http://invest-public-api.tbank.ru/mcp"},
            env_file=tmp_path / "x",
        )


def test_mcp_url_foreign_host_refused(tmp_path):
    with pytest.raises(ConfigError, match="tbank.ru"):
        load_settings(env={"TINVEST_MCP_URL": "https://evil.example/mcp"}, env_file=tmp_path / "x")
    s = load_settings(
        env={"TINVEST_MCP_URL": "https://sandbox-invest-public-api.tbank.ru/mcp"},
        env_file=tmp_path / "x",
    )
    assert s.mcp_url.startswith("https://sandbox")


def test_token_with_control_chars_refused():
    from factorminus.config import Settings

    with pytest.raises(ConfigError, match="недопустимые символы"):
        Settings(token="t.bad\ntoken").require_token()


def test_insecure_refused_even_without_pytest_env(tmp_path, monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    s = load_settings(env={"TINVEST_INSECURE_SSL": "1"}, env_file=tmp_path / "x")
    with pytest.raises(ConfigError):
        s.verify()


def test_ca_bundle_must_exist(tmp_path):
    s = load_settings(
        env={"TINVEST_CA_BUNDLE": str(tmp_path / "missing.pem")}, env_file=tmp_path / "x"
    )
    with pytest.raises(ConfigError, match="TINVEST_CA_BUNDLE"):
        s.ssl_verify()


def test_relative_ca_bundle_resolved_from_repo_root(tmp_path):
    from factorminus.config import REPO_ROOT

    s = load_settings(env={"TINVEST_CA_BUNDLE": "data/ca/x.pem"}, env_file=tmp_path / "x")
    assert s.ca_bundle == str(REPO_ROOT / "data/ca/x.pem")
