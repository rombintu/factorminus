"""Конфигурация из окружения и `.env`. Секреты в repr и логах маскируются.

TLS: certifi + `certs/russian_trusted_root_ca.pem` из пакета — Russian Trusted Root CA
НУЦ Минцифры (источник: Госуслуги, SHA-256 `ROOT_CA_SHA256`, действует до 27.02.2032).
"""

from __future__ import annotations

import hashlib
import os
import re
import ssl
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path
from urllib.parse import urlparse

import certifi

DEFAULT_MCP_URL = "https://invest-public-api.tbank.ru/mcp"
DB_FILENAME = "fm.sqlite"
ALLOWED_MCP_HOST_SUFFIX = "tbank.ru"
# Серверы T-Invest и ISS присылают цепочку до Sub CA сами: в пакете нужен только корневой.
ROOT_CA_SHA256 = "d26d2d0231b7c39f92cc738512ba54103519e4405d68b5bd703e9788ca8ecf31"
_TOKEN_RE = re.compile(r"^[\x21-\x7e]+$")


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _find_repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").exists():
            return parent
    return Path.cwd()


def repo_root(env: Mapping[str, str] | None = None) -> Path:
    """Корень проекта: `FM_HOME`, иначе каталог с `pyproject.toml` над пакетом.

    При обычной (не editable) установке, например в Docker-образе, `pyproject.toml` рядом
    с пакетом нет, поэтому корень задаётся явно.
    """
    env = os.environ if env is None else env
    home = _clean(env.get("FM_HOME"))
    return Path(home).resolve() if home else _find_repo_root()


def data_dir(env: Mapping[str, str] | None = None, root: Path | None = None) -> Path:
    """Каталог данных времени выполнения: SQLite, кассеты record, отчёты проверок.

    `FM_DATA_DIR` (относительный путь — от корня), иначе `<корень>/data`. Файлы из git
    (`universe.yaml` и другие конфиги) читаются из `CONFIG_DIR`, а не отсюда: в контейнере
    это разные места, и том с данными не закрывает конфигурацию из образа.
    """
    env = os.environ if env is None else env
    root = repo_root(env) if root is None else root
    value = _clean(env.get("FM_DATA_DIR"))
    if not value:
        return root / "data"
    path = Path(value)
    return path if path.is_absolute() else root / path


REPO_ROOT = repo_root()
DATA_DIR = data_dir(root=REPO_ROOT)
# Конфигурация из git (только чтение): universe.yaml, позже groups.yaml и другие.
CONFIG_DIR = REPO_ROOT / "data"


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


@dataclass(frozen=True)
class Settings:
    token: str | None = field(repr=False)
    mcp_url: str = DEFAULT_MCP_URL
    insecure_ssl: bool = False
    db_path: Path = DATA_DIR / DB_FILENAME
    data_dir: Path = DATA_DIR

    def __repr__(self) -> str:
        return (
            f"Settings(token={mask_secret(self.token)}, mcp_url={self.mcp_url!r}, "
            f"insecure_ssl={self.insecure_ssl}, "
            f"db_path={str(self.db_path)!r}, data_dir={str(self.data_dir)!r})"
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

    def ssl_verify(self) -> ssl.SSLContext | bool:
        """Значение для `httpx.Client(verify=...)`: `tls_context()` или False при отладке."""
        if self.insecure_ssl:
            if os.environ.get("PYTEST_CURRENT_TEST") or "pytest" in sys.modules:
                raise ConfigError("TINVEST_INSECURE_SSL=1 запрещён в тестах")
            print(
                "ВНИМАНИЕ: TINVEST_INSECURE_SSL=1, проверка TLS-сертификата отключена. "
                "Только для локальной отладки.",
                file=sys.stderr,
            )
            return False
        return tls_context()


def tls_context() -> ssl.SSLContext:
    """certifi + корневой сертификат Минцифры из пакета; подмена файла — ConfigError."""
    pem = (files("factorminus") / "certs/russian_trusted_root_ca.pem").read_text("ascii")
    try:
        der = ssl.PEM_cert_to_DER_cert(pem)
    except ValueError as e:
        raise ConfigError("Russian Trusted Root CA: файл в пакете не PEM-сертификат") from e
    if hashlib.sha256(der).hexdigest() != ROOT_CA_SHA256:
        raise ConfigError("Russian Trusted Root CA: отпечаток не совпадает, файл подменён")
    ctx = ssl.create_default_context(cafile=certifi.where())
    ctx.load_verify_locations(cadata=pem)
    return ctx


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


def load_settings(env: Mapping[str, str] | None = None, env_file: Path | None = None) -> Settings:
    env = os.environ if env is None else env
    # Корень — из того же env (FM_HOME), что и остальные переменные: от него считаются .env,
    # FM_DATA_DIR и относительный FM_DB_PATH.
    root = repo_root(env)
    dotenv = _read_dotenv(env_file if env_file is not None else root / ".env")

    def get(key: str) -> str | None:
        value = _clean(env.get(key))
        return value if value is not None else _clean(dotenv.get(key))

    # FM_HOME и FM_DATA_DIR берутся только из окружения: от них зависит, где искать .env.
    rw = data_dir(env, root=root)
    db = get("FM_DB_PATH")
    if db:
        db_path = Path(db)
        if not db_path.is_absolute():
            db_path = root / db_path
    else:
        db_path = rw / DB_FILENAME
    return Settings(
        token=get("TINVEST_TOKEN"),
        mcp_url=_check_mcp_url(get("TINVEST_MCP_URL") or DEFAULT_MCP_URL),
        insecure_ssl=get("TINVEST_INSECURE_SSL") == "1",
        db_path=db_path,
        data_dir=rw,
    )
