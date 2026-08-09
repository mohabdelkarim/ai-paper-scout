import os
import json
import logging
import re
import time
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import arxiv
import httpx
import openai
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

LLM_API_KEY     = os.getenv("LLM_API_KEY")
LLM_API_BASE    = os.getenv("LLM_API_BASE", "https://api.groq.com/openai/v1")
LLM_MODEL       = os.getenv("LLM_MODEL", "llama-3.3-70b-versatile")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID")
REPOSITORY_URL    = "https://github.com/mohabdelkarim/ai-paper-scout"

REPORTS_DIR = Path(__file__).parent.parent / "reports"
HEALTH_DIR  = REPORTS_DIR / "health"
README_PATH = Path(__file__).parent.parent / "README.md"

MAX_PAPERS          = 60
TOP_N               = 3
MAX_RETRIES         = 3
RETRY_DELAY         = 2.0
ABSTRACT_TRUNCATE_LEN = 400

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
    entry = {
        "step": name,
        "timestamp_utc": datetime.utcnow().isoformat(),
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
        entry["sla_ok"]    = elapsed <= entry["sla_threshold_s"]
        metrics.append(entry)
        status = "OK" if entry["sla_ok"] else "SLA BREACH"
        logger.info(f"[{status}] {name} — {elapsed}s (threshold {entry['sla_threshold_s']}s)")


def save_health_metrics(today: date, metrics: list, pipeline_ok: bool) -> Path:
    """Persist health data to reports/health/YYYY-MM-DD.json."""
    HEALTH_DIR.mkdir(parents=True, exist_ok=True)
    path = HEALTH_DIR / f"{today.isoformat()}.json"
    payload = {
        "date": today.isoformat(),
        "pipeline_success": pipeline_ok,
        "steps": metrics,
        "summary": {
            "total_steps":    len(metrics),
            "sla_breaches":   sum(1 for m in metrics if m.get("sla_ok") is False),
            "total_retries":  sum(m.get("retries", 0) for m in metrics),
            "total_tokens":   sum(m.get("tokens_used") or 0 for m in metrics),
            "total_latency_s": round(sum(m.get("latency_s") or 0 for m in metrics), 3),
            "errors":         [m["error"] for m in metrics if m.get("error")],
        },
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
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
                "text": message,
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
    today: date, distilled_papers: list, metrics: list, pipeline_ok: bool
) -> str:
    breaches      = [m for m in metrics if m.get("sla_ok") is False]
    total_tokens  = sum(m.get("tokens_used") or 0 for m in metrics)
    total_latency = round(sum(m.get("latency_s") or 0 for m in metrics), 1)
    status_text   = "Success" if pipeline_ok else "Failed"

    lines = [
        "AI Paper Scout",
        f"Date: {today.isoformat()} | Status: {status_text}",
        "",
        "Top 3 Papers",
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
    lines += [
        "",
        f"Repository: {REPOSITORY_URL}",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def validate_env() -> None:
    if not LLM_API_KEY:
        raise EnvironmentError(
            "LLM_API_KEY is not set. Copy .env.example to .env and fill in your values."
        )


def get_client() -> OpenAI:
    return OpenAI(api_key=LLM_API_KEY, base_url=LLM_API_BASE)


def fetch_papers(metrics: list) -> list[dict]:
    logger.info("Fetching papers from arXiv (cs.AI OR cs.LG)...")
    papers = []
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
                "title":     result.title.strip(),
                "authors":   ", ".join(a.name for a in result.authors),
                "abstract":  abstract_clean,
                "url":       result.entry_id,
                "published": result.published.strftime("%Y-%m-%d"),
            })
        if not papers:
            raise RuntimeError("No papers fetched from arXiv. Check network connectivity.")
        logger.info(f"Fetched {len(papers)} papers")
    return papers


def build_paper_catalogue(papers: list[dict]) -> str:
    parts = []
    for i, paper in enumerate(papers):
        snippet = paper["abstract"][:ABSTRACT_TRUNCATE_LEN].rstrip()
        parts.append(
            f"[{i}] Title: {paper['title']}\n"
            f"   Authors: {paper['authors']}\n"
            f"   Abstract: {snippet}..."
        )
    return "\n\n".join(parts)


def _parse_json_safely(content: str) -> Optional[dict]:
    content = content.strip()
    content = re.sub(r"^```json\s*", "", content)
    content = re.sub(r"^```\s*",    "", content)
    content = re.sub(r"\s*```$",    "", content)
    m = re.search(r"\{[\s\S]*\}", content)
    if not m:
        return None
    try:
        return json.loads(m.group())
    except json.JSONDecodeError:
        return None


def _normalise_tags(tags: list) -> list[str]:
    result = []
    for t in tags[:5]:
        tag = str(t).strip().lower()
        tag = re.sub(r"[\s_]+", "-", tag)
        tag = re.sub(r"[^a-z0-9-]", "", tag)
        tag = re.sub(r"-+", "-", tag).strip("-")
        if tag:
            result.append(tag)
    return result


def _call_llm_with_retry(
    client: OpenAI,
    messages: list[dict],
    temperature: float,
    max_tokens: int,
    metric_entry: Optional[dict] = None,
) -> str:
    """
    Call the LLM with exponential-backoff retry.
    Uses `openai.APIError` and `openai.RateLimitError` (valid in both v1 and v2).
    `response.usage.total_tokens` is stable across SDK versions.
    """
    last_error = None
    total_retries = 0
    for attempt in range(MAX_RETRIES):
        try:
            response = client.chat.completions.create(
                model=LLM_MODEL,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            if metric_entry is not None and response.usage:
                metric_entry["tokens_used"] = response.usage.total_tokens
                metric_entry["retries"]     = total_retries
            return response.choices[0].message.content.strip()
        except (openai.APIError, openai.RateLimitError) as e:
            last_error = e
            total_retries += 1
            if attempt < MAX_RETRIES - 1:
                wait = RETRY_DELAY * (2 ** attempt)
                logger.warning(
                    f"API error (attempt {attempt + 1}/{MAX_RETRIES}): {e}. "
                    f"Retrying in {wait}s..."
                )
                time.sleep(wait)
    if metric_entry is not None:
        metric_entry["retries"] = total_retries
    raise RuntimeError(f"LLM API call failed after {MAX_RETRIES} attempts: {last_error}")


def select_top_papers(
    client: OpenAI, papers: list[dict], metrics: list
) -> tuple[list[int], str]:
    catalogue = build_paper_catalogue(papers)
    prompt    = PAPER_RANKING_PROMPT.format(papers=catalogue)
    logger.info("Requesting paper ranking from LLM...")

    with track("llm_ranking", metrics) as entry:
        try:
            content = _call_llm_with_retry(
                client,
                [{"role": "system", "content": "You are a research analyst."},
                 {"role": "user",   "content": prompt}],
                temperature=0.3,
                max_tokens=500,
                metric_entry=entry,
            )
        except RuntimeError as e:
            logger.warning(f"LLM ranking failed: {e}. Falling back to first {TOP_N} papers.")
            return list(range(min(TOP_N, len(papers)))), "Fallback: ranking failed."

    data = _parse_json_safely(content)
    if not data:
        logger.warning("Failed to parse LLM ranking JSON. Falling back.")
        return list(range(min(TOP_N, len(papers)))), "Fallback: JSON parse failed."

    indices_raw = data.get("ranked_indices", [])
    if not isinstance(indices_raw, list) or not indices_raw:
        return list(range(min(TOP_N, len(papers)))), "Fallback: invalid ranked_indices."

    seen, indices = set(), []
    for i in indices_raw:
        try:
            idx = int(i)
        except (TypeError, ValueError):
            continue
        if 0 <= idx < len(papers) and idx not in seen:
            seen.add(idx)
            indices.append(idx)
        if len(indices) >= TOP_N:
            break

    if not indices:
        return list(range(min(TOP_N, len(papers)))), "Fallback: no valid indices."

    logger.info(f"Selected paper indices: {indices}")
    return indices, data.get("reasoning", "No reasoning provided.")


def distil_paper(client: OpenAI, paper: dict, metrics: list) -> dict:
    prompt = PAPER_DISTILL_PROMPT.format(
        title=paper["title"],
        authors=paper["authors"],
        abstract=paper["abstract"],
        url=paper["url"],
    )
    logger.info(f"Distilling paper: {paper['title'][:60]}...")

    with track("llm_distill", metrics) as entry:
        try:
            content = _call_llm_with_retry(
                client,
                [{"role": "system", "content": "You are a research analyst."},
                 {"role": "user",   "content": prompt}],
                temperature=0.5,
                max_tokens=800,
                metric_entry=entry,
            )
        except RuntimeError as e:
            logger.warning(f"Distillation failed for '{paper['title'][:50]}': {e}")
            return _fallback_distillation(paper)

    data = _parse_json_safely(content)
    if not data:
        logger.warning(f"JSON parse failed for '{paper['title'][:50]}'. Using fallback.")
        return _fallback_distillation(paper)

    tags = data.get("tags", ["research", "ai", "ml"])
    if not isinstance(tags, list):
        tags = ["research", "ai", "ml"]

    return {
        "tldr":           data.get("tldr",           f"Research on {paper['title'][:100]}."),
        "key_innovation": data.get("key_innovation",  "Technical details under review."),
        "why_it_matters": data.get("why_it_matters",  "Potential impact on AI/ML field."),
        "tags":           _normalise_tags(tags),
    }


def _fallback_distillation(paper: dict) -> dict:
    return {
        "tldr":           f"Research on {paper['title'][:100]}.",
        "key_innovation": "Technical details under review.",
        "why_it_matters": "Potential impact on AI/ML field.",
        "tags":           ["research", "ai", "ml"],
    }


def write_report(today: date, distilled_papers: list[dict], selection_reasoning: str) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORTS_DIR / f"{today.isoformat()}.md"
    logger.info(f"Writing report to {report_path}")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(f"# AI Paper Scout Report — {today.isoformat()}\n\n")
        f.write("## Selection Rationale\n\n")
        f.write(f"{selection_reasoning}\n\n")
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
    """Extract unique tags from the first paper in a report Markdown file."""
    tags = []
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
    except Exception:
        pass
    return tags


def update_readme_index(today: date, report_path: Path) -> bool:
    if not README_PATH.exists():
        logger.warning(f"{README_PATH} not found, skipping README index update")
        return False
    with open(README_PATH, "r", encoding="utf-8") as f:
        content = f.read()
    marker = "<!-- REPORT_INDEX -->"
    if marker not in content:
        logger.warning(f"Marker '{marker}' not found in README, skipping update")
        return False
    date_str  = today.isoformat()
    parts = content.split(marker)
    if len(parts) != 3:
        logger.warning("Malformed REPORT_INDEX marker, skipping update")
        return False
    index_section = parts[1]

    report_rel = report_path.relative_to(REPORTS_DIR.parent).as_posix()

    existing_links = re.findall(r"\[([^\]]+)\]\(([^)]+)\)", index_section)
    for _, link_path in existing_links:
        if link_path == report_rel:
            logger.info(f"Report for {date_str} already in README index, skipping")
            return False

    tags = _extract_report_tags(report_path)
    first_tag = tags[0] if tags else "AI Research"
    date_label = today.strftime("%b %d")
    label = f"{date_label} · {first_tag}"
    new_link = f"[{label}]({report_rel})"

    all_entries = [new_link] + [f"[{lbl}]({pth})" for lbl, pth in existing_links]
    max_total   = 30
    per_column  = 10
    max_columns = 3
    all_entries = all_entries[:max_total]

    num_columns = min((len(all_entries) + per_column - 1) // per_column, max_columns)

    header    = "|" + "|".join([" "] * num_columns) + "|"
    separator = "|" + "|".join(["---"] * num_columns) + "|"
    rows = [header, separator]
    for row_idx in range(per_column):
        cells = []
        for col_idx in range(num_columns):
            idx = col_idx * per_column + row_idx
            cells.append(all_entries[idx] if idx < len(all_entries) else " ")
        rows.append("|" + "|".join(cells) + "|")

    new_index = "\n".join(rows) + "\n"
    new_content = parts[0] + marker + new_index + marker + parts[2]
    with open(README_PATH, "w", encoding="utf-8") as f:
        f.write(new_content)
    logger.info("README index updated")
    return True


def main() -> Optional[Path]:
    validate_env()
    client: OpenAI = get_client()
    metrics: list  = []
    pipeline_ok    = False
    distilled: list = []

    today       = date.today()
    report_path = REPORTS_DIR / f"{today.isoformat()}.md"
    if report_path.exists():
        logger.info(f"Report for {today.isoformat()} already exists. Skipping.")
        return None

    try:
        papers = fetch_papers(metrics)
        ranked_indices, reasoning = select_top_papers(client, papers, metrics)
        selected_papers = [papers[i] for i in ranked_indices]

        for paper in selected_papers:
            dist = distil_paper(client, paper, metrics)
            dist["title"]   = paper["title"]
            dist["authors"] = paper["authors"]
            dist["url"]     = paper["url"]
            distilled.append(dist)

        report_path = write_report(today, distilled, reasoning)
        logger.info(f"Report written to: {report_path}")

        if update_readme_index(today, report_path):
            logger.info("README index updated successfully")

        pipeline_ok = True

    except Exception as exc:
        logger.error(f"Pipeline failed: {exc}")
        save_health_metrics(today, metrics, pipeline_ok=False)
        send_telegram(
            f"AI Paper Scout\n"
            f"Date: {today.isoformat()} | Status: Failed\n\n"
            f"Error: {str(exc)[:200]}\n"
            f"Steps completed: {len(metrics)}\n\n"
            f"Repository: {REPOSITORY_URL}"
        )
        raise

    save_health_metrics(today, metrics, pipeline_ok=True)
    send_telegram(build_telegram_message(today, distilled, metrics, pipeline_ok))
    return report_path


if __name__ == "__main__":
    main()
