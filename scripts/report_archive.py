"""Report Archive Generator

Generates a single-file HTML archive of all Markdown reports in reports/.
Also prints a plain-text summary table to stdout.

Usage:
    python scripts/report_archive.py                  # writes reports/archive.html
    python scripts/report_archive.py --stdout         # print summary only
    python scripts/report_archive.py --out custom.html
"""
from __future__ import annotations

import argparse
import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path

REPORTS_DIR = Path(__file__).parent.parent / "reports"
HEALTH_DIR = REPORTS_DIR / "health"


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

def parse_report(path: Path) -> dict:
    """Extract structured data from a YYYY-MM-DD.md report file."""
    text = path.read_text(encoding="utf-8")
    date = path.stem

    paper_blocks = re.split(r"(?m)^## \d+\. ", text)[1:]
    papers = []
    for block in paper_blocks:
        lines = block.strip().split("\n")
        title = lines[0].strip()
        tldr = _field(block, "TL;DR")
        key_innovation = _field(block, "Key Innovation")
        why_it_matters = _field(block, "Why It Matters")
        authors = _field(block, "Authors")
        tags = _field(block, "Tags")
        link = _field(block, "Link")
        url_m = re.search(r"\(https?://[^)]+\)", link)
        url = url_m.group()[1:-1] if url_m else link
        papers.append({
            "title": title,
            "authors": authors,
            "tldr": tldr,
            "key_innovation": key_innovation,
            "why_it_matters": why_it_matters,
            "tags": tags,
            "url": url,
        })

    health_path = HEALTH_DIR / f"{date}.json"
    health = None
    if health_path.exists():
        with open(health_path, encoding="utf-8") as f:
            health = json.load(f)

    return {"date": date, "papers": papers, "health": health, "raw": text}


def _field(block: str, label: str) -> str:
    m = re.search(rf"\*\*{re.escape(label)}:\*\*\s*(.+)", block)
    return m.group(1).strip() if m else ""


def load_all_reports() -> list[dict]:
    paths = sorted(
        REPORTS_DIR.glob("[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9].md"),
        reverse=True,
    )
    return [parse_report(p) for p in paths]


# ---------------------------------------------------------------------------
# Plain-text summary
# ---------------------------------------------------------------------------

def print_summary(reports: list[dict]) -> None:
    print(f"\n{'=' * 70}")
    print(f"  AI Paper Scout — Report Archive ({len(reports)} reports)")
    print(f"{'=' * 70}")
    for r in reports:
        h = r["health"]
        health_str = ""
        if h:
            ok = "OK" if h.get("pipeline_success") else "FAILED"
            lat = h.get("summary", {}).get("total_latency_s", "?")
            tokens = h.get("summary", {}).get("total_tokens", "?")
            breach = h.get("summary", {}).get("sla_breaches", 0)
            degraded = (h.get("quality") or {}).get("degraded")
            deg = " | degraded" if degraded else ""
            health_str = f" | {ok} {lat}s | {tokens} tokens | {breach} SLA breach(es){deg}"
        print(f"\n{r['date']}{health_str}")
        for i, p in enumerate(r["papers"], 1):
            print(f"   {i}. {p['title'][:70]}")
            if p["tldr"]:
                print(f"      -> {p['tldr'][:90]}")
    print()


# ---------------------------------------------------------------------------
# HTML archive
# ---------------------------------------------------------------------------

HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI Paper Scout — Archive</title>
<style>
  :root {
    --bg: #0e0e0f; --surface: #18181b; --surface2: #1f1f23;
    --border: #2e2e33; --text: #e4e4e7; --muted: #71717a;
    --accent: #4f98a3; --accent-hover: #227f8b;
    --success: #6daa45; --error: #dd6974; --warn: #d4a017;
    --radius: 0.5rem; --font: 'IBM Plex Sans', 'Segoe UI', system-ui, sans-serif;
  }
  [data-theme="light"] {
    --bg: #f7f6f2; --surface: #ffffff; --surface2: #f0efeb;
    --border: #d4d1ca; --text: #28251d; --muted: #7a7974;
  }
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  html { scroll-behavior: smooth; }
  body { font-family: var(--font); font-size: 15px; background: var(--bg);
         color: var(--text); line-height: 1.6; }
  a { color: var(--accent); text-decoration: none; }
  a:hover { color: var(--accent-hover); text-decoration: underline; }

  header { position: sticky; top: 0; z-index: 100;
           background: color-mix(in oklch, var(--bg) 90%, transparent);
           backdrop-filter: blur(12px); border-bottom: 1px solid var(--border);
           padding: 0.75rem 1.5rem; display: flex;
           align-items: center; justify-content: space-between; gap: 1rem; }
  header h1 { font-size: 1rem; font-weight: 600; white-space: nowrap; }
  header span { font-size: 0.8rem; color: var(--muted); }
  .theme-btn { background: none; border: 1px solid var(--border);
               color: var(--muted); border-radius: var(--radius);
               padding: 0.3rem 0.6rem; cursor: pointer; font-size: 0.8rem;
               transition: border-color 150ms, color 150ms; }
  .theme-btn:hover { border-color: var(--accent); color: var(--accent); }

  main { max-width: 860px; margin: 0 auto; padding: 2rem 1.5rem 4rem; }

  .stats { display: flex; gap: 1rem; flex-wrap: wrap; margin-bottom: 2rem; }
  .stat { background: var(--surface); border: 1px solid var(--border);
          border-radius: var(--radius); padding: 0.6rem 1rem; font-size: 0.8rem;
          color: var(--muted); }
  .stat strong { display: block; font-size: 1.2rem; color: var(--text); }

  .report { background: var(--surface); border: 1px solid var(--border);
             border-radius: var(--radius); margin-bottom: 1.25rem;
             overflow: hidden; }
  .report-header { display: flex; align-items: center; justify-content: space-between;
                   padding: 0.75rem 1rem; cursor: pointer;
                   border-bottom: 1px solid transparent;
                   transition: background 150ms; gap: 0.75rem; }
  .report-header:hover { background: var(--surface2); }
  .report.open .report-header { border-bottom-color: var(--border); }
  .report-date { font-weight: 600; font-size: 0.9rem; white-space: nowrap; }
  .report-meta { display: flex; gap: 0.5rem; align-items: center;
                 flex-wrap: wrap; font-size: 0.75rem; color: var(--muted); }
  .badge { display: inline-flex; align-items: center; gap: 0.25rem;
            padding: 0.15rem 0.5rem; border-radius: 99px;
            font-size: 0.7rem; font-weight: 500;
            background: var(--surface2); border: 1px solid var(--border); }
  .badge.ok  { color: var(--success); border-color: color-mix(in oklch, var(--success) 40%, transparent); }
  .badge.err { color: var(--error);   border-color: color-mix(in oklch, var(--error)   40%, transparent); }
  .badge.warn { color: var(--warn); border-color: color-mix(in oklch, var(--warn) 40%, transparent); }
  .chevron { margin-left: auto; color: var(--muted); transition: transform 200ms; }
  .report.open .chevron { transform: rotate(180deg); }

  .report-body { display: none; padding: 1rem; }
  .report.open .report-body { display: block; }

  .paper { padding: 0.75rem; border-radius: calc(var(--radius) - 2px);
           background: var(--surface2); margin-bottom: 0.75rem; }
  .paper:last-child { margin-bottom: 0; }
  .paper-title { font-weight: 600; font-size: 0.88rem; margin-bottom: 0.3rem; }
  .paper-authors { font-size: 0.75rem; color: var(--muted); margin-bottom: 0.35rem; }
  .paper-tldr { font-size: 0.82rem; color: var(--muted); margin-bottom: 0.4rem; }
  .paper-detail { font-size: 0.8rem; margin-bottom: 0.25rem; }
  .paper-detail strong { color: var(--text); font-weight: 600; }
  .paper-tags { display: flex; gap: 0.3rem; flex-wrap: wrap; margin-top: 0.4rem; }
  .tag { font-size: 0.7rem; padding: 0.1rem 0.4rem;
          border-radius: 99px; background: color-mix(in oklch, var(--accent) 12%, var(--surface));
          color: var(--accent); border: 1px solid color-mix(in oklch, var(--accent) 25%, transparent); }

  .health { margin-top: 1rem; font-size: 0.78rem; color: var(--muted);
             border-top: 1px solid var(--border); padding-top: 0.75rem; }
  .health-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
                  gap: 0.4rem; margin-top: 0.4rem; }
  .health-item { background: var(--surface); border: 1px solid var(--border);
                  border-radius: calc(var(--radius) - 2px); padding: 0.4rem 0.6rem; }
  .health-item span { display: block; font-size: 0.7rem; color: var(--muted); }
  .health-item strong { font-size: 0.85rem; color: var(--text); }

  .search-wrap { margin-bottom: 1.5rem; }
  #search { width: 100%; background: var(--surface); border: 1px solid var(--border);
             border-radius: var(--radius); padding: 0.5rem 0.75rem;
             font-size: 0.88rem; color: var(--text); outline: none;
             transition: border-color 150ms; }
  #search:focus { border-color: var(--accent); }
  #search::placeholder { color: var(--muted); }

  footer { text-align: center; font-size: 0.75rem; color: var(--muted);
            padding: 2rem; border-top: 1px solid var(--border); }
