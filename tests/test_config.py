import ssl
from pathlib import Path

import pytest

from factorminus.config import (
    DATA_DIR,
    DB_FILENAME,
    DEFAULT_MCP_URL,
    ROOT_CA_SHA256,
    ConfigError,
    Settings,
    load_settings,
    mask_secret,
    tls_context,
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
    assert s.db_path == s.data_dir / DB_FILENAME


def test_default_mcp_url_is_sandbox():
    """Все 9 инструментов проходят на песочнице (ревью PR #1, п. 3): боевой токен не нужен."""
    assert DEFAULT_MCP_URL == "https://sandbox-invest-public-api.tbank.ru/mcp"


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


def _ca_names(ctx: ssl.SSLContext) -> set[str]:
    return {dict(x[0] for x in c["subject"]).get("commonName") for c in ctx.get_ca_certs()}


def test_tls_context_from_package_pem():
    ctx = tls_context()
    assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname
    assert "Russian Trusted Root CA" in _ca_names(ctx)
    assert len(ctx.get_ca_certs()) > 100  # certifi + корневой Минцифры


def _other_cert() -> str:
    import certifi

    text = certifi.contents()
    start = text.index("-----BEGIN CERTIFICATE-----")
    end = text.index("-----END CERTIFICATE-----", start) + len("-----END CERTIFICATE-----")
    return text[start:end] + "\n"


@pytest.mark.parametrize("pem", [_other_cert(), "not a certificate\n"])
def test_tls_context_substituted_pem_refused(tmp_path, monkeypatch, pem):
    from factorminus import config

    (tmp_path / "certs").mkdir()
    (tmp_path / "certs" / "russian_trusted_root_ca.pem").write_text(pem, encoding="ascii")
    monkeypatch.setattr(config, "files", lambda _pkg: tmp_path)
    with pytest.raises(ConfigError, match="Russian Trusted Root CA"):
        tls_context()


def test_root_ca_sha256_pinned():
    assert ROOT_CA_SHA256 == "d26d2d0231b7c39f92cc738512ba54103519e4405d68b5bd703e9788ca8ecf31"


def test_ssl_verify_default_is_tls_context(tmp_path):
    verify = load_settings(env={}, env_file=tmp_path / "x").ssl_verify()
    assert isinstance(verify, ssl.SSLContext)
    assert "Russian Trusted Root CA" in _ca_names(verify)


def test_insecure_forbidden_under_pytest(tmp_path):
    s = load_settings(env={"TINVEST_INSECURE_SSL": "1"}, env_file=tmp_path / "x")
    assert s.insecure_ssl is True
    with pytest.raises(ConfigError, match="TINVEST_INSECURE_SSL"):
        s.ssl_verify()


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
        s.ssl_verify()


# --- FM_HOME / FM_DATA_DIR ---


def test_repo_root_from_fm_home(tmp_path):
    from factorminus.config import repo_root

    assert repo_root({"FM_HOME": str(tmp_path)}) == tmp_path


def test_repo_root_default_is_project_with_pyproject():
    from factorminus.config import repo_root

    assert (repo_root({}) / "pyproject.toml").is_file()


def test_data_dir_default_is_root_data(tmp_path):
    from factorminus.config import data_dir

    assert data_dir({}, root=tmp_path) == tmp_path / "data"


def test_data_dir_absolute_and_relative(tmp_path):
    from factorminus.config import data_dir

    assert data_dir({"FM_DATA_DIR": "/var/lib/fm"}, root=tmp_path) == Path("/var/lib/fm")
    assert data_dir({"FM_DATA_DIR": "runtime"}, root=tmp_path) == tmp_path / "runtime"


def test_db_path_defaults_to_data_dir(tmp_path):
    s = load_settings(env={"FM_DATA_DIR": str(tmp_path / "rw")}, env_file=tmp_path / "x")
    assert s.db_path == tmp_path / "rw" / "fm.sqlite"
    assert s.data_dir == tmp_path / "rw"


def test_fm_db_path_wins_over_data_dir(tmp_path):
    s = load_settings(
        env={"FM_DATA_DIR": str(tmp_path / "rw"), "FM_DB_PATH": str(tmp_path / "x.sqlite")},
        env_file=tmp_path / "x",
    )
    assert s.db_path == tmp_path / "x.sqlite"


def test_without_variables_paths_unchanged(tmp_path):
    from factorminus.config import REPO_ROOT

    s = load_settings(env={}, env_file=tmp_path / "x")
    assert s.db_path == REPO_ROOT / "data" / "fm.sqlite"
    assert s.data_dir == REPO_ROOT / "data"


def test_module_constants_follow_environment(tmp_path):
    """Как в контейнере: пакет вне репозитория, корень и данные из переменных."""
    import subprocess
    import sys

    home, rw = tmp_path / "app", tmp_path / "rw"
    code = (
        "from factorminus import config, cli\n"
        "from factorminus.mcp import client\n"
        "print(config.REPO_ROOT, config.DATA_DIR, config.CONFIG_DIR, sep='\\n')\n"
        "print(cli.UNIVERSE_PATH, cli.SYNTH_DIR, client.DEFAULT_CASSETTE_DIR, sep='\\n')\n"
        "print(config.load_settings().db_path)\n"
    )
    env = {"PATH": "/usr/bin:/bin", "FM_HOME": str(home), "FM_DATA_DIR": str(rw)}
    out = subprocess.run(
        [sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True
    ).stdout.split("\n")
    assert out[:7] == [
        str(home),
        str(rw),
        str(home / "data"),
        str(home / "data" / "universe.yaml"),
        str(home / "tests" / "fixtures" / "synthetic"),
        str(rw / "cassettes"),
        str(rw / "fm.sqlite"),
    ]


def test_load_settings_uses_fm_home_from_env(tmp_path):
    """Корень берётся из переданного env, а не из модульного REPO_ROOT (ревью 1.5, п. 6.2)."""
    home = tmp_path / "home"
    home.mkdir()
    (home / ".env").write_text("TINVEST_TOKEN=t.fake-home\n", encoding="utf-8")
    s = load_settings(env={"FM_HOME": str(home)})
    assert s.token == "t.fake-home"  # .env из FM_HOME
    assert s.data_dir == home / "data"
    assert s.db_path == home / "data" / "fm.sqlite"

    s = load_settings(
        env={
            "FM_HOME": str(home),
            "FM_DATA_DIR": "rw",
            "FM_DB_PATH": "db/x.sqlite",
        }
    )
    assert s.data_dir == home / "rw"
    assert s.db_path == home / "db" / "x.sqlite"


def test_settings_defaults_follow_data_dir():
    """Settings() без путей не зависит от текущей папки (ревью 1.5, п. 6.3)."""
    s = Settings(token=None)
    assert s.data_dir == DATA_DIR
    assert s.db_path == DATA_DIR / DB_FILENAME


@pytest.mark.git  # .env.example есть в checkout, в образе test его нет
def test_env_example_has_no_db_path():
    """FM_DB_PATH в .env.example увёл бы базу из FM_DATA_DIR (ревью 1.5, п. 6.1)."""
    from factorminus.config import REPO_ROOT

    example = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    assert not any(line.startswith("FM_DB_PATH=") for line in example.splitlines())
    assert "# FM_DB_PATH=" in example
