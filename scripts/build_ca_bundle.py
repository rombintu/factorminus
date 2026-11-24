#!/usr/bin/env python3
"""CA-бандл для T-Invest и ISS: сертификаты certifi + российские из `certs/`.

Каждый файл `certs/*.pem` сверяется по SHA-256 с зашитым отпечатком. Неизвестный файл,
подменённый сертификат или отсутствие корневого — ошибка: бандл не пишется.

Отпечаток корневого «Russian Trusted Root CA» сверен с официальными файлами Госуслуг.
Промежуточные «Russian Trusted Sub CA» подписаны этим корневым (`openssl verify`).

    python scripts/build_ca_bundle.py --out data/ca/ru-bundle.pem
"""

from __future__ import annotations

import argparse
import hashlib
import re
import ssl
import sys
from pathlib import Path

ROOT_FILE = "russian_trusted_root_ca.pem"
PINNED = {
    ROOT_FILE: "d26d2d0231b7c39f92cc738512ba54103519e4405d68b5bd703e9788ca8ecf31",
    "russian_trusted_sub_ca_2027.pem": (
        "bbbde2103e790b999ec62bd03cf625a5a2e7c316e10afe6a490eedead8b3fd9b"
    ),
    "russian_trusted_sub_ca_2029.pem": (
        "2155785036c900dbb5f1bb2a1569c80c55595bd6bf94867a29bbddbc7d88a3f2"
    ),
}
_PEM_RE = re.compile(r"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----", re.S)
DEFAULT_CERTS = Path(__file__).resolve().parents[1] / "certs"


class BundleError(Exception):
    pass


def _fingerprint(pem: str) -> str:
    try:
        der = ssl.PEM_cert_to_DER_cert(pem)
    except ValueError as e:
        raise BundleError(f"не PEM-сертификат: {e}") from None
    return hashlib.sha256(der).hexdigest()


def verify_certs(certs_dir: Path) -> list[str]:
    """Проверить `certs/*.pem` по отпечаткам; вернуть PEM в порядке имён файлов."""
    files = sorted(certs_dir.glob("*.pem"))
    names = {f.name for f in files}
    if ROOT_FILE not in names:
        raise BundleError(f"в {certs_dir} нет корневого сертификата {ROOT_FILE}")
    out = []
    for f in files:
        expected = PINNED.get(f.name)
        if expected is None:
            raise BundleError(f"{f.name}: файла нет в списке зашитых отпечатков")
        blocks = _PEM_RE.findall(f.read_text(encoding="ascii", errors="replace"))
        if len(blocks) != 1:
            raise BundleError(f"{f.name}: должен быть ровно один сертификат, найдено {len(blocks)}")
        actual = _fingerprint(blocks[0])
        if actual != expected:
            raise BundleError(
                f"{f.name}: SHA-256 {actual} не совпадает с зашитым {expected}. "
                "Сертификат подменён или устарел: сверьте его с Госуслугами."
            )
        out.append(blocks[0])
    return out


def build_bundle(certs_dir: Path, out: Path, certifi_path: str | None = None) -> int:
    """Записать бандл certifi + российские сертификаты; вернуть число сертификатов."""
    extra = verify_certs(Path(certs_dir))
    if certifi_path is None:
        import certifi

        certifi_path = certifi.where()
    base = Path(certifi_path).read_text(encoding="ascii")
    text = base.rstrip("\n") + "\n\n" + "\n".join(extra) + "\n"
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".tmp")
    tmp.write_text(text, encoding="ascii")
    tmp.replace(out)
    return len(_PEM_RE.findall(text))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--certs", type=Path, default=DEFAULT_CERTS)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        n = build_bundle(args.certs, args.out)
    except BundleError as e:
        print(f"Ошибка: {e}", file=sys.stderr)
        return 1
    print(f"{args.out}: {n} сертификатов (certifi + {len(PINNED)} из {args.certs.name}/)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
