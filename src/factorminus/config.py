"""Настройки: токен, адрес MCP, путь к базе, TLS-контекст."""

import hashlib
import os
import ssl
from pathlib import Path
from urllib.parse import urlsplit

import certifi

SANDBOX_URL = "https://sandbox-invest-public-api.tbank.ru/mcp"
CERT = Path(__file__).parent / "certs" / "russian_trusted_root_ca.pem"
# SHA-256 от DER: Russian Trusted Root CA НУЦ Минцифры, сверен с Госуслугами 24.11.2026.
CERT_SHA256 = "d26d2d0231b7c39f92cc738512ba54103519e4405d68b5bd703e9788ca8ecf31"


class ConfigError(Exception):
    """Ожидаемая ошибка настройки: CLI печатает её без трейсбека."""


def read_env(path: Path = Path(".env")) -> dict[str, str]:
    """Простой парсер .env: строки KEY=VALUE, комментарии и пустые строки пропускаются."""
    if not path.exists():
        return {}
    out = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            out[key.strip()] = value.strip().strip("'\"")
    return out


def get(name: str, default: str | None = None) -> str | None:
    return os.environ.get(name) or read_env().get(name) or default


def token() -> str:
    value = get("TINVEST_TOKEN")
    if not value:
        raise ConfigError("задайте TINVEST_TOKEN в .env (токен песочницы T-Invest)")
    return value


def check_url(url: str) -> str:
    """Токен уходит только по https на *.tbank.ru."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    if parts.scheme != "https" or not (host == "tbank.ru" or host.endswith(".tbank.ru")):
        raise ConfigError(f"TINVEST_MCP_URL должен быть https://*.tbank.ru, получено: {url}")
    return url


def mcp_url() -> str:
    return check_url(get("TINVEST_MCP_URL", SANDBOX_URL))


def db_path() -> Path:
    return Path(get("FM_DB", "data/fm.sqlite"))


def tls_context(cert: Path = CERT, sha256: str = CERT_SHA256) -> ssl.SSLContext:
    """certifi плюс корневой сертификат НУЦ Минцифры; отпечаток сверяется при каждом создании."""
    pem = cert.read_text()
    if hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem)).hexdigest() != sha256:
        raise ConfigError(f"отпечаток сертификата {cert.name} не совпадает, файл подменён")
    ctx = ssl.create_default_context(cafile=certifi.where())
    ctx.load_verify_locations(cadata=pem)
    return ctx
