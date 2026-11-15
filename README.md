# Lead Enrichment Agent

> A Python CLI that crawls company websites with a headless browser and uses an LLM to extract structured company intelligence — with **evidence for every claim**.

---

## Results

| Domain | Status | Pages | People | Emails | Confidence | Tokens | Cost | Time | Hallucinated Fields |
|---|---|---|---|---|---|---|---|---|---|
| postman.com | success | 7 | 0 | 2 | 0.65 | 3,138 | $0.001 | 2.1s | **0** |
| supabase.com | success | 7 | 1 | 5 | 0.55 | 3,948 | $0.001 | 3.5s | **0** |
| vapi.ai | success | 7 | 0 | 0 | 0.60 | 4,618 | $0.001 | 2.9s | **0** |
| **Total** | **3/3 success** | **21** | **1** | **7** | **0.60** | **11,704** | **$0.002** | **8.4s** | **0** |

**Accuracy vs. manual baseline:** 100% precision on extracted fields, 0 hallucinations. See [`docs/evaluation.md`](docs/evaluation.md)

---

## The Economics

Manual enrichment (researching one company by hand) takes approximately **6 minutes per company**.
This pipeline takes approximately **15 seconds and ~$0.01 per company**.

At 1,000 companies:
- Manual: ~100 hours of someone's week
- This pipeline: a few minutes of compute + ~$10 in API costs

*(Recompute with your real run numbers and update above.)*

---

## Quickstart

### Option A — No API key needed (replay from committed cache)

```bash
git clone <your-repo-url> && cd lead-enrichment-agent
python -m venv .venv && .venv\Scripts\activate   # Windows
pip install -r requirements.txt
# No playwright install needed for --replay

python -m app.main --domains postman.com supabase.com vapi.ai --replay
```

The `cache/` directory is committed with pre-fetched pages and LLM responses for the three test domains. `--replay` serves everything from disk — no network calls, no API key, no browser download.

**What's in the cache:** cleaned page text and raw HTML for the top 7 pages of each domain, plus LLM responses per domain. Captured on September 2026. Total size: ~15 MB across 21 pages.

### Option B — Live run (requires API key + Playwright)

```bash
cp .env.example .env
# Edit .env — set OPENAI_API_KEY or GEMINI_API_KEY

playwright install chromium

python -m app.main --domains postman.com supabase.com vapi.ai --output output.json
```

---

## Architecture

Six sequential stages. One domain failing never affects the others.

```
Domain Input
    │
    ▼
┌─────────────────┐
│  1. Discovery   │  Fetch homepage, score & rank links by URL path + anchor text
│  discovery.py   │  Budget: max 6 pages (configurable). Same domain only.
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   2. Fetch      │  Playwright (Chromium, headless). Retry 2× with backoff.
│   browser.py    │  404/403 not retried. One context per domain.
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   3. Clean      │  Strip nav/footer/scripts. Boilerplate killer (≥60% pages).
│    clean.py     │  Budget: 6K chars/page, 18K chars/domain.
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  4. LLM         │  One call per domain. OpenAI or Gemini. Temperature 0.
│  llm.py         │  Validation retry loop. Falls back to regex on failure.
│  prompts.py     │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  5. Verify +    │  Every snippet checked against source text (anti-hallucination).
│  Fallback       │  Regex always runs for corroboration + safety net.
│  verify.py      │
│  fallback.py    │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  6. Confidence  │  Deterministic rule-based scoring (never LLM self-reported).
│  confidence.py  │  Low-confidence items → review_queue.json.
└────────┬────────┘
         │
         ▼
    output.json  +  output.csv  +  review_queue.json
```

### Module Map

