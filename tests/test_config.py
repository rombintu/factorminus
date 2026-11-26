import pytest

from factorminus import config


@pytest.mark.parametrize(
    "url",
    [
        "http://sandbox-invest-public-api.tbank.ru/mcp",
        "https://evil.example.com/mcp",
        "https://tbank.ru.evil.com/mcp",
        "https://eviltbank.ru/mcp",
    ],
)
def test_foreign_or_plain_url_rejected(monkeypatch, url):
    monkeypatch.setenv("TINVEST_MCP_URL", url)
    with pytest.raises(config.ConfigError):
        config.mcp_url()


def test_default_url_is_sandbox():
    assert config.mcp_url() == "https://sandbox-invest-public-api.tbank.ru/mcp"


def test_token_from_dotenv_and_missing(tmp_path):
    with pytest.raises(config.ConfigError, match="TINVEST_TOKEN"):
        config.token()
    (tmp_path / ".env").write_text("# comment\nTINVEST_TOKEN='abc'\n")
    assert config.token() == "abc"


def test_tls_context_checks_fingerprint(tmp_path):
    assert config.tls_context() is not None
    fake = tmp_path / "ca.pem"
    fake.write_text(config.CERT.read_text())
    with pytest.raises(config.ConfigError, match="отпечаток"):
        config.tls_context(fake, sha256="0" * 64)
