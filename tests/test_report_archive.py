"""Unit tests for report archive parsing and HTML safety."""

from __future__ import annotations

from pathlib import Path

import report_archive


SAMPLE_REPORT = """# AI Paper Scout Report — 2026-11-12

## Selection Rationale

Real ranking rationale.

---

## 1. Safe <script>Title</script>

**Authors:** A. Author

**TL;DR:** Short summary with <b>html</b>.

**Key Innovation:** A new thing.

**Why It Matters:** Helps engineers ship.

**Tags:** robotics, vision

**Link:** [http://arxiv.org/abs/2611.00001v1](http://arxiv.org/abs/2611.00001v1)
"""


def test_parse_report_extracts_full_fields(tmp_path: Path) -> None:
    path = tmp_path / "2026-11-12.md"
    path.write_text(SAMPLE_REPORT, encoding="utf-8")
    health_dir = tmp_path / "health"
    health_dir.mkdir()
    # point parser at temp reports dir
    report_archive.REPORTS_DIR = tmp_path
    report_archive.HEALTH_DIR = health_dir

    parsed = report_archive.parse_report(path)
    assert parsed["date"] == "2026-11-12"
    assert len(parsed["papers"]) == 1
    paper = parsed["papers"][0]
    assert paper["title"].startswith("Safe")
    assert paper["tldr"].startswith("Short summary")
    assert paper["key_innovation"] == "A new thing."
    assert paper["why_it_matters"] == "Helps engineers ship."
    assert paper["authors"] == "A. Author"
    assert paper["url"] == "http://arxiv.org/abs/2611.00001v1"


def test_html_escapes_untrusted_content(tmp_path: Path) -> None:
    path = tmp_path / "2026-11-12.md"
    path.write_text(SAMPLE_REPORT, encoding="utf-8")
    report_archive.REPORTS_DIR = tmp_path
    report_archive.HEALTH_DIR = tmp_path / "health"
    report_archive.HEALTH_DIR.mkdir()

    out = tmp_path / "archive.html"
    reports = report_archive.load_all_reports()
    report_archive.generate_html(reports, out)
    html = out.read_text(encoding="utf-8")
    assert "<script>Title</script>" not in html
    assert "&lt;script&gt;Title&lt;/script&gt;" in html
    assert "<b>html</b>" not in html
    assert "A new thing." in html
    assert "Helps engineers ship." in html
