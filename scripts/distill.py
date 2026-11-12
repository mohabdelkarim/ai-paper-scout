"""AI Paper Scout distillation pipeline.

Fetches recent arXiv papers, ranks them with an OpenAI-compatible LLM,
distills the top results into Markdown, updates the README index, and
optionally notifies via Telegram.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

import arxiv
import httpx
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)
# httpx logs full request URLs; Telegram bot tokens live in the path.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

LLM_API_KEY = os.getenv("LLM_API_KEY")
LLM_API_BASE = os.getenv("LLM_API_BASE", "https://api.groq.com/openai/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen/qwen3.8-27b")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
REPOSITORY_URL = "https://github.com/mohabdelkarim/ai-paper-scout"

REPORTS_DIR = Path(__file__).parent.parent / "reports"
HEALTH_DIR = REPORTS_DIR / "health"
README_PATH = Path(__file__).parent.parent / "README.md"

MAX_PAPERS = 60
TOP_N = 3
MAX_RETRIES = 3
RETRY_DELAY = 2.0
# Ranking prompt must stay under Groq free-tier TPM (~8000). Titles + short
# abstracts only; authors are omitted from the ranking catalogue on purpose.
RANK_ABSTRACT_LEN = 160
DISTILL_PARSE_RETRIES = 1

GENERIC_TAGS = frozenset({"research", "ai", "ml", "machine-learning", "artificial-intelligence"})
PLACEHOLDER_INNOVATION = "Technical details under review."
PLACEHOLDER_IMPACT = "Potential impact on AI/ML field."

SLA_THRESHOLDS = {
    "arxiv_fetch": 20.0,
    "llm_ranking": 35.0,
    "llm_distill": 25.0,
}

PAPER_RANKING_PROMPT = """You are an AI research analyst. Given a list of recent arXiv papers in AI/ML, select the top 3 most important ones based on:
1. Technical novelty
2. Industry relevance
3. Practical importance

Return ONLY valid JSON in this exact format (no markdown, no explanation):
{{
  "ranked_indices": [0, 1, 2],
  "reasoning": "Brief explanation of why these 3 papers were selected"
}}

The ranked_indices must be distinct indices (0-based) from the paper list below.
Paper list:
{papers}"""

PAPER_DISTILL_PROMPT = """You are an AI research analyst. Create a detailed distillation of the following arXiv paper.

Return ONLY valid JSON in this exact format (no markdown, no explanation):
{{
  "tldr": "One sentence summary accessible to a technical but non-expert audience",
  "key_innovation": "The core technical contribution or breakthrough",
  "why_it_matters": "A concrete real-world use case or application that this enables or improves — must be different from the key_innovation and focus on practical impact for engineers or products",
  "tags": ["tag1", "tag2", "tag3", "tag4", "tag5"]
}}