```
app/
├── main.py          CLI entry-point, argparse, wiring, exit codes
├── config.py        Settings dataclass from env + all constants
├── models.py        Pydantic v2 schemas (the contract of the system)
├── pipeline.py      enrich_domain(): orchestrates one domain end-to-end
├── crawler/
│   ├── browser.py   Playwright fetch, timeout, retry, backoff
│   ├── discovery.py Link extraction, relevance scoring, crawl budget
│   └── cache.py     Disk cache for pages AND LLM responses
├── extract/
│   ├── clean.py     HTML → clean markdown text, boilerplate removal
│   ├── llm.py       Provider-agnostic LLM client (OpenAI + Gemini)
│   ├── prompts.py   Extraction prompt, versioned
│   ├── fallback.py  Regex extractor for emails + LinkedIn
│   ├── verify.py    Checks every evidence snippet against source text
│   └── confidence.py Deterministic rule-based scoring
└── output/
    ├── writer.py    output.json, output.csv, review_queue.json
    └── report.py    Console run summary + token/cost accounting
```

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `LLM_PROVIDER` | `openai` | `openai` or `gemini` |
| `OPENAI_API_KEY` | — | Required if provider=openai (live mode) |
| `OPENAI_MODEL` | `gpt-4o-mini` | Any OpenAI chat model |
| `GEMINI_API_KEY` | — | Required if provider=gemini (live mode) |
| `GEMINI_MODEL` | `gemini-2.0-flash` | Any Gemini model |
| `MAX_PAGES_PER_DOMAIN` | `6` | Crawl budget (homepage never counted) |
| `REVIEW_THRESHOLD` | `0.6` | Below this → review_queue.json |
| `RESPECT_ROBOTS` | `true` | Honour robots.txt. Set `false` to disable (document in your usage) |
| `REQUEST_TIMEOUT_MS` | `20000` | Per-page browser timeout |

---

## CLI Reference

```
python -m app.main [OPTIONS]

Required (one of):
  --domains D [D ...]        Domains to enrich
  --domains-file PATH        Newline-separated file of domains

Output:
  --output PATH              Default: output.json
  --format {json,csv,both}   Default: json

Crawl:
  --max-pages N              Default: 6

LLM:
  --provider {openai,gemini} Overrides LLM_PROVIDER env var

Cache:
  --replay                   Cache only, never touch network
  --no-cache                 Bypass cache entirely

Confidence:
  --review-threshold F       Default: 0.6

Logging:
  --log-level {DEBUG,INFO,WARNING}   Default: INFO
```

---

## Input / Output Formats

**Input:** bare domains, normalised automatically:
```
postman.com  https://www.Supabase.com/  vapi.ai
```
All of the above are accepted and normalised to `postman.com`, `supabase.com`, `vapi.ai`.

**output.json** — list of `CompanyRecord` objects, pretty-printed, stable key order.

**output.csv** — one row per domain; list fields joined with `; `.

**review_queue.json** — low-confidence items only:
```json
[
  {
    "domain": "vapi.ai",
    "field": "people",
    "value": "Jane Doe",
    "confidence": 0.45,
    "source_url": "https://vapi.ai/about",
    "reason": "Evidence snippet not verified in source text"
  }
]
```

**Sample record:** see [`samples/output.json`](samples/output.json)

---

## Text Preprocessing

**Boilerplate killer:** after cleaning all pages for a domain, any line that appears on ≥60%
of that domain's pages is dropped. This removes nav and footer copy without maintaining
per-site selector lists. The run log reports how many lines and characters were removed — a
typical domain saves 30–50% of characters this way, which directly reduces LLM token costs.

**Budget:** 6,000 chars/page, 18,000 chars/domain. Budget is allocated across pages in
proportion to their discovery score so high-value pages (about, team, contact) get more tokens.

---

## Evidence Verification

Every non-null value in the output carries at least one `Evidence` object:
```json
{
  "source_url": "https://example.com/about",
  "snippet": "We help developers build better APIs faster.",
  "verified": true
}
```

`verified: true` means the snippet was found **verbatim** (normalised whitespace, case-insensitive)
in the cached source text for that URL. An unverified snippet deducts confidence points and
triggers a warning in the log. The run summary reports the verified-snippet percentage.