</style>
</head>
<body>

<header>
  <h1>AI Paper Scout — Archive</h1>
  <span>Generated {generated_at}</span>
  <button class="theme-btn" type="button" onclick="toggleTheme()" title="Toggle theme">Theme</button>
</header>

<main>
  <div class="stats">
    <div class="stat"><strong>{total_reports}</strong>Reports</div>
    <div class="stat"><strong>{total_papers}</strong>Papers distilled</div>
    <div class="stat"><strong>{total_tokens}</strong>Tokens used</div>
    <div class="stat"><strong>{success_rate}%</strong>Pipeline success rate</div>
  </div>

  <div class="search-wrap">
    <input id="search" type="search" placeholder="Search by title, tag, or date…" oninput="filterReports()">
  </div>

  <div id="reports">
    {report_cards}
  </div>
</main>

<footer>AI Paper Scout — auto-generated archive — {generated_at}</footer>

<script>
function toggleTheme() {
  const html = document.documentElement;
  html.setAttribute('data-theme', html.getAttribute('data-theme') === 'dark' ? 'light' : 'dark');
}
function toggleReport(el) {
  el.closest('.report').classList.toggle('open');
}
function filterReports() {
  const q = document.getElementById('search').value.toLowerCase();
  document.querySelectorAll('.report').forEach(card => {
    card.style.display = card.textContent.toLowerCase().includes(q) ? '' : 'none';
  });
}
document.addEventListener('DOMContentLoaded', () => {
  const first = document.querySelector('.report');
  if (first) first.classList.add('open');
});
</script>
</body>
</html>
"""


def _esc(value: str) -> str:
    return html.escape(value or "", quote=True)


def _health_badges(health: dict | None) -> str:
    if not health:
        return ""
    ok = health.get("pipeline_success", False)
    summary = health.get("summary", {})
    quality = health.get("quality") or {}
    cls = "ok" if ok else "err"
    label = "OK" if ok else "FAILED"
    lat = summary.get("total_latency_s", "?")
    tokens = summary.get("total_tokens", "?")
    breach = summary.get("sla_breaches", 0)
    b = f'<span class="badge {cls}">{_esc(label)}</span>'
    if quality.get("degraded"):
        b += '<span class="badge warn">degraded</span>'
    if quality.get("ranking_fallback"):
        b += '<span class="badge warn">ranking fallback</span>'
    b += f'<span class="badge">{_esc(str(lat))}s</span>'
    b += f'<span class="badge">{_esc(str(tokens))} tokens</span>'
    if breach:
        b += f'<span class="badge err">{_esc(str(breach))} SLA breach</span>'
    return b


def _health_detail(health: dict | None) -> str:
    if not health:
        return ""
    s = health.get("summary", {})
    q = health.get("quality") or {}
    items = [
        ("Latency", f"{s.get('total_latency_s', '?')}s"),
        ("Tokens", str(s.get("total_tokens", "?"))),
        ("Retries", str(s.get("total_retries", "?"))),
        ("SLA breach", str(s.get("sla_breaches", "?"))),
        ("Ranking fallback", "yes" if q.get("ranking_fallback") else "no"),
        ("Distill failures", str(q.get("distill_failures", 0))),
    ]
    grid = "".join(
        f'<div class="health-item"><span>{_esc(k)}</span><strong>{_esc(v)}</strong></div>'
        for k, v in items
    )
    errors = s.get("errors", [])
    err_html = ""
    if errors:
        err_html = (
            f'<p style="color:var(--error);margin-top:0.4rem;font-size:0.75rem">'
            f'{_esc(str(errors[0])[:120])}</p>'
        )
    return (
        f'<div class="health"><strong>Pipeline metrics</strong>'
        f'<div class="health-grid">{grid}</div>{err_html}</div>'
    )


def _paper_card(paper: dict) -> str:
    title = _esc(paper.get("title", ""))
    authors = _esc(paper.get("authors", ""))
    tldr = _esc(paper.get("tldr", ""))
    innovation = _esc(paper.get("key_innovation", ""))
    impact = _esc(paper.get("why_it_matters", ""))
    raw_url = paper.get("url", "") or ""
    # Only allow http(s) links into href attributes.
    safe_url = raw_url if re.match(r"^https?://", raw_url) else ""
    href = _esc(safe_url)
    tags = [t.strip() for t in (paper.get("tags") or "").split(",") if t.strip()]
    tag_html = "".join(f'<span class="tag">{_esc(t)}</span>' for t in tags)
    title_html = (
        f'<a href="{href}" target="_blank" rel="noopener noreferrer">{title}</a>'
        if safe_url
        else title
    )
    authors_html = f'<div class="paper-authors">{authors}</div>' if authors else ""
    tldr_html = f'<div class="paper-tldr">{tldr}</div>' if tldr else ""
    innovation_html = (
        f'<div class="paper-detail"><strong>Key innovation:</strong> {innovation}</div>'
        if innovation
        else ""
    )
    impact_html = (
        f'<div class="paper-detail"><strong>Why it matters:</strong> {impact}</div>'
        if impact
        else ""
    )
    tags_html = f'<div class="paper-tags">{tag_html}</div>' if tag_html else ""
    return (
        f'<div class="paper">'
        f'<div class="paper-title">{title_html}</div>'
        f'{authors_html}{tldr_html}{innovation_html}{impact_html}{tags_html}'
        f'</div>'
    )


def _report_card(report: dict) -> str:
    date_str = _esc(report["date"])
    papers = report["papers"]
    health = report["health"]

    badges = _health_badges(health)
    papers_html = "".join(_paper_card(p) for p in papers)
    health_detail = _health_detail(health)
    count_str = f"{len(papers)} paper{'' if len(papers) == 1 else 's'}"

    return (
        f'<div class="report" data-date="{date_str}">'
        f'<div class="report-header" onclick="toggleReport(this)">'
        f'<span class="report-date">{date_str}</span>'
        f'<div class="report-meta">{badges}<span class="badge">{_esc(count_str)}</span></div>'
        f'<svg class="chevron" width="16" height="16" viewBox="0 0 24 24" fill="none" '
        f'stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>'
        f'</div>'
        f'<div class="report-body">{papers_html}{health_detail}</div>'
        f'</div>'
    )


def generate_html(reports: list[dict], out_path: Path) -> None:
    if not reports:
        print("No reports found in reports/.")
        return

    total_papers = sum(len(r["papers"]) for r in reports)
    total_tokens = sum(
        (r["health"] or {}).get("summary", {}).get("total_tokens", 0) for r in reports
    )
    runs_with_health = [r for r in reports if r["health"] is not None]
    successful_runs = sum(
        1 for r in runs_with_health if r["health"].get("pipeline_success")
    )
    success_rate = (
        round(100 * successful_runs / len(runs_with_health)) if runs_with_health else "N/A"
    )

    report_cards = "\n".join(_report_card(r) for r in reports)
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Use replace (not str.format): CSS braces in the template would KeyError.
    html_out = (
        HTML_TEMPLATE
        .replace("{generated_at}", generated_at)
        .replace("{total_reports}", str(len(reports)))
        .replace("{total_papers}", str(total_papers))
        .replace("{total_tokens}", f"{total_tokens:,}")
        .replace("{success_rate}", str(success_rate))
        .replace("{report_cards}", report_cards)
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html_out, encoding="utf-8")
    print(f"Archive written to: {out_path}  ({len(reports)} reports, {total_papers} papers)")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Generate AI Paper Scout HTML archive")
    parser.add_argument(
        "--out",
        default=str(REPORTS_DIR / "archive.html"),
        help="Output HTML file path",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="Print plain-text summary to stdout only",
    )
    args = parser.parse_args()

    reports = load_all_reports()
    if not reports:
        print("No reports found. Run distill.py first.")
        return

    print_summary(reports)
    if not args.stdout:
        generate_html(reports, Path(args.out))


if __name__ == "__main__":
    main()
