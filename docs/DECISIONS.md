# Architecture & Design Decisions

Six decisions worth explaining. Each follows the pattern: **Decision → Reason → What I'd change at scale**.

---

## 1. Playwright over Selenium

**Decision:** Use Playwright (sync API) for headless browser automation.

**Reason:** Playwright's `wait_until="networkidle"` + a 1.5s settle reliably captures late-hydrating React/Next.js content that Selenium's older model misses. The async API in Playwright is excellent, but the sync API is cleaner for a sequential, single-domain-at-a-time pipeline where there's no concurrency benefit to unlock. `playwright install chromium` in one command beats Selenium's chromedriver version-matching pain.

**At scale:** Switch to the async API and use `asyncio.gather` across pages within a domain. At very high volume, swap to a managed browser pool (e.g., Browserless.io) to avoid managing Chromium instances on worker nodes.

---

## 2. Sequential over Concurrent

**Decision:** Process domains one at a time; no threading, asyncio, or multiprocessing.

**Reason:** The spec asks for restraint here, and it's the right call for a take-home: concurrent code introduces race conditions, makes errors harder to attribute, and massively increases review complexity. The pipeline is I/O-bound on network calls and LLM API latency, which are the obvious future parallelisation wins — but they're not free, and adding them without needing them is cleverness. The pipeline for three domains takes under 60 seconds; that's fast enough to be credible without concurrency.

**At scale:** Async I/O within a domain (parallel page fetches), process-level parallelism across domains using `concurrent.futures.ProcessPoolExecutor`. Each domain is already fully self-contained with its own error records and stats, so isolation is free.

---

## 3. Rule-based Confidence over LLM Self-scoring

**Decision:** Compute confidence from a deterministic scoring table, never by asking the LLM to rate its own output.

**Reason:** LLMs are empirically poorly calibrated at self-scoring — they tend to assign high confidence to hallucinated values and show no systematic relationship between expressed confidence and accuracy. A table of verifiable signals (verified snippet, page type match, corroboration, format validity) produces an auditable, reproducible score that a reviewer can check line-by-line. It also keeps the "hallucinated fields = 0" claim defensible: if an unverified snippet lowers the score, we know exactly why.

**At scale:** Train a lightweight classifier on a labelled set of (field, evidence, ground_truth) tuples. The deterministic table serves as the feature set; the classifier learns the weights from real data rather than intuition.

---

## 4. One LLM Call per Domain over One Call per Page

**Decision:** Concatenate all cleaned pages into a single user message and make one LLM call per domain.

**Reason:** One call per page would cost 6× more in tokens and 6× more in latency. More importantly, cross-page context is valuable: the LLM can reconcile a person's name found on `/team` with their email on `/contact`, which a per-page call cannot do. The 18K character domain budget keeps the combined message well within GPT-4o-mini's 128K context.

**At scale:** For very large sites (enterprise companies with 50+ relevant pages), a two-pass approach makes sense: a fast, cheap first pass to rank page relevance, then a second pass with the top N pages. This is not needed at the 6-page budget.

---

## 5. Generic Emails Only — a Product Decision, Not a Limitation

**Decision:** Accept only role-based/generic email prefixes (`info@`, `contact@`, `sales@`, etc.). Personal emails are dropped before storage.

**Reason:** This is deliberate. Personal emails sourced from a public website crawler are almost always either: (a) someone's support alias that forwards to a queue anyway, or (b) a data point that violates GDPR Article 6 without a lawful basis. The risk of burning a relationship with a cold email to `j.doe@enterprise.com` scraped from a press release is higher than the value of the lead. Generic addresses go to monitored inboxes; they have better deliverability; they don't get someone in trouble. The allow-list is in `config.py::GENERIC_EMAIL_PREFIXES` and is easy to extend.

**At scale:** Integrate a compliant enrichment provider (e.g., Apollo, Hunter.io) for verified personal contacts where consent is established. The pipeline feeds them the role; the provider handles the contact.

---

## 6. No Framework (LangChain / LlamaIndex / CrewAI)

**Decision:** No orchestration framework. Linear six-stage pipeline in pure Python.

**Reason:** The task is a linear ETL pipeline with a fixed schema, not an agent loop that needs dynamic tool selection. Introducing LangChain here would add 15,000 lines of framework code to trace through when something goes wrong, replace explicit Python function calls with config-driven chains that are harder to test, and signal to the reviewer that the framework is doing the thinking. Every stage here is a plain function with a typed signature. The error taxonomy, confidence scoring, and evidence verification are all custom logic that a framework would obscure rather than enable.

**At scale:** If the extraction tasks become non-linear (e.g., "if you can't find the CEO on the team page, try the about page, then the blog, then press releases") an agent loop with tool use becomes the right model. Not before.
