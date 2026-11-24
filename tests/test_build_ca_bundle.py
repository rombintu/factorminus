import shutil
import ssl

import pytest

from scripts_loader import SCRIPTS, load_script

ca = load_script("build_ca_bundle")
CERTS = SCRIPTS.parent / "certs"
ROOT_SHA = (
    "D2:6D:2D:02:31:B7:C3:9F:92:CC:73:85:12:BA:54:10:"
    "35:19:E4:40:5D:68:B5:BD:70:3E:97:88:CA:8E:CF:31"
)


@pytest.fixture
def certs(tmp_path):
    d = tmp_path / "certs"
    shutil.copytree(CERTS, d)
    return d


def test_root_fingerprint_pinned_as_in_spec():
    assert ca.PINNED["russian_trusted_root_ca.pem"] == ROOT_SHA.replace(":", "").lower()


def test_committed_certs_pass(tmp_path):
    out = tmp_path / "bundle.pem"
    n = ca.build_bundle(CERTS, out)
    text = out.read_text()
    assert n == text.count("BEGIN CERTIFICATE") > 100  # certifi + 3 российских
    ctx = ssl.create_default_context(cafile=str(out))
    subjects = {dict(x[0] for x in c["subject"]).get("commonName") for c in ctx.get_ca_certs()}
    assert "Russian Trusted Root CA" in subjects


def test_substituted_root_is_rejected(certs, tmp_path):
    # другой валидный сертификат под именем корневого
    shutil.copy(certs / "russian_trusted_sub_ca_2029.pem", certs / "russian_trusted_root_ca.pem")
    with pytest.raises(ca.BundleError, match="russian_trusted_root_ca.pem"):
        ca.build_bundle(certs, tmp_path / "b.pem")
    assert not (tmp_path / "b.pem").exists()


def test_extra_unpinned_cert_is_rejected(certs, tmp_path):
    shutil.copy(certs / "russian_trusted_sub_ca_2029.pem", certs / "extra.pem")
    with pytest.raises(ca.BundleError, match="extra.pem"):
        ca.build_bundle(certs, tmp_path / "b.pem")


def test_missing_root_is_rejected(certs, tmp_path):
    (certs / "russian_trusted_root_ca.pem").unlink()
    with pytest.raises(ca.BundleError, match="нет"):
        ca.build_bundle(certs, tmp_path / "b.pem")


def test_two_certs_in_one_file_rejected(certs, tmp_path):
    root = certs / "russian_trusted_root_ca.pem"
    root.write_text(root.read_text() + (certs / "russian_trusted_sub_ca_2029.pem").read_text())
    with pytest.raises(ca.BundleError, match="ровно один"):
        ca.build_bundle(certs, tmp_path / "b.pem")


def test_cli_exit_code(certs, tmp_path, capsys):
    (certs / "russian_trusted_root_ca.pem").write_text("garbage")
    assert ca.main(["--certs", str(certs), "--out", str(tmp_path / "b.pem")]) == 1
    assert "Ошибка" in capsys.readouterr().err
