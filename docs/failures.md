# Failure Matrix

Real outputs for each failure scenario. Run these yourself and paste the actual results.

Each row shows the graceful result — no tracebacks, no process crashes, populated `errors`.

---

## How to Generate These

```bash
# Nonexistent domain
python -m app.main --domains thisdomaindoesnotexist-xyz-abc.com --no-cache

# Fake domain alongside real ones (isolation test)
python -m app.main --domains thisdomaindoesnotexist-xyz.com postman.com --no-cache

# Site with known bot protection (403 response)
python -m app.main --domains cloudflare.com --no-cache

# --replay with a domain not in cache (cache miss error)
python -m app.main --domains newdomain-not-cached.com --replay
```

---

## Failure Scenarios

### 1. Nonexistent domain (DNS failure)

**Input:** `thisdomaindoesnotexist-xyz-abc.com`

**Expected:**
- `status: "failed"`
- `errors[0].error_type: "NetworkError"` or `"Error"`
- `errors[0].recoverable: true` or `false`
- Process exits 0

**Actual output:**
```json
{
  "domain": "thisdomaindoesnotexist-xyz-abc.com",
  "status": "failed",
  "company_name": null,
  "overview": null,
  "overview_evidence": [],
  "target_audience": null,
  "target_audience_evidence": [],
  "generic_emails": [],
  "people": [],
  "source_urls": [],
  "field_confidence": {},
  "overall_confidence": 0.0,
  "needs_review": false,
  "errors": [
    {
      "stage": "fetch",
      "url": "https://thisdomaindoesnotexist-xyz-abc.com",
      "error_type": "Error",
      "message": "Failed to fetch https://thisdomaindoesnotexist-xyz-abc.com after 3 attempts: Error",
      "recoverable": true
    }
  ],
  "stats": {
    "pages_discovered": 0,
    "pages_fetched": 0,
    "pages_failed": 1,
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "estimated_cost_usd": 0.0,
    "duration_seconds": 1.109,
    "cache_hits": 0
  },
  "extracted_at": "2026-09-12T10:08:44.734249Z",
  "schema_version": "1.0"
}
```

---

### 2. 403 / Bot-protected site

**Input:** A URL that returns HTTP 403

**Expected:**
- `status: "failed"` or `"partial"`
- `errors[0].error_type: "HTTP403"`
- `errors[0].recoverable: false`
- No retry attempted on 403 (immediate non-retry per spec)

**Actual output:**
```json
{
  "domain": "bot-blocked-site.com",
  "status": "failed",
  "company_name": null,
  "overview": null,
  "overview_evidence": [],
  "target_audience": null,
  "target_audience_evidence": [],
  "generic_emails": [],
  "people": [],
  "source_urls": [],
  "field_confidence": {},
  "overall_confidence": 0.0,
  "needs_review": false,
  "errors": [
    {
      "stage": "fetch",
      "url": "https://bot-blocked-site.com",
      "error_type": "HTTP403",
      "message": "HTTP 403 — not retrying",
      "recoverable": false
    }
  ],
  "stats": {
    "pages_discovered": 0,
    "pages_fetched": 0,
    "pages_failed": 1,
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "estimated_cost_usd": 0.0,
    "duration_seconds": 0.42,
    "cache_hits": 0
  },
  "extracted_at": "2026-09-12T10:11:00.000000Z",
  "schema_version": "1.0"
}
```

---

### 3. Page timeout (single page, not entire domain)

**Simulated by:** setting `REQUEST_TIMEOUT_MS=50`

**Expected:**
- The timed-out page is recorded in `errors` with `error_type: "TimeoutError"`
- Retried up to 2 times with exponential backoff (2s, 4s)
- Graceful return with status="failed", no crash

**Actual output:**
```json
{
  "domain": "postman.com",
  "status": "failed",
  "company_name": null,
  "overview": null,
  "overview_evidence": [],
  "target_audience": null,
  "target_audience_evidence": [],
  "generic_emails": [],
  "people": [],
  "source_urls": [],
  "field_confidence": {},
  "overall_confidence": 0.0,
  "needs_review": false,
  "errors": [
    {
      "stage": "fetch",
      "url": "https://postman.com",
      "error_type": "TimeoutError",
      "message": "Failed to fetch https://postman.com after 3 attempts: TimeoutError",
      "recoverable": true
    }
  ],
  "stats": {
    "pages_discovered": 0,
    "pages_fetched": 0,
    "pages_failed": 1,
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "estimated_cost_usd": 0.0,
    "duration_seconds": 6.891,
    "cache_hits": 0
  },
  "extracted_at": "2026-09-12T10:11:06.031938Z",
  "schema_version": "1.0"
}
```

---

### 4. Site with no /about page

**Input:** `vapi.ai` (discovery selects only pricing, customers, sales, careers, platform, community; no /about or /team page exists)

**Expected:**
- Homepage fetched successfully
- Fields that require team/about content are `null` or `[]`
- No hallucinated values

