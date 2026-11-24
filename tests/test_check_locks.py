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


def test_build_requires_from_pyproject(capsys):
    assert cl.main(["--build-requires"]) == 0
    assert capsys.readouterr().out.startswith("setuptools")
