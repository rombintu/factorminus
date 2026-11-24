from scripts_loader import load_script

cs = load_script("ci_summary")

JUNIT = """<?xml version="1.0" encoding="utf-8"?>
<testsuites name="pytest tests"><testsuite name="pytest" errors="1" failures="2" skipped="8"
 tests="290" time="5.1"></testsuite></testsuites>"""
COVERAGE = '<?xml version="1.0" ?><coverage line-rate="0.9141" lines-valid="1560"></coverage>'


def build(tmp_path, junit=True, coverage=True):
    b = tmp_path / "build"
    (b / "ci").mkdir(parents=True)
    if junit:
        (b / "junit.xml").write_text(JUNIT)
    if coverage:
        (b / "coverage.xml").write_text(COVERAGE)
    return b


def test_tests_and_coverage(tmp_path):
    md = cs.render(build(tmp_path))
    assert "| passed | skipped | failed |" in md
    assert "| 279 | 8 | 3 |" in md  # 290 - 8 - 2 - 1; ошибки считаются как упавшие
    assert "Покрытие: **91.4%**" in md


def test_sections_from_files_in_order(tmp_path):
    b = build(tmp_path)
    (b / "ci" / "40-image.md").write_text("### Образ\n\nРазмер: 239 МБ\n")
    (b / "ci" / "20-hygiene.md").write_text("### Гигиена\n\n✅ ок\n")
    (b / "ci" / "build-runtime.txt").write_text("95\n")
    md = cs.render(b)
    assert md.index("### Гигиена") < md.index("### Образ")
    assert "| runtime | 95 с |" in md


def test_missing_inputs_are_reported_not_crash(tmp_path):
    md = cs.render(build(tmp_path, junit=False, coverage=False))
    assert "нет данных" in md


def test_main_appends_to_step_summary(tmp_path, monkeypatch):
    out = tmp_path / "summary.md"
    out.write_text("before\n")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(out))
    assert cs.main(["--build", str(build(tmp_path))]) == 0
    text = out.read_text()
    assert text.startswith("before\n") and "Сводка прогона" in text
