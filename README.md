<div align="center">

<br/>

# AI Paper Scout

<p>
  <img src="https://img.shields.io/badge/arXiv-cs.AI%20%7C%20cs.LG-b31b1b?style=flat-square&logo=arxiv&logoColor=white" />
  &nbsp;
  <img src="https://img.shields.io/badge/Groq%20LPU-powered-F55036?style=flat-square" />
  &nbsp;
  <img src="https://img.shields.io/github/actions/workflow/status/mohabdelkarim/ai-paper-scout/distill.yml?style=flat-square&label=weekly%20run&logo=github-actions&logoColor=white" />
  &nbsp;
  <img src="https://img.shields.io/badge/cost%20per%20run-%240.002-22c55e?style=flat-square" />
  &nbsp;
  <img src="https://img.shields.io/badge/Telegram-notifications-26A5E4?style=flat-square&logo=telegram&logoColor=white" />
</p>

<br/>

> ### 100+ AI papers land on arXiv every day. You don't have time for that.
> **AI Paper Scout reads them all, picks the 3 that matter, and tells you why.**
> Every Thursday. Automatically. In your repo and on your phone.

<br/>

</div>

## Features

<div align="center">

| | | | | | |
|:---:|:---:|:---:|:---:|:---:|:---:|
| **Auto-fetch** | **LLM Ranking** | **Distilled Reports** | **Telegram Alerts** | **Security Scanning** | **Health Metrics** |
| 60 papers from arXiv | Top 3 selected by AI | Clean Markdown | Digest on your phone | Trivy + secret scan | SLA, tokens, latency |

</div>

<br/>

## The Pipeline

```mermaid
flowchart LR
    A(["arXiv\n cs.AI · cs.LG"]):::red -->|"fetch 60 papers"| B
    B(["LLM Ranker\n Groq LPU"]):::dark -->|"score · select top 3"| C
    C(["Distiller"]):::mid -->|"TL;DR · Innovation · Impact · Tags"| D
    D(["Report\n YYYY-MM-DD.md"]):::purple -->|"commit & push"| E
    E(["Telegram\n + HTML Archive"]):::blue

    classDef red    fill:#b31b1b,color:#fff,stroke:none
    classDef dark   fill:#18181b,color:#fff,stroke:none
    classDef mid    fill:#27272a,color:#fff,stroke:none
    classDef purple fill:#3b0764,color:#fff,stroke:none
    classDef blue   fill:#1d4ed8,color:#fff,stroke:none
```

<br/>

<div align="center">
<table>
<tr>
<td align="center" width="175"><strong>TL;DR</strong><br/><sup>What the paper does<br/>in one sentence</sup></td>
<td align="center" width="175"><strong>Key Innovation</strong><br/><sup>The specific technique<br/>or finding that is new</sup></td>
<td align="center" width="175"><strong>Why It Matters</strong><br/><sup>What you can concretely<br/>build with this</sup></td>
<td align="center" width="175"><strong>Tags</strong><br/><sup><code>rag</code> &nbsp; <code>vision-language</code><br/><code>fine-tuning</code></sup></td>
<td align="center" width="175"><strong>Link</strong><br/><sup>Direct arXiv link,<br/>no paywalls</sup></td>
</tr>
</table>
</div>

<br/>

## Quick Start