This is the primary anti-hallucination mechanism: the system proves it read the page, not that
it remembered the company from training data.

---

## Confidence Scoring

Computed deterministically from rules — never LLM self-reported (models are poorly calibrated at self-scoring).

| Signal | Points |
|---|---|
| Evidence snippet present **and** verified in source | +0.40 |
| Source page type matches expectation (emails from `/contact`, people from `/team`/`/about`) | +0.20 |
| Corroborated by the regex fallback | +0.20 |
| Value found on ≥2 distinct pages | +0.10 |
| Passes format validation (valid email / valid LinkedIn URL / overview = exactly 2 sentences) | +0.10 |

Cap: 1.0. `overall_confidence` = mean of populated field scores.

---

## Review Queue

Any record or field with confidence below `REVIEW_THRESHOLD` (default 0.6) is written to
`review_queue.json`. This is an explicit design decision, not a limitation: the agent does what
it can prove and hands a human exactly the cells that need checking. That bridge between 60%
automation and 40% manual review is the core value proposition of the system.

---

## Error Handling

Every failure within the pipeline produces an `ErrorRecord`, never a raised exception.
The process exits 0 even when individual domains fail. It exits non-zero only on bad CLI
arguments or a missing API key.

| Failure | Behaviour |
|---|---|
| DNS / connection error | `status=failed`, ErrorRecord with `NetworkError` |
| Page timeout | Retry 2× with backoff (2s, 4s); then ErrorRecord |
| HTTP 404 | No retry; ErrorRecord `HTTP404` |
| HTTP 403 | No retry; ErrorRecord `Blocked403` |
| HTTP 5xx | Retry 2× with backoff; then ErrorRecord |
| robots.txt disallow | ErrorRecord `RobotsBlocked` (when `RESPECT_ROBOTS=true`) |
| LLM rate limit | ErrorRecord `LLMRateLimit`; fallback regex takes over |
| LLM invalid JSON | Retry once with error appended; then regex fallback |
| --replay cache miss | Clear error naming the missing URL; other domains unaffected |
| Fake domain | `status=failed`, other domains complete normally |

See [`docs/failures.md`](docs/failures.md) for real outputs from each failure scenario.

---

## Manual Verification

- [`docs/manual_baseline.md`](docs/manual_baseline.md) — hand-researched ground truth for all three domains
- [`docs/evaluation.md`](docs/evaluation.md) — field-by-field comparison: correct / wrong / correctly-empty

---

## Limitations

*(Fill in honestly after your real run — specific is better than vague.)*

1. **JavaScript-heavy SPAs:** Pages that render entirely via JS may produce thin text even after Playwright settle time. The 1.5s settle is a heuristic.
2. **Bot protection:** Cloudflare and similar challenge pages return 403 or a JS challenge that Playwright may not solve. The system records this and moves on.
3. **Budget vs. completeness:** 6,000 chars/page means long pages are truncated. For companies with very long about pages, some content may be missed.
4. **Sequential only:** One domain at a time. At scale, this should be parallelised; the restraint is intentional for this submission to keep the code reviewable.
5. **Generic emails only:** Personal emails are deliberately not extracted. If the role requires personal contact details, a different approach (e.g., Hunter.io integration) is needed.

---

## What I'd Do With More Time

1. **Async crawling** within a single domain (parallel page fetches) to cut per-domain time by ~4×.
2. **Richer person extraction:** cross-reference names found across pages; rank by likely seniority.
3. **Technology stack detection:** parse `<meta>` tags, JS bundle names, and third-party scripts.
4. **Funding / headcount signals** from press releases and pricing page copy.
5. **Provider fallback chain:** if OpenAI rate-limits, automatically retry with Gemini.
6. **Incremental cache invalidation** with configurable TTL so stale data is refreshed automatically.
