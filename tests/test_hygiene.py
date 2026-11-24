import subprocess

import pytest

from scripts_loader import SCRIPTS, load_script

hy = load_script("check_repo_hygiene")
REPO = SCRIPTS.parent
FAKE_TOKEN = "t." + "Ab3_-" * 17 + "x"  # 88 символов, как настоящий; собирается в рантайме


def make(root, files):
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content if isinstance(content, bytes) else content.encode())
    return sorted(files)


def rules(violations):
    return {(v.path, v.rule) for v in violations}


@pytest.fixture
def universe(tmp_path):
    make(tmp_path, {"data/universe.yaml": "- id: SBER_TQBR\n  kind: share\n- id: TMOS_TQBR\n"})
    return tmp_path


def test_fake_token_shape():
    assert len(FAKE_TOKEN) == 88


@pytest.mark.parametrize(
    "path",
    [
        ".env",
        ".env.local",
        "sub/.env",
        "data/fm.sqlite",
        "x.sqlite-journal",
        "data/ingest.log",
        "data/cassettes/a/b.json",
        "data/ca/ru-bundle.pem",
        "data/universe_resolved.json",
    ],
)
def test_forbidden_paths_caught(universe, path):
    files = make(universe, {path: "x"}) + ["data/universe.yaml"]
    assert (path, "forbidden-path") in rules(hy.check(universe, files))


def test_env_example_allowed(universe):
    files = make(universe, {".env.example": "TINVEST_TOKEN=\n"}) + ["data/universe.yaml"]
    assert hy.check(universe, files) == []


def test_only_yaml_in_data(universe):
    files = make(universe, {"data/notes.txt": "x", "data/sub/x.yaml": "a: 1"})
    got = rules(hy.check(universe, files + ["data/universe.yaml"]))
    assert ("data/notes.txt", "data-not-yaml") in got
    assert ("data/sub/x.yaml", "data-not-yaml") in got


def test_token_caught_and_masked_not(universe):
    files = make(
        universe,
        {
            "src/a.py": f'TOKEN = "{FAKE_TOKEN}"\n',
            "src/b.py": 'masked = "t.***"\nfake = "t.fake-env"\nshort = "t.super-secret-value"\n',
        },
    )
    got = hy.check(universe, files + ["data/universe.yaml"])
    assert rules(got) == {("src/a.py", "token")}
    assert FAKE_TOKEN not in str(got)  # нарушение не печатает сам токен


def test_large_file_caught_unless_allowed(universe):
    big = b"0" * (hy.MAX_BYTES + 1)
    files = make(universe, {"blob.bin": big, "tests/fixtures/synthetic/candles.csv": big})
    got = rules(hy.check(universe, files + ["data/universe.yaml"]))
    assert ("blob.bin", "large-file") in got
    assert ("tests/fixtures/synthetic/candles.csv", "large-file") not in got


def test_real_tickers_in_fixtures(universe):
    files = make(
        universe,
        {
            "tests/fixtures/x/candles.csv": "SYN_A,1\nSBER_TQBR,250.1\n",
            "tests/fixtures/x/prices.json": '{"ticker": "TMOS", "close": 7.1}',
            "tests/fixtures/x/ok.json": '{"ticker": "SYN_TMOS", "id": "SYNIDX_INDEX"}',
            "tests/test_live.py": 'ids = ["SBER_TQBR"]\n',  # вне fixtures — не проверяется
        },
    )
    got = rules(hy.check(universe, files + ["data/universe.yaml"]))
    assert got == {
        ("tests/fixtures/x/candles.csv", "real-ticker-in-fixture"),
        ("tests/fixtures/x/prices.json", "real-ticker-in-fixture"),
    }


def test_fixture_exception_list(universe, monkeypatch):
    files = make(universe, {"tests/fixtures/x/m.json": '"как TMOS"'})
    monkeypatch.setitem(hy.FIXTURE_EXCEPTIONS, "tests/fixtures/x/m.json", "пример без цен")
    assert hy.check(universe, files + ["data/universe.yaml"]) == []


@pytest.mark.git
def test_current_repository_is_clean():
    files = hy.git_files(REPO)
    assert "data/universe.yaml" in files
    assert hy.check(REPO, files) == []


@pytest.mark.git
def test_main_exit_codes(universe, capsys):
    make(universe, {".env": "x"})
    subprocess.run(["git", "init", "-q"], cwd=universe, check=True)
    subprocess.run(["git", "add", "-f", ".env", "data/universe.yaml"], cwd=universe, check=True)
    summary = universe / "build" / "hygiene.md"
    assert hy.main(["--root", str(universe), "--summary", str(summary)]) == 1
    assert "forbidden-path" in capsys.readouterr().out
    assert "❌" in summary.read_text() and "`.env`: forbidden-path" in summary.read_text()