**Prerequisites:** Python 3.9+ &nbsp;&middot;&nbsp; A free [Groq API key](https://console.groq.com) (takes 30 seconds)

**1. Clone & install**

```bash
git clone https://github.com/mohabdelkarim/ai-paper-scout.git
cd ai-paper-scout
python -m venv .venv && source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

**2. Add your API key**

```bash
cp .env.example .env
```

Open `.env` and set:

```
LLM_API_KEY=gsk_...        # your Groq key — free tier is enough
```

**3. Run**

```bash
python scripts/distill.py
```

In ~30 seconds you get:

```
reports/
├── 2026-06-20.md          ← today's 3 papers, ranked and distilled
└── health/
    └── 2026-06-20.json    ← pipeline metrics (latency, tokens, SLA)
```

**4. Generate the HTML archive** (optional)

```bash
python scripts/report_archive.py
```

Produces `reports/archive.html` — a searchable, themeable single-file archive of every report with pipeline health metrics.

> **Want a different provider?** Set `LLM_API_BASE` and `LLM_MODEL` in `.env` to use OpenAI, Together, Mistral, Ollama, or any OpenAI-compatible endpoint. No code changes needed.

## GitHub Actions — Set & Forget

<div align="center"><br/>
<strong>No server &nbsp;&middot;&nbsp; No infra &nbsp;&middot;&nbsp; No maintenance</strong><br/>
<sub>Push once — a fresh digest arrives in your repo every Thursday at 09:00 UTC.</sub>
<br/><br/>

| | Step | |
|:---:|---|:---:|
| **1** | **Fork or push** this repo to your GitHub account | |
| **2** | Go to **Settings → Secrets and variables → Actions** | |
| **3** | Add the secrets below — then you're done | |

</div>

<br/>

**Required secret**

```
LLM_API_KEY = gsk_...        ← your Groq key (free at console.groq.com)
```

**Optional secrets**

| Secret | Example value | Effect |
|---|---|---|
| `LLM_API_BASE` | `https://api.openai.com/v1` | Point to OpenAI, Together, Mistral, Ollama… |
| `LLM_MODEL` | `gpt-4o-mini` | Override the model used for ranking & distilling |
| `TELEGRAM_BOT_TOKEN` | `123456:ABC-DEF…` | Enable Telegram notifications |
| `TELEGRAM_CHAT_ID` | `123456789` | Where to send the digest |

<br/>

> **Run it right now →** go to **Actions → AI Paper Scout → Run workflow**

## Telegram Notifications

When `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are set, every run sends a rich Markdown digest to your phone:

```
AI Paper Scout — 2026-06-20

Top 3 AI Papers Today

1. VERITAS: Visual Verification for Robot Policies
   Robots can now self-check their actions...
   Gradient-free visual verifier at inference time...
   Improves deployment reliability without retraining...
   robotics  visual-verification  inference-time
   https://arxiv.org/abs/...

Pipeline Health
   Total latency: 12.4s
   Tokens used: 4200
   All SLA thresholds met
```

Failure alerts are also sent automatically — you'll know immediately if something breaks.

## Security Scanning

A weekly [Trivy](https://trivy.dev) scan runs every Monday, checking dependencies and the filesystem for vulnerabilities and leaked secrets. Results are sent via Telegram — critical findings are flagged as critical, highs as warnings, clean runs confirmed.

## Health Metrics & SLA Monitoring

Every pipeline run records detailed metrics to `reports/health/YYYY-MM-DD.json`:

| Metric | Description |
|---|---|
| **Latency per step** | Time spent on arXiv fetch, LLM ranking, each distillation |
| **SLA breaches** | Steps that exceeded their time threshold (20s fetch, 35s ranking, 25s distill) |
| **Token usage** | Total LLM tokens consumed per step and overall |
| **Retry count** | API calls that needed exponential-backoff retries |
| **Errors** | Any step-level errors with full context |

The HTML archive surfaces these as per-report badges and expandable metric grids.

## Reference

### Why Groq?

Groq's LPU inference runs **~10× faster** than typical GPU inference — ranking 60 papers takes seconds, not minutes. The free tier covers all usage for this project. To use a different provider, set `LLM_API_BASE` and `LLM_MODEL` — no code changes needed.

### Configuration

| Variable | Required | Default | Notes |
|---|---|---|---|
| `LLM_API_KEY` | Yes | — | Your provider API key |
| `LLM_API_BASE` | No | `https://api.groq.com/openai/v1` | Any OpenAI-compatible endpoint |
| `LLM_MODEL` | No | `llama-3.3-70b-versatile` | Any model your provider supports |
| `TELEGRAM_BOT_TOKEN` | No | — | Telegram bot token for notifications |
| `TELEGRAM_CHAT_ID` | No | — | Telegram chat ID to send digest to |

### Resilience

| Scenario | What happens |
|---|---|
| Report already exists for today | Skipped — no duplicate commits |
| LLM ranking fails | Falls back to first 3 fetched papers |
| Single paper distillation fails | Writes fallback summary, continues |
| `<!-- REPORT_INDEX -->` missing | Logs warning, skips safely |
| API rate limit hit | 3 retries with exponential backoff |
| Telegram not configured | Skips notification, pipeline continues |
| Pipeline crashes | Error alert sent via Telegram, health JSON saved |

### Project Structure

```
ai-paper-scout/
├── .github/workflows/
│   ├── distill.yml                ──  cron: every Thursday at 09:00 UTC
│   └── security.yml               ──  Trivy scan: every Monday at 08:00 UTC
├── scripts/
│   ├── distill.py                 ──  fetch → rank → distil → report → notify
│   └── report_archive.py          ──  generates searchable HTML archive
├── reports/
│   ├── YYYY-MM-DD.md              ──  one distilled report per run
│   ├── health/YYYY-MM-DD.json     ──  pipeline metrics per run
│   └── archive.html               ──  generated HTML archive (run report_archive.py)
├── .env.example
├── requirements.txt
└── README.md
```

### Troubleshooting

**No papers fetched** — check connectivity to `export.arxiv.org` and confirm the `arxiv` package is installed.

**LLM API errors** — verify `LLM_API_KEY` is valid and matches the provider at `LLM_API_BASE`.

**README index not updating** — ensure both `<!-- REPORT_INDEX -->` markers are present in this file.

**Workflow not triggering** — confirm GitHub Actions is enabled and the schedule is `0 9 * * 4`.

**Telegram not sending** — verify `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are set as repository secrets.

## Report Archive

<div align="center">

| Date | Report |
|:---:|:---:|
| Jun 20, 2026 | [→ read](reports/2026-06-20.md) |
| Jun 19, 2026 | [→ read](reports/2026-06-19.md) |
| Jun 17, 2026 | [→ read](reports/2026-06-17.md) |
| Jun 15, 2026 | [→ read](reports/2026-06-15.md) |
| Jun 13, 2026 | [→ read](reports/2026-06-13.md) |
| Jun 09, 2026 | [→ read](reports/2026-06-09.md) |
| Jun 07, 2026 | [→ read](reports/2026-06-07.md) |
| May 31, 2026 | [→ read](reports/2026-05-31.md) |
<!-- REPORT_INDEX -->
<!-- REPORT_INDEX -->

</div>

<br/>

<div align="center">
<sup>Built by <a href="https://github.com/mohabdelkarim">@mohabdelkarim</a> &middot; MIT License</sup>
</div>
