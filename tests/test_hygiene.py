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


def test_large_file_caught_unless_allowed(universe, monkeypatch):
    big = b"0" * (hy.MAX_BYTES + 1)
    files = make(universe, {"blob.bin": big, "tests/cases/big.csv": big})
    monkeypatch.setitem(hy.LARGE_ALLOWED, "tests/cases/big.csv", "пример исключения")
    got = rules(hy.check(universe, files + ["data/universe.yaml"]))
    assert ("blob.bin", "large-file") in got
    assert ("tests/cases/big.csv", "large-file") not in got


def test_real_tickers_in_fixtures(universe):
    files = make(
        universe,
        {
            "tests/fixtures/synthetic/candles.csv": "SYN_A,1\nSBER_TQBR,250.1\n",
            "tests/fixtures/synthetic/prices.json": '{"ticker": "TMOS", "close": 7.1}',
            "tests/fixtures/synthetic/ok.json": '{"ticker": "SYN_TMOS", "id": "SYNIDX_INDEX"}',
            "tests/fixtures/x/readme.txt": "SBER_TQBR",  # не файл данных, но в fixtures
            "tests/test_live.py": 'ids = ["SBER_TQBR"]\n',  # код тестов — не проверяется
        },
    )
    got = rules(hy.check(universe, files + ["data/universe.yaml"]))
    assert got == {
        ("tests/fixtures/synthetic/candles.csv", "real-ticker-in-data"),
        ("tests/fixtures/synthetic/prices.json", "real-ticker-in-data"),
        ("tests/fixtures/x/readme.txt", "real-ticker-in-data"),
    }


def test_ticker_exception_list(universe, monkeypatch):
    files = make(universe, {"tests/fixtures/synthetic/m.json": '"как TMOS"'})
    monkeypatch.setitem(hy.TICKER_EXCEPTIONS, "tests/fixtures/synthetic/m.json", "пример без цен")
    assert hy.check(universe, files + ["data/universe.yaml"]) == []


# Случаи, которые гигиена этапа 1.5 пропускала (ревью 1.5, п. 1)
MCP_CANDLES = (
    '{"candles": [{"time": "2024-01-03T07:00:00Z", "close": {"units": "271", "nano": 5e8}}],'
    ' "instrumentUid": "e6123145-9665-43e0-8413-cd61b8aa9b13", "ticker": "SBER_TQBR"}'
)


@pytest.mark.parametrize(
    ("path", "content", "rule"),
    [
        ("docs/real_prices.csv", "2024-01-03,SBER_TQBR,271.5\n", "data-file-outside-allowlist"),
        ("analysis/candles.csv", "SBER,271.5\n", "data-file-outside-allowlist"),
        ("tests/cassettes/invest_get_candles.json", MCP_CANDLES, "data-file-outside-allowlist"),
        ("tests/cassettes/invest_get_candles.json", MCP_CANDLES, "mcp-response"),
        ("data/fm.sqlite.bak", "x", "data-not-yaml"),
        ("tests/fixtures/synthetic/x.csv", "SBER 271\n", "real-ticker-in-data"),
    ],
)
def test_review_cases_caught(universe, path, content, rule):
    files = make(universe, {path: content}) + ["data/universe.yaml"]
    assert (path, rule) in rules(hy.check(universe, files))


@pytest.mark.parametrize(
    "path",
    [
        "x.tsv",
        "a/b.jsonl",
        "out.parquet",
        "out.feather",
        "report.xlsx",
        "m.pkl",
        "m.pickle",
        "arr.npz",
        "arr.npy",
        "local.db",
        "tests/fixtures/real/prices.json",  # вне synthetic
        "docs/contract.json",  # не в docs/contract/
    ],
)
def test_data_extensions_outside_allowlist(universe, path):
    files = make(universe, {path: "1"}) + ["data/universe.yaml"]
    assert (path, "data-file-outside-allowlist") in rules(hy.check(universe, files))


@pytest.mark.parametrize(
    "path",
    [
        "tests/fixtures/synthetic/a.csv",
        "tests/cases/sma/case.json",
        "docs/contract/examples/x.json",
        "src/factorminus/schema.yaml",  # yaml не файл данных
    ],
)
def test_data_files_allowed_in_allowlist(universe, path):
    files = make(universe, {path: "SYN_A,1\n"}) + ["data/universe.yaml"]
    assert hy.check(universe, files) == []


def test_data_file_exception_with_reason(universe, monkeypatch):
    files = make(universe, {"bench/results.json": "{}"}) + ["data/universe.yaml"]
    monkeypatch.setitem(hy.DATA_FILE_EXCEPTIONS, "bench/results.json", "только время, без цен")
    assert hy.check(universe, files) == []


@pytest.mark.parametrize("folder", ["tests/fixtures/synthetic", "tests/cases/x", "docs/contract"])
def test_real_tickers_checked_in_all_data_dirs(universe, folder):
    path = f"{folder}/q.json"
    files = make(universe, {path: '{"id": "TMOS"}'}) + ["data/universe.yaml"]
    assert (path, "real-ticker-in-data") in rules(hy.check(universe, files))


@pytest.mark.parametrize(
    "content",
    [
        '{"figi": "BBG004730N88"}',
        '{"assetUid": "40d89385-a03a-4659-bf4e-d3ecba011782"}',
        '{"positionUid": "41eb2102-5333-4713-bf15-72b204c4bf7b"}',
        '{"brandUid": 5}',
        'instrumentUid: "e6123145"\n"instrumentUid": "e6123145"',
        '{"candles": [], "x": {"close": 1}}',
    ],
)
def test_mcp_keys_caught_in_non_code_files(universe, content):
    files = make(universe, {"notes/dump.txt": content}) + ["data/universe.yaml"]
    assert ("notes/dump.txt", "mcp-response") in rules(hy.check(universe, files))


def test_mcp_keys_allowed_in_code_and_synthetic(universe):
    files = make(
        universe,
        {
            "src/factorminus/mcp/parse.py": 'u = x["instrumentUid"]; c = r["candles"]["close"]\n',
            "tests/test_parse.py": 'RESP = {"figi": "BBG004730N88"}\n',
            "docs/MCP.md": '`"assetUid"`, `"candles"` и `"close"`\n',
            # синтетика повторяет форму ответа MCP, значения начинаются с syn-
            "tests/fixtures/synthetic/instruments.json": (
                '[{"assetUid": "syn-asset-a", "brandUid": "syn-brand-a", "positionUid": "syn-p"},'
                ' {"assetUid": "syn-asset-b", "brandUid": null}]'
            ),
            "docs/contract/examples/n.json": '{"data_as_of": {"candles": "2025-12-01"}}',
        },
    )
    assert hy.check(universe, files + ["data/universe.yaml"]) == []


@pytest.mark.parametrize(
    "path", ["certs/russian_trusted_sub_ca_2029.pem", "src/factorminus/certs/extra.pem", "x.crt"]
)
def test_certificate_outside_package_path_caught(universe, path):
    files = make(universe, {path: "-----BEGIN CERTIFICATE-----\n"}) + ["data/universe.yaml"]
    assert (path, "certificate-path") in rules(hy.check(universe, files))


def test_package_root_ca_allowed(universe):
    files = make(universe, {hy.ROOT_CA_PATH: "-----BEGIN CERTIFICATE-----\n"})
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
