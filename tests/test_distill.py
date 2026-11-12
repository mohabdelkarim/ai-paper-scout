"""Unit tests for distill pipeline helpers."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import distill


def test_parse_json_safely_strips_fences_and_noise() -> None:
    raw = 'Here you go:\n```json\n{"tldr": "ok", "tags": ["a"]}\n```\nthanks'
    data = distill._parse_json_safely(raw)
    assert data == {"tldr": "ok", "tags": ["a"]}


def test_parse_json_safely_returns_none_on_garbage() -> None:
    assert distill._parse_json_safely("not json at all") is None


def test_normalise_tags_hyphenates_and_limits() -> None:
    tags = distill._normalise_tags(
        ["Large Language Models", "AI_Safety", "ok!", "", "x", "y", "z"]
    )
    assert tags == [
        "large-language-models",
        "ai-safety",
        "ok",
        "x",
        "y",
    ]


def test_ranking_catalogue_stays_under_groq_tpm_budget() -> None:
    """Groq free tier TPM is 8000; ranking must leave headroom for response."""
    papers = [
        {
            "title": f"Paper title number {i} with extra words for realism " * 2,
            "authors": "A. Author, B. Researcher, C. Scientist, D. Engineer",
            "abstract": ("This abstract discusses methods and results. " * 40).strip(),
            "url": f"http://arxiv.org/abs/2601.{i:05d}",
            "published": "2026-01-01",
        }
        for i in range(60)
    ]
    catalogue = distill.build_paper_catalogue(papers)
    prompt = distill.PAPER_RANKING_PROMPT.format(papers=catalogue)
    # rough token estimate: ~4 chars/token for English technical text
    estimated_tokens = len(prompt) // 4
    assert estimated_tokens < 7000, estimated_tokens


def test_is_retryable_api_error_rejects_oversized_requests() -> None:
    err = RuntimeError(
        "LLM API HTTP 413: Request too large for model, please reduce your message size"
    )
    assert distill._is_retryable_api_error(err) is False


def test_is_retryable_api_error_allows_transient_rate_limits() -> None:
    err = RuntimeError("LLM API HTTP 429: rate_limit_exceeded, try again later")
    assert distill._is_retryable_api_error(err) is True


def test_is_retryable_api_error_rejects_missing_model() -> None:
    err = RuntimeError(
        'LLM API HTTP 404: {"error":{"message":"The model does not exist","code":"model_not_found"}}'
    )
    assert distill._is_retryable_api_error(err) is False


def test_chat_completions_url_joins_base() -> None:
    assert distill._chat_completions_url().endswith("/chat/completions")


def test_retry_wait_seconds_parses_provider_hint() -> None:
    err = RuntimeError("Rate limit. Please try again in 11.3925s. Need more tokens?")
    assert distill._retry_wait_seconds(err, 0) == 12.1425


def test_is_usable_distillation_rejects_placeholders() -> None:
    bad = {
        "tldr": "Research on Some Paper.",
        "key_innovation": "Technical details under review.",
        "why_it_matters": "Potential impact on AI/ML field.",
        "tags": ["research", "ai", "ml"],
    }
    assert distill.is_usable_distillation(bad) is False

    good = {
        "tldr": "A concrete summary of the method.",
        "key_innovation": "A novel attention routing scheme.",
        "why_it_matters": "Cuts inference cost for production LLMs.",
        "tags": ["attention", "efficiency"],
    }
    assert distill.is_usable_distillation(good) is True


def test_pick_readme_theme_tag_skips_generic_tags() -> None:
    tags = ["research", "ai", "ml", "robotics", "vision"]
    assert distill.pick_readme_theme_tag(tags) == "robotics"


def test_build_health_payload_marks_degraded_ranking() -> None:
    metrics = [
        {
            "step": "llm_ranking",
            "latency_s": 1.0,
            "sla_threshold_s": 35.0,
            "sla_ok": True,
            "retries": 0,
            "tokens_used": None,
            "error": None,
            "ranking_fallback": True,
        }
    ]
    payload = distill.build_health_payload(
        date(2026, 11, 12),
        metrics,
        pipeline_ok=True,
        ranking_fallback=True,
        distill_failures=1,
        papers_written=3,
    )
    assert payload["pipeline_success"] is True
    assert payload["quality"]["ranking_fallback"] is True
    assert payload["quality"]["degraded"] is True
    assert payload["quality"]["distill_failures"] == 1
    assert payload["quality"]["papers_written"] == 3


def test_update_readme_index_inserts_new_report(tmp_path: Path, monkeypatch) -> None:
    readme = tmp_path / "README.md"
    readme.write_text(
        "# Demo\n\n<!-- REPORT_INDEX -->\n| |\n|---|\n|[May 30 · robotics](reports/2026-05-30.md)|\n"
        "<!-- REPORT_INDEX -->\n",
        encoding="utf-8",
    )
    reports = tmp_path / "reports"
    reports.mkdir()
    report = reports / "2026-11-12.md"
    report.write_text(
        "# Report\n\n## 1. Title\n\n**Tags:** robotics, vision\n\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(distill, "README_PATH", readme)
    monkeypatch.setattr(distill, "REPORTS_DIR", reports)

    assert distill.update_readme_index(date(2026, 11, 12), report) is True
    text = readme.read_text(encoding="utf-8")
    assert "reports/2026-11-12.md" in text
    assert "Nov 12" in text


def test_selection_rationale_marks_degraded_runs() -> None:
    text = distill.format_selection_rationale(
        "Fallback: ranking failed.",
        ranking_fallback=True,
    )
    assert "Degraded" in text
    assert "not a curated ranking" in text.lower() or "newest" in text.lower()