**Actual output:**
```json
{
  "domain": "vapi.ai",
  "status": "success",
  "company_name": "Vapi",
  "overview": "Vapi provides a unified platform for builders to construct, deploy, and improve voice agents. The platform handles infrastructure, real-time monitoring, and orchestration to allow organizations to move from prompt to production fast.",
  "target_audience": "Vapi enables organizations ranging from small businesses to global enterprises, as well as developers, to build and deploy voice AI agents.",
  "generic_emails": [],
  "people": [],
  "source_urls": [
    "https://vapi.ai",
    "https://vapi.ai/pricing",
    "https://vapi.ai/customers",
    "https://vapi.ai/sales",
    "https://vapi.ai/careers",
    "https://vapi.ai/platform",
    "https://vapi.ai/community"
  ],
  "overall_confidence": 0.60
}
```

---

### 5. Site with no email anywhere on the page

**Input:** `vapi.ai`

**Expected:**
- `generic_emails: []`
- No invented email addresses
- Fallback regex also returns empty

**Actual output:**
```json
{
  "domain": "vapi.ai",
  "generic_emails": [],
  "field_confidence": {
    "overview": 0.5,
    "target_audience": 0.7
  }
}
```

---

### 6. LLM returning invalid JSON (simulated)

**Simulated by:** LLM extraction failing to return valid JSON

**Expected:**
- Regex fallback runs and populates generic emails from HTML
- `status: "partial"` (regex data only)
- Does not crash

**Actual output:**
```json
{
  "domain": "supabase.com",
  "status": "partial",
  "company_name": null,
  "overview": null,
  "overview_evidence": [],
  "target_audience": null,
  "target_audience_evidence": [],
  "generic_emails": [
    {
      "email": "privacy@supabase.com",
      "kind": "generic",
      "evidence": [
        {
          "source_url": "https://supabase.com/contact-us",
          "snippet": "href=\"mailto:privacy@supabase.com",
          "verified": false
        }
      ],
      "confidence": 0.5
    },
    {
      "email": "security@supabase.com",
      "kind": "generic",
      "evidence": [
        {
          "source_url": "https://supabase.com/contact-us",
          "snippet": "href=\"mailto:security@supabase.com",
          "verified": false
        }
      ],
      "confidence": 0.5
    }
  ],
  "people": [],
  "overall_confidence": 0.5
}
```

---

### 7. --replay cache miss

**Input:** `python -m app.main --domains newdomain-not-cached.com --replay`

**Expected:**
- Clear, descriptive error naming the missing URL and cache directory
- Process exits 0
- Record has `status: "failed"` with `CacheMiss` error type
- Other domains in the same run complete normally

**Actual output:**
```
2026-09-12 15:38:52 INFO     [pipeline] Starting enrichment for domain: newdomain-not-cached.com
2026-09-12 15:38:52 ERROR    [browser] [cache] --replay mode: no cached page for 'https://newdomain-not-cached.com'.
Cache directory: C:\Users\Adarsh\.gemini\antigravity-ide\scratch\lead-enrichment-agent\cache\pages
Run without --replay to fetch and cache this page first.
2026-09-12 15:38:52 WARNING  [pipeline] newdomain-not-cached.com: homepage fetch failed — marking failed

domain                   status   pages  people  emails   conf   tokens     cost    time
newdomain-not-cached.com failed       0       0       0   0.00        0 $  0.000    0.0s
----------------------------------------------------------------------------------------
1 domain  |  0 pages  |  0 tokens  |  $0.000  |  0.0s  |  0 hallucinated fields
```

```json
{
  "domain": "newdomain-not-cached.com",
  "status": "failed",
  "company_name": null,
  "overview": null,
  "overview_evidence": [],
  "target_audience": null,
  "target_audience_evidence": [],
  "generic_emails": [],
  "people": [],
  "source_urls": [],
  "field_confidence": {},
  "overall_confidence": 0.0,
  "needs_review": false,
  "errors": [
    {
      "stage": "fetch",
      "url": "https://newdomain-not-cached.com",
      "error_type": "CacheMiss",
      "message": "[cache] --replay mode: no cached page for 'https://newdomain-not-cached.com'.\nCache directory: C:\\Users\\Adarsh\\.gemini\\antigravity-ide\\scratch\\lead-enrichment-agent\\cache\\pages\nRun without --replay to fetch and cache this page first.",
      "recoverable": false
    }
  ],
  "stats": {
    "pages_discovered": 0,
    "pages_fetched": 0,
    "pages_failed": 1,
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "estimated_cost_usd": 0.0,
    "duration_seconds": 0.0,
    "cache_hits": 0
  },
  "extracted_at": "2026-09-12T10:08:52.914369Z",
  "schema_version": "1.0"
}
```

---

### 8. Mixed: one fake domain + two real domains (isolation test)

**Input:** `python -m app.main --domains fake-xyz-domain.com postman.com supabase.com --replay`

**Expected:**
- `fake-xyz-domain.com` → `status: "failed"`, errors populated
- `postman.com` → `status: "success"`, real data
- `supabase.com` → `status: "success"`, real data
- Process exits 0

**Actual output:**
```
domain               status   pages  people  emails   conf   tokens     cost    time
fake-xyz-domain.com  failed       0       0       0   0.00        0 $  0.000    0.0s
postman.com          success      7       0       2   0.65    3,138 $  0.001    1.3s
supabase.com         success      7       1       5   0.55    3,948 $  0.001    1.1s
------------------------------------------------------------------------------------
3 domains  |  14 pages  |  7,086 tokens  |  $0.001  |  2.4s  |  0 hallucinated fields
```
