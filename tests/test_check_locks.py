from scripts_loader import SCRIPTS, load_script

cl = load_script("check_locks")
REQ = SCRIPTS.parent / "requirements"


def test_same_pins_ok():
    a = "numpy==2.5.5 \\\n    --hash=sha256:aa\ntorch==2.15.0 ; sys_platform != 'linux'\n"
    b = "numpy==2.5.5\ntorch==2.15.0+cpu ; sys_platform == 'linux'\nlaya==0.5.1\n"
    assert cl.mismatches(a, b) == []


def test_version_drift_caught():
    assert cl.mismatches("PyYAML==6.0.4\n", "pyyaml==6.0.3\n") == ["pyyaml: 6.0.4 != 6.0.3"]


def test_committed_dev_and_ml_agree():
    assert cl.main([str(REQ / "dev.txt"), str(REQ / "ml.txt")]) == 0


def test_committed_locks_agree_pairwise(capsys):
    files = [str(REQ / f"{n}.txt") for n in ("base", "dev", "ml")]
    assert cl.main(files) == 0
    out = capsys.readouterr().out
    for pair in ("base.txt и dev.txt", "base.txt и ml.txt", "dev.txt и ml.txt"):
        assert pair in out


def test_base_dev_drift_caught(tmp_path, capsys):
    """Образ runtime собран из base.txt, тесты идут на dev.txt: версии обязаны совпадать."""
    (tmp_path / "base.txt").write_text("numpy==2.5.4 \\\n    --hash=sha256:aa\nhttpx==0.28.1\n")
    (tmp_path / "dev.txt").write_text("numpy==2.5.5\nhttpx==0.28.1\npytest==9.0.0\n")
    (tmp_path / "ml.txt").write_text("numpy==2.5.4\nhttpx==0.28.1\n")
    files = [str(tmp_path / f"{n}.txt") for n in ("base", "dev", "ml")]
    assert cl.main(files) == 1
    out = capsys.readouterr().out
    assert "base.txt / dev.txt: numpy: 2.5.4 != 2.5.5" in out
    assert "dev.txt / ml.txt: numpy: 2.5.5 != 2.5.4" in out
    assert "base.txt / ml.txt" not in out


def test_single_file_is_usage_error():
    assert cl.main([str(REQ / "dev.txt")]) == 2


def test_build_requires_from_pyproject(capsys):
    assert cl.main(["--build-requires"]) == 0
    assert capsys.readouterr().out.startswith("setuptools")
