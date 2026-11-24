import pytest

from scripts_loader import load_script

rn = load_script("release_notes")

STAGES = """# Журнал этапов

| Этап | Ветка | PR | Тег | Статус | Отчёт | Ключевые метрики |
|---|---|---|---|---|---|---|
| 1 | `stage-1` | #1 | `v0.1.0` | принят | [отчёт](reports/STAGE_1_REPORT.md) | 246 тестов |
| 1.5 | `infra` | #2 | `v0.1.5` | на ревью | [отчёт](reports/STAGE_1_5_REPORT.md) | CI |
"""
REPORT = """# Отчёт

Вступление.

## Что сделано

- пункт один;
- пункт два.

### Подраздел

Текст подраздела.

## Как проверено

Не должно попасть.
"""


@pytest.fixture
def docs(tmp_path):
    d = tmp_path / "docs"
    (d / "reports").mkdir(parents=True)
    (d / "STAGES.md").write_text(STAGES)
    (d / "reports" / "STAGE_1_5_REPORT.md").write_text(REPORT)
    return d


def test_stage_for_tag(docs):
    row = rn.stage_for_tag(docs / "STAGES.md", "v0.1.5")
    assert row["stage"] == "1.5"
    assert row["report"] == "reports/STAGE_1_5_REPORT.md"


def test_unknown_tag_is_error(docs):
    with pytest.raises(rn.ReleaseError, match="v9.9.9"):
        rn.stage_for_tag(docs / "STAGES.md", "v9.9.9")


def test_done_section_extracted_with_subsections(docs):
    text = rn.done_section(docs / "reports" / "STAGE_1_5_REPORT.md")
    assert "пункт два" in text and "Текст подраздела" in text
    assert "Не должно попасть" not in text


def test_notes_have_images_and_ci_link(docs):
    md = rn.render(
        docs, "v0.1.5", repo="rombintu/factorminus", run_url="https://github.com/r/actions/runs/1"
    )
    assert md.startswith("## Этап 1.5")
    assert "ghcr.io/rombintu/factorminus:0.1.5" in md
    assert "ghcr.io/rombintu/factorminus:0.1.5-ml" in md
    assert "https://github.com/r/actions/runs/1" in md
    assert "пункт один" in md


def test_bad_tag_format(docs):
    with pytest.raises(rn.ReleaseError, match="vX.Y.Z"):
        rn.render(docs, "stage-1", repo="r/r", run_url="")
