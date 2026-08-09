<div align="center">

<br/>

```
    _   ___    ___  _   ___ ___ ___    ___  ___ ___  _   _ _____
    /_\ |_ _|  | _ \/_\ | _ \ __| _ \  / __|/ __/ _ \| | | |_   _|
   / _ \ | |   |  _/ _ \|  _/ _||   /  \__ \ (_| (_) | |_| | | |
  /_/ \_\___|  |_|/_/ \_\_| |___|_|_\  |___/\___\___/ \___/  |_|
```

<br/>

<p>
  <img src="https://img.shields.io/badge/arXiv-cs.AI%20%7C%20cs.LG-b31b1b?style=flat-square&logo=arxiv&logoColor=white" />
  &nbsp;
  <img src="https://img.shields.io/badge/Groq%20LPU-powered-F55036?style=flat-square" />
  &nbsp;
  <img src="https://img.shields.io/github/actions/workflow/status/mohabdelkarim/ai-paper-scout/distill.yml?style=flat-square&label=weekly%20run&logo=github-actions&logoColor=white" />
  &nbsp;
  <img src="https://img.shields.io/badge/cost%20per%20run-%240.002-22c55e?style=flat-square" />
</p>

<br/>

<p><strong>100+ AI papers land on arXiv every day.<br/>
AI Paper Scout reads them. You read 3.</strong></p>

<p><sup>Fetches &nbsp;&middot;&nbsp; Ranks &nbsp;&middot;&nbsp; Distils &nbsp;&middot;&nbsp; Commits &mdash; automatically, every Thursday.</sup></p>

<br/>

</div>

---

## How It Works

```mermaid
flowchart LR
    A(["arXiv\ncs.AI · cs.LG"]):::red   -->|"fetch  60 papers"| B
    B(["LLM Ranker\nGroq LPU"]):::dark  -->|"score · select top 3"| C
    C(["Distiller"]):::mid               -->|"structure each paper"| D
    D(["Report\nYYYY-MM-DD.md"]):::purple

    classDef red    fill:#b31b1b,color:#fff,stroke:none
    classDef dark   fill:#18181b,color:#fff,stroke:none
    classDef mid    fill:#27272a,color:#fff,stroke:none
    classDef purple fill:#3b0764,color:#fff,stroke:none
```

<br/>

<div align="center">
<table>
<tr>
<td align="center" width="175"><strong>TL;DR</strong><br/><sup>What the paper does<br/>in one sentence</sup></td>
<td align="center" width="175"><strong>Key Innovation</strong><br/><sup>The specific technique<br/>or finding that is new</sup></td>
<td align="center" width="175"><strong>Why It Matters</strong><br/><sup>What you can concretely<br/>build with this</sup></td>
<td align="center" width="175"><strong>Tags</strong><br/><sup><code>rag</code> &nbsp; <code>vision-language</code><br/><code>fine-tuning</code></sup></td>
<td align="center" width="175"><strong>Link</strong><br/><sup>Direct arXiv PDF,<br/>no paywalls</sup></td>
</tr>
</table>
</div>

<br/>

---

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

That's it. In ~30 seconds you get:

```
reports/
└── 2026-06-20.md    ← today's 3 papers, ranked and distilled
```

> **Want a different provider?** Set `LLM_API_BASE` and `LLM_MODEL` in `.env` to use OpenAI, Together, Mistral, or any OpenAI-compatible endpoint. No code changes needed.

---

## GitHub Actions Setup

<div align="center"><br/>
<strong>No server &nbsp;&middot;&nbsp; No infra &nbsp;&middot;&nbsp; No maintenance</strong><br/>
<sub>Push once — a fresh digest arrives in your repo every Thursday, automatically.</sub>
<br/><br/>

| | Step | |
|:---:|---|:---:|
| **1** | **Fork or push** this repo to your GitHub account | |
| **2** | Go to **Settings → Secrets and variables → Actions** | |
| **3** | Add the secret below — then you're done | ✅ |

</div>

<br/>

**Required secret**

```
LLM_API_KEY = gsk_...        ← your Groq key (free at console.groq.com)
```

**Optional — swap providers without touching any code**

| Secret | Example value | Effect |
|---|---|---|
| `LLM_API_BASE` | `https://api.openai.com/v1` | Point to OpenAI, Together, Mistral, Ollama… |
| `LLM_MODEL` | `gpt-4o-mini` | Override the model used for ranking & distilling |

<br/>

> **Run it right now →** go to **Actions → Distill Papers → Run workflow**

---

## Reference

### Why Groq?

Groq's LPU inference runs **~10× faster** than typical GPU inference — ranking 60 papers takes seconds, not minutes. The free tier covers all usage for this project. To use a different provider, set `LLM_API_BASE` and `LLM_MODEL` — no code changes needed.

### Configuration

| Variable | Required | Default | Notes |
|---|---|---|
| `LLM_API_KEY` | Yes | — | Your provider API key |
| `LLM_API_BASE` | No | `https://api.groq.com/openai/v1` | Any OpenAI-compatible endpoint |
| `LLM_MODEL` | No | `llama-3.3-70b-versatile` | Any model your provider supports |

### Resilience

Every failure mode is handled gracefully — a bad run never silently breaks the pipeline.

| Scenario | What happens |
|---|---|
| Report already exists for today | Skipped — no duplicate commits |
| LLM ranking fails | Falls back to first 3 fetched papers |
| Single paper distillation fails | Writes fallback summary, continues |
| `<!-- REPORT_INDEX -->` missing | Logs warning, skips safely |
| API rate limit hit | 3 retries with exponential backoff |

### Project Structure

```
ai-paper-scout/
├── .github/workflows/distill.yml   ──  cron: every Thursday at 09:00 UTC
├── scripts/distill.py               ──  fetch → rank → distil → commit
├── reports/YYYY-MM-DD.md            ──  one report per run
├── .env.example
├── requirements.txt
└── README.md
```

### Troubleshooting

**No papers fetched** — check connectivity to `export.arxiv.org` and confirm the `arxiv` package is installed.

**LLM API errors** — verify `LLM_API_KEY` is valid and matches the provider at `LLM_API_BASE`.

**README index not updating** — ensure `<!-- REPORT_INDEX -->` marker is present in this file.

**Workflow not triggering** — confirm GitHub Actions is enabled and the schedule is `0 9 * * 4`.

---

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
| May 30, 2026 | [→ read](reports/2026-05-30.md) |
<!-- REPORT_INDEX_END -->

</div>

---

<div align="center">
<sup>Built by <a href="https://github.com/mohabdelkarim">@mohabdelkarim</a> &middot; MIT License</sup>
</div>