IMPORTANT for tags: use lowercase-hyphenated format only (e.g. \"mixture-of-experts\", \"distribution-shift\", \"ai-safety\"). No spaces, no underscores, no uppercase.

Paper title: {title}
Paper authors: {authors}
Paper abstract: {abstract}
arXiv URL: {url}"""


# ---------------------------------------------------------------------------
# Health / metrics helpers
# ---------------------------------------------------------------------------

@contextmanager
def track(name: str, metrics: list):
    """Context manager: records latency, SLA status, retries, tokens, errors."""
    start = time.perf_counter()
    entry: dict[str, Any] = {
        "step": name,
        "timestamp_utc": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
        "latency_s": None,
        "sla_threshold_s": SLA_THRESHOLDS.get(name, 15.0),
        "sla_ok": None,
        "retries": 0,
        "tokens_used": None,
        "error": None,
    }
    try:
        yield entry
    except Exception as exc:
        entry["error"] = str(exc)
        raise
    finally:
        elapsed = round(time.perf_counter() - start, 3)
        entry["latency_s"] = elapsed
        entry["sla_ok"] = elapsed <= entry["sla_threshold_s"]
        metrics.append(entry)
        if entry.get("error"):
            status = "ERROR"
        elif entry["sla_ok"]:
            status = "OK"
        else:
            status = "SLA BREACH"
        logger.info(f"[{status}] {name} — {elapsed}s (threshold {entry['sla_threshold_s']}s)")


def build_health_payload(
    today: date,
    metrics: list,
    *,
    pipeline_ok: bool,
    ranking_fallback: bool = False,
    distill_failures: int = 0,
    papers_written: int = 0,
) -> dict:
    """Build the health JSON payload for a pipeline run."""
    degraded = bool(ranking_fallback or distill_failures > 0 or papers_written < TOP_N)
    return {
        "date": today.isoformat(),
        "pipeline_success": pipeline_ok,
        "steps": metrics,
        "quality": {
            "ranking_fallback": ranking_fallback,
            "distill_failures": distill_failures,
            "papers_written": papers_written,
            "degraded": degraded,
        },
        "summary": {
            "total_steps": len(metrics),
            "sla_breaches": sum(1 for m in metrics if m.get("sla_ok") is False),
            "total_retries": sum(m.get("retries", 0) for m in metrics),
            "total_tokens": sum(m.get("tokens_used") or 0 for m in metrics),
            "total_latency_s": round(sum(m.get("latency_s") or 0 for m in metrics), 3),
            "errors": [m["error"] for m in metrics if m.get("error")],
        },
    }


def save_health_metrics(
    today: date,
    metrics: list,
    *,
    pipeline_ok: bool,
    ranking_fallback: bool = False,
    distill_failures: int = 0,
    papers_written: int = 0,
) -> Path:
    """Persist health data to reports/health/YYYY-MM-DD.json."""
    HEALTH_DIR.mkdir(parents=True, exist_ok=True)
    path = HEALTH_DIR / f"{today.isoformat()}.json"
    payload = build_health_payload(
        today,
        metrics,
        pipeline_ok=pipeline_ok,
        ranking_fallback=ranking_fallback,
        distill_failures=distill_failures,
        papers_written=papers_written,
    )
    # Atomic replace avoids a late-failed process clobbering a successful run's file.
    tmp_path = path.with_suffix(".json.tmp")
    tmp_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    tmp_path.replace(path)
    logger.info(f"Health metrics saved to {path}")
    return path


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------

def send_telegram(message: str) -> bool:
    """Send a plain-text message via Telegram Bot API."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.info("Telegram not configured, skipping notification.")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        resp = httpx.post(
            url,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message[:4000],
                "disable_web_page_preview": True,
            },
            timeout=10,
        )
        if resp.status_code == 200:
            logger.info("Telegram notification sent successfully.")
            return True
        logger.warning(f"Telegram API returned {resp.status_code}: {resp.text}")
        return False
    except Exception as e:
        logger.warning(f"Telegram notification failed: {e}")
        return False


def build_telegram_message(
    today: date,
    distilled_papers: list,
    metrics: list,
    pipeline_ok: bool,
    *,
    ranking_fallback: bool = False,
) -> str:
    breaches = [m for m in metrics if m.get("sla_ok") is False]
    total_tokens = sum(m.get("tokens_used") or 0 for m in metrics)
    total_latency = round(sum(m.get("latency_s") or 0 for m in metrics), 1)
    status_text = "Success" if pipeline_ok else "Failed"
    if pipeline_ok and ranking_fallback:
        status_text = "Degraded (ranking fallback)"

    lines = [
        "AI Paper Scout",
        f"Date: {today.isoformat()} | Status: {status_text}",
        "",
        "Top Papers",
    ]
    for i, paper in enumerate(distilled_papers, 1):
        tags = " ".join(paper.get("tags", [])[:3])
        lines += [
            "",
            f"{i}. {paper['title']}",
            f"Summary: {paper.get('tldr', 'N/A')}",
            f"Innovation: {paper.get('key_innovation', 'N/A')}",
            f"Impact: {paper.get('why_it_matters', 'N/A')}",
            f"Tags: {tags}",
            f"Link: {paper.get('url', '')}",
        ]
    lines += [
        "",
        "Pipeline Health",
        f"Latency: {total_latency}s | Tokens: {total_tokens}",
    ]
    if breaches:
        breach_info = ", ".join(f"{b['step']} ({b['latency_s']}s)" for b in breaches)
        lines.append(f"SLA breaches: {breach_info}")
    else:
        lines.append("All SLA thresholds met")
    errors = [m["error"] for m in metrics if m.get("error")]
    if errors:
        lines.append(f"Errors: {'; '.join(errors[:2])}")
    lines += ["", f"Repository: {REPOSITORY_URL}"]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def validate_env() -> None:
    if not LLM_API_KEY:
        raise EnvironmentError(
            "LLM_API_KEY is not set. Copy .env.example to .env and fill in your values."
        )


