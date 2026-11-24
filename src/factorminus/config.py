"""Конфигурация из окружения и `.env`. Секреты в repr и логах маскируются."""

from __future__ import annotations

import os
import re
import ssl
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

DEFAULT_MCP_URL = "https://invest-public-api.tbank.ru/mcp"
DEFAULT_DB_PATH = "data/fm.sqlite"
ALLOWED_MCP_HOST_SUFFIX = "tbank.ru"
_TOKEN_RE = re.compile(r"^[\x21-\x7e]+$")


def _find_repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").exists():
            return parent
    return Path.cwd()


REPO_ROOT = _find_repo_root()


class ConfigError(Exception):
    """Ошибка конфигурации: сообщение показывается пользователю без трейсбека."""


def mask_secret(value: str | None) -> str:
    if not value:
        return "<не задан>"
    return "t.***"


def _read_dotenv(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        out[key.strip()] = value
    return out


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


@dataclass(frozen=True)
class Settings:
    token: str | None = field(repr=False)
    mcp_url: str = DEFAULT_MCP_URL
    ca_bundle: str | None = None
    insecure_ssl: bool = False
    db_path: Path = Path(DEFAULT_DB_PATH)

    def __repr__(self) -> str:
        return (
            f"Settings(token={mask_secret(self.token)}, mcp_url={self.mcp_url!r}, "
            f"ca_bundle={self.ca_bundle!r}, insecure_ssl={self.insecure_ssl}, "
            f"db_path={str(self.db_path)!r})"
        )

    __str__ = __repr__

    @property
    def token_status(self) -> str:
        return "задан" if self.token else "не задан"

    def require_token(self) -> str:
        if not self.token:
            raise ConfigError("Токен не найден: задайте TINVEST_TOKEN в .env или в окружении")
        if not _TOKEN_RE.match(self.token):
            raise ConfigError(
                "TINVEST_TOKEN содержит недопустимые символы (пробелы, переводы строк)"
            )
        return self.token

    def verify(self) -> bool | str:
        """Значение для `httpx.Client(verify=...)`."""
        if self.insecure_ssl:
            if os.environ.get("PYTEST_CURRENT_TEST") or "pytest" in sys.modules:
                raise ConfigError("TINVEST_INSECURE_SSL=1 запрещён в тестах")
            print(
                "ВНИМАНИЕ: TINVEST_INSECURE_SSL=1, проверка TLS-сертификата отключена. "
                "Только для локальной отладки.",
                file=sys.stderr,
            )
            return False
        return self.ca_bundle or True

    def ssl_verify(self) -> ssl.SSLContext | bool:
        """Значение для `httpx.Client(verify=...)`: контекст с CA-бандлом или системный."""
        verify = self.verify()
        if isinstance(verify, str):
            if not Path(verify).is_file():
                raise ConfigError(f"TINVEST_CA_BUNDLE: файл не найден: {verify}")
            return ssl.create_default_context(cafile=verify)
        return verify


def _check_mcp_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ConfigError("TINVEST_MCP_URL должен начинаться с https://")
    host = (parsed.hostname or "").lower()
    if host != ALLOWED_MCP_HOST_SUFFIX and not host.endswith("." + ALLOWED_MCP_HOST_SUFFIX):
        raise ConfigError(
            f"TINVEST_MCP_URL: хост {host!r} не из домена {ALLOWED_MCP_HOST_SUFFIX}, "
            "токен туда не отправляется"
        )
    return url


def _resolve(path: str | None) -> str | None:
    if path is None or Path(path).is_absolute():
        return path
    return str(REPO_ROOT / path)


def load_settings(env: Mapping[str, str] | None = None, env_file: Path | None = None) -> Settings:
    env = os.environ if env is None else env
    dotenv = _read_dotenv(env_file if env_file is not None else REPO_ROOT / ".env")

    def get(key: str) -> str | None:
        value = _clean(env.get(key))
        return value if value is not None else _clean(dotenv.get(key))

    db = get("FM_DB_PATH") or DEFAULT_DB_PATH
    db_path = Path(db)
    if not db_path.is_absolute():
        db_path = REPO_ROOT / db_path
    return Settings(
        token=get("TINVEST_TOKEN"),
        mcp_url=_check_mcp_url(get("TINVEST_MCP_URL") or DEFAULT_MCP_URL),
        ca_bundle=_resolve(get("TINVEST_CA_BUNDLE")),
        insecure_ssl=get("TINVEST_INSECURE_SSL") == "1",
        db_path=db_path,
    )