def fetch_papers(metrics: list) -> list[dict]:
    logger.info("Fetching papers from arXiv (cs.AI OR cs.LG)...")
    papers: list[dict] = []
    with track("arxiv_fetch", metrics):
        search = arxiv.Search(
            query="cat:cs.AI OR cat:cs.LG",
            max_results=MAX_PAPERS,
            sort_by=arxiv.SortCriterion.SubmittedDate,
            sort_order=arxiv.SortOrder.Descending,
        )
        client = arxiv.Client()
        for result in client.results(search):
            abstract_clean = re.sub(r"\s+", " ", result.summary).strip()
            papers.append({
                "title": result.title.strip(),
                "authors": ", ".join(a.name for a in result.authors),
                "abstract": abstract_clean,
                "url": result.entry_id,
                "published": result.published.strftime("%Y-%m-%d"),
            })
        if not papers:
            raise RuntimeError("No papers fetched from arXiv. Check network connectivity.")
        logger.info(f"Fetched {len(papers)} papers")
    return papers


def build_paper_catalogue(papers: list[dict]) -> str:
    """Compact ranking catalogue: index + title + short abstract (no authors)."""
    parts = []
    for i, paper in enumerate(papers):
        snippet = paper["abstract"][:RANK_ABSTRACT_LEN].rstrip()
        if len(paper["abstract"]) > RANK_ABSTRACT_LEN:
            snippet = snippet.rstrip(".,;:") + "..."
        parts.append(f"[{i}] {paper['title']}\n   {snippet}")
    return "\n\n".join(parts)


def _parse_json_safely(content: str) -> Optional[dict]:
    content = content.strip()
    content = re.sub(r"^```json\s*", "", content)
    content = re.sub(r"^```\s*", "", content)
    content = re.sub(r"\s*```$", "", content)
    m = re.search(r"\{[\s\S]*\}", content)
    if not m:
        return None
    try:
        return json.loads(m.group())
    except json.JSONDecodeError:
        return None


def _normalise_tags(tags: list) -> list[str]:
    result = []
    for t in tags:
        tag = str(t).strip().lower()
        tag = re.sub(r"[\s_]+", "-", tag)
        tag = re.sub(r"[^a-z0-9-]", "", tag)
        tag = re.sub(r"-+", "-", tag).strip("-")
        if tag and tag not in result:
            result.append(tag)
        if len(result) >= 5:
            break
    return result


def pick_readme_theme_tag(tags: list[str]) -> str:
    """Prefer a specific tag over generic placeholders for README labels."""
    for tag in tags:
        if tag and tag.lower() not in GENERIC_TAGS:
            return tag
    return tags[0] if tags else "AI Research"


def is_usable_distillation(data: dict) -> bool:
    """Reject known placeholder / empty distillations so they never ship."""
    tldr = str(data.get("tldr", "")).strip()
    innovation = str(data.get("key_innovation", "")).strip()
    impact = str(data.get("why_it_matters", "")).strip()
    tags = data.get("tags") or []
    if not tldr or not innovation or not impact:
        return False
    if innovation == PLACEHOLDER_INNOVATION or impact == PLACEHOLDER_IMPACT:
        return False
    if tldr.lower().startswith("research on ") and len(tldr) < 140:
        return False
    if isinstance(tags, list) and tags:
        normalised = {str(t).strip().lower().replace(" ", "-") for t in tags}
        if normalised and normalised.issubset(GENERIC_TAGS):
            return False
    return True


def _is_retryable_api_error(exc: BaseException) -> bool:
    """Return False for permanent payload / auth failures that retries cannot fix."""
    msg = str(exc).lower()
    non_retryable_markers = (
        "413",
        "request too large",
        "reduce your message size",
        "payload too large",
        "context_length_exceeded",
        "maximum context length",
        "invalid_api_key",
        "incorrect api key",
        "model_not_found",
        "does not exist or you do not have access",
        "has been decommissioned",
        "401",
        "403",
        "404",
    )
    if any(marker in msg for marker in non_retryable_markers):
        return False
    return True


def _retry_wait_seconds(exc: BaseException, attempt: int) -> float:
    """Prefer provider 'try again in Xs' hints over blind exponential backoff."""
    match = re.search(r"try again in ([0-9]+(?:\.[0-9]+)?)s", str(exc), re.IGNORECASE)
    if match:
        return float(match.group(1)) + 0.75
    return RETRY_DELAY * (2 ** attempt)


def _chat_completions_url() -> str:
    return f"{LLM_API_BASE.rstrip('/')}/chat/completions"


def _call_llm_once(
    messages: list[dict],
    temperature: float,
    max_tokens: int,
) -> tuple[str, Optional[int]]:
    """Single OpenAI-compatible chat completion via httpx (no native SDK/DLL deps)."""
    payload = {
        "model": LLM_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    headers = {
        "Authorization": f"Bearer {LLM_API_KEY}",
        "Content-Type": "application/json",
    }
    try:
        resp = httpx.post(
            _chat_completions_url(),
            json=payload,
            headers=headers,
            timeout=90.0,
        )
    except httpx.HTTPError as e:
        raise RuntimeError(f"LLM transport error: {e}") from e

    body_text = resp.text
    if resp.status_code >= 400:
        # Keep provider message, never echo Authorization header.
        raise RuntimeError(f"LLM API HTTP {resp.status_code}: {body_text[:500]}")

    try:
        data = resp.json()
    except json.JSONDecodeError as e:
        raise RuntimeError("LLM API returned non-JSON response") from e

    try:
        choice = data["choices"][0]
        message = choice["message"]
        content = message.get("content")
        finish_reason = choice.get("finish_reason")
    except (KeyError, IndexError, TypeError) as e:
        raise RuntimeError(f"LLM API response missing content: {str(data)[:300]}") from e

    if not content or not str(content).strip():
        # Reasoning models (e.g. gpt-oss) may spend the whole budget on hidden
        # reasoning and return empty content with finish_reason=length.
        raise RuntimeError(
            f"LLM returned empty content (finish_reason={finish_reason})"
        )

    tokens = None
    usage = data.get("usage") or {}
    if isinstance(usage, dict) and usage.get("total_tokens") is not None:
        try:
            tokens = int(usage["total_tokens"])
        except (TypeError, ValueError):
            tokens = None
    return str(content).strip(), tokens


def _call_llm_with_retry(
    messages: list[dict],
    temperature: float,
    max_tokens: int,
    metric_entry: Optional[dict] = None,
) -> str:
    """Call the LLM with exponential-backoff retry for transient failures only."""
    last_error: Optional[BaseException] = None
    total_retries = 0
    current_max_tokens = max_tokens
    for attempt in range(MAX_RETRIES):
        try:
            content, tokens = _call_llm_once(
                messages, temperature, current_max_tokens
            )
            if metric_entry is not None:
                if tokens is not None:
                    metric_entry["tokens_used"] = tokens
                metric_entry["retries"] = total_retries
            return content
        except RuntimeError as e:
            last_error = e
            if not _is_retryable_api_error(e):
                if metric_entry is not None:
                    metric_entry["retries"] = total_retries
                raise RuntimeError(f"LLM API call failed (non-retryable): {e}") from e
            # Give reasoning models more room on empty-content/length failures.
            if "empty content" in str(e).lower():
                current_max_tokens = max(current_max_tokens * 2, max_tokens * 2)
            total_retries += 1
            if attempt < MAX_RETRIES - 1:
                wait = _retry_wait_seconds(e, attempt)
                logger.warning(
                    f"API error (attempt {attempt + 1}/{MAX_RETRIES}): {e}. "
                    f"Retrying in {wait:.1f}s..."
                )
                time.sleep(wait)
    if metric_entry is not None:
        metric_entry["retries"] = total_retries
    raise RuntimeError(f"LLM API call failed after {MAX_RETRIES} attempts: {last_error}")


def _coerce_ranked_indices(indices_raw: Any, paper_count: int) -> list[int]:
    if not isinstance(indices_raw, list) or not indices_raw:
        return []
    seen: set[int] = set()
    indices: list[int] = []
    for i in indices_raw:
        try:
            idx = int(i)
        except (TypeError, ValueError):
            continue
        if 0 <= idx < paper_count and idx not in seen:
            seen.add(idx)
            indices.append(idx)
        if len(indices) >= TOP_N:
            break
    return indices


def select_top_papers(
    papers: list[dict], metrics: list
) -> tuple[list[int], str, bool]:
    """Return (indices, reasoning, ranking_fallback)."""
    catalogue = build_paper_catalogue(papers)
    prompt = PAPER_RANKING_PROMPT.format(papers=catalogue)
    logger.info(
        "Requesting paper ranking from LLM "
        f"(catalogue ~{len(prompt) // 4} estimated tokens)..."
    )

    with track("llm_ranking", metrics) as entry:
        try:
            content = _call_llm_with_retry(
                [
                    {"role": "system", "content": "You are a research analyst."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                max_tokens=900,
                metric_entry=entry,
            )
        except RuntimeError as e:
            msg = str(e).lower()
            if "model_not_found" in msg or "does not exist or you do not have access" in msg or "decommissioned" in msg:
                raise RuntimeError(
                    f"LLM model is unavailable ({LLM_MODEL}). "
                    "Set LLM_MODEL in .env to a model your provider supports "
                    "(for Groq, try openai/gpt-oss-20b)."
                ) from e
            logger.warning(f"LLM ranking failed: {e}. Falling back to first {TOP_N} papers.")
            entry["ranking_fallback"] = True
            return (
                list(range(min(TOP_N, len(papers)))),
                "Fallback: ranking failed.",
                True,
            )

    data = _parse_json_safely(content)
    if not data:
        logger.warning("Failed to parse LLM ranking JSON. Falling back.")
        entry = metrics[-1]
        entry["ranking_fallback"] = True
        return (
            list(range(min(TOP_N, len(papers)))),
            "Fallback: JSON parse failed.",
            True,
        )

    indices = _coerce_ranked_indices(data.get("ranked_indices", []), len(papers))
    if not indices:
        entry = metrics[-1]
        entry["ranking_fallback"] = True
        return (
            list(range(min(TOP_N, len(papers)))),
            "Fallback: no valid indices.",
            True,
        )

    # Pad with newest remaining papers if the model returned fewer than TOP_N.
    if len(indices) < TOP_N:
        for i in range(len(papers)):
            if i not in indices:
                indices.append(i)
            if len(indices) >= TOP_N:
                break

    logger.info(f"Selected paper indices: {indices}")
    return indices, data.get("reasoning", "No reasoning provided."), False


def distil_paper(paper: dict, metrics: list) -> Optional[dict]:
    """Distill one paper. Returns None when output is unusable (never ships placeholders)."""
    prompt = PAPER_DISTILL_PROMPT.format(
        title=paper["title"],
        authors=paper["authors"],
        abstract=paper["abstract"],
        url=paper["url"],
    )
    logger.info(f"Distilling paper: {paper['title'][:60]}...")

    with track("llm_distill", metrics) as entry:
        last_content = None
        for attempt in range(DISTILL_PARSE_RETRIES + 1):
            try:
                content = _call_llm_with_retry(
                    [
                        {"role": "system", "content": "You are a research analyst."},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.5 if attempt == 0 else 0.2,
                    max_tokens=1400,
                    metric_entry=entry,
                )
            except RuntimeError as e:
                logger.warning(f"Distillation failed for '{paper['title'][:50]}': {e}")
                entry["distill_failed"] = True
                return None

            last_content = content
            data = _parse_json_safely(content)
            if not data:
                logger.warning(
                    f"JSON parse failed for '{paper['title'][:50]}' "
                    f"(attempt {attempt + 1}/{DISTILL_PARSE_RETRIES + 1})."
                )
                continue

            tags = data.get("tags", [])
            if not isinstance(tags, list):
                tags = []
            candidate = {
                "tldr": str(data.get("tldr", "")).strip(),
                "key_innovation": str(data.get("key_innovation", "")).strip(),
                "why_it_matters": str(data.get("why_it_matters", "")).strip(),
                "tags": _normalise_tags(tags),
            }
            if is_usable_distillation(candidate):
                return candidate
            logger.warning(
                f"Unusable distillation for '{paper['title'][:50]}' "
                f"(attempt {attempt + 1}/{DISTILL_PARSE_RETRIES + 1})."
            )

        logger.warning(
            f"Giving up on '{paper['title'][:50]}' after parse/quality failures. "
            f"Last content preview: {(last_content or '')[:120]!r}"
        )
        entry["distill_failed"] = True
        return None


def collect_distilled_papers(
    papers: list[dict],
    ranked_indices: list[int],
    metrics: list,
) -> tuple[list[dict], int]:
    """Walk ranked then remaining papers until TOP_N usable distillations exist."""
    ordered: list[int] = []
    seen: set[int] = set()
    for idx in list(ranked_indices) + list(range(len(papers))):
        if idx not in seen and 0 <= idx < len(papers):
            seen.add(idx)
            ordered.append(idx)

    distilled: list[dict] = []
    failures = 0
    for idx in ordered:
        if len(distilled) >= TOP_N:
            break
        paper = papers[idx]
        dist = distil_paper(paper, metrics)
        if dist is None:
            failures += 1
            continue
        dist["title"] = paper["title"]
        dist["authors"] = paper["authors"]
        dist["url"] = paper["url"]
        dist["published"] = paper.get("published", "")
        distilled.append(dist)

    return distilled, failures


def format_selection_rationale(selection_reasoning: str, *, ranking_fallback: bool) -> str:
    if not ranking_fallback:
        return selection_reasoning.strip()
    return (
        "**Degraded run:** LLM ranking was unavailable, so this report uses the "
        "newest arXiv submissions rather than a curated ranking.\n\n"
        f"{selection_reasoning.strip()}"
    )


def write_report(
    today: date,
    distilled_papers: list[dict],
    selection_reasoning: str,
    *,
    ranking_fallback: bool = False,
) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORTS_DIR / f"{today.isoformat()}.md"
    logger.info(f"Writing report to {report_path}")
    rationale = format_selection_rationale(
        selection_reasoning, ranking_fallback=ranking_fallback
    )
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(f"# AI Paper Scout Report — {today.isoformat()}\n\n")
        f.write("## Selection Rationale\n\n")
        f.write(f"{rationale}\n\n")
        f.write("---\n\n")
        for i, paper in enumerate(distilled_papers, 1):
            f.write(f"## {i}. {paper['title']}\n\n")
            f.write(f"**Authors:** {paper['authors']}\n\n")
            f.write(f"**TL;DR:** {paper['tldr']}\n\n")
            f.write(f"**Key Innovation:** {paper['key_innovation']}\n\n")
            f.write(f"**Why It Matters:** {paper['why_it_matters']}\n\n")
            f.write(f"**Tags:** {', '.join(paper['tags'])}\n\n")
            f.write(f"**Link:** [{paper['url']}]({paper['url']})\n\n")
            if i < len(distilled_papers):
                f.write("---\n\n")
    return report_path


def _extract_report_tags(report_path: Path) -> list[str]:
    """Extract unique tags from the first paper section in a report."""
    tags: list[str] = []
    try:
        with open(report_path, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped.startswith("**Tags:**"):
                    raw = stripped.replace("**Tags:**", "").strip()
                    for t in raw.split(","):
                        t = t.strip()
                        if t and t not in tags:
                            tags.append(t)
                    return tags
    except OSError:
        pass
    return tags


def update_readme_index(today: date, report_path: Path) -> bool:
    if not README_PATH.exists():
        logger.warning(f"{README_PATH} not found, skipping README index update")
        return False
    content = README_PATH.read_text(encoding="utf-8")
    marker = "<!-- REPORT_INDEX -->"
    if marker not in content:
        logger.warning(f"Marker '{marker}' not found in README, skipping update")
        return False
    date_str = today.isoformat()
    parts = content.split(marker)
    if len(parts) != 3:
        logger.warning("Malformed REPORT_INDEX marker, skipping update")
        return False
    index_section = parts[1]

    report_path = report_path.resolve()
    report_rel = report_path.relative_to(REPORTS_DIR.parent.resolve()).as_posix()

    existing_links = re.findall(r"\[([^\]]+)\]\(([^)]+)\)", index_section)
    for _, link_path in existing_links:
        if link_path == report_rel:
            logger.info(f"Report for {date_str} already in README index, skipping")
            return False

    tags = _extract_report_tags(report_path)
    first_tag = pick_readme_theme_tag(tags)
    date_label = today.strftime("%b %d")
    label = f"{date_label} · {first_tag}"
    new_link = f"[{label}]({report_rel})"

    all_entries = [new_link] + [f"[{lbl}]({pth})" for lbl, pth in existing_links]
    max_total = 30
    per_column = 10
    max_columns = 3
    all_entries = all_entries[:max_total]

    num_columns = min((len(all_entries) + per_column - 1) // per_column, max_columns)

    header = "|" + "|".join([" "] * num_columns) + "|"
    separator = "|" + "|".join(["---"] * num_columns) + "|"
    rows = [header, separator]
    for row_idx in range(per_column):
        cells = []
        for col_idx in range(num_columns):
            idx = col_idx * per_column + row_idx
            cells.append(all_entries[idx] if idx < len(all_entries) else " ")
        rows.append("|" + "|".join(cells) + "|")

    new_index = "\n".join(rows) + "\n"
    new_content = parts[0] + marker + "\n" + new_index + marker + parts[2]
    README_PATH.write_text(new_content, encoding="utf-8")
    logger.info("README index updated")
    return True


def main() -> Optional[Path]:
    validate_env()
    metrics: list = []
    pipeline_ok = False
    distilled: list = []
    ranking_fallback = False
    distill_failures = 0

    today = date.today()
    report_path = REPORTS_DIR / f"{today.isoformat()}.md"
    if report_path.exists():
        logger.info(f"Report for {today.isoformat()} already exists. Skipping.")
        return None

    try:
        papers = fetch_papers(metrics)
        ranked_indices, reasoning, ranking_fallback = select_top_papers(
            papers, metrics
        )
        distilled, distill_failures = collect_distilled_papers(
            papers, ranked_indices, metrics
        )
        if not distilled:
            raise RuntimeError(
                "No usable paper distillations produced. Refusing to write an empty/placeholder report."
            )
        if len(distilled) < TOP_N:
            logger.warning(
                f"Only {len(distilled)}/{TOP_N} usable distillations; writing partial report."
            )

        report_path = write_report(
            today,
            distilled,
            reasoning,
            ranking_fallback=ranking_fallback,
        )
        logger.info(f"Report written to: {report_path}")

        if update_readme_index(today, report_path):
            logger.info("README index updated successfully")

        pipeline_ok = True

    except Exception as exc:
        logger.error(f"Pipeline failed: {exc}")
        save_health_metrics(
            today,
            metrics,
            pipeline_ok=False,
            ranking_fallback=ranking_fallback,
            distill_failures=distill_failures,
            papers_written=len(distilled),
        )
        send_telegram(
            f"AI Paper Scout\n"
            f"Date: {today.isoformat()} | Status: Failed\n\n"
            f"Error: {str(exc)[:200]}\n"
            f"Steps completed: {len(metrics)}\n\n"
            f"Repository: {REPOSITORY_URL}"
        )
        raise

    save_health_metrics(
        today,
        metrics,
        pipeline_ok=True,
        ranking_fallback=ranking_fallback,
        distill_failures=distill_failures,
        papers_written=len(distilled),
    )
    send_telegram(
        build_telegram_message(
            today,
            distilled,
            metrics,
            pipeline_ok,
            ranking_fallback=ranking_fallback,
        )
    )
    return report_path


if __name__ == "__main__":
    main()
