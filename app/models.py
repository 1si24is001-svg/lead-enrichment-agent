"""
app/models.py
=============
Pydantic v2 schemas — the contract of the system.

Every module in the pipeline speaks this language. Change these models carefully:
any field rename is a breaking change to cached LLM responses and stored output.

Schema version: 1.0
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, field_validator


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------

class Evidence(BaseModel):
    """A single piece of grounding for any extracted value.

    The snippet MUST be copied verbatim (<= 300 chars) from the cleaned page
    text at source_url.  verify.py sets `verified` after checking the snippet
    actually appears in the cached source.
    """

    source_url: str
    snippet: str  # <= 300 chars, VERBATIM from the cleaned page text
    verified: bool = False  # set by verify.py

    @field_validator("snippet")
    @classmethod
    def snippet_max_length(cls, v: str) -> str:
        if len(v) > 300:
            raise ValueError("Evidence snippet must be <= 300 characters (must be verbatim from source).")
        return v


# ---------------------------------------------------------------------------
# EmailHit
# ---------------------------------------------------------------------------

class EmailHit(BaseModel):
    """A confirmed generic/role-based email address found on the site.

    Personal emails are dropped before storage — this is a deliberate product
    decision.  The `kind` field is always "generic"; it exists so consumers of
    the output can trust that any stored email passed the allow-list filter.
    """

    email: EmailStr
    kind: Literal["generic"]  # personal emails are dropped, never stored
    evidence: list[Evidence] = []
    confidence: float = 0.0


# ---------------------------------------------------------------------------
# Person
# ---------------------------------------------------------------------------

class Person(BaseModel):
    """A named individual found on the company's own pages.

    Roles and LinkedIn URLs are stored exactly as written on the page.
    linkedin_url is only populated when the URL appears in page text;
    we never crawl LinkedIn directly.
    """

    name: str
    role: str | None = None
    linkedin_url: str | None = None
    evidence: list[Evidence] = []
    confidence: float = 0.0


# ---------------------------------------------------------------------------
# ErrorRecord
# ---------------------------------------------------------------------------

class ErrorRecord(BaseModel):
    """A structured record of any failure within the pipeline.

    Errors are collected, never re-raised.  The pipeline always returns a
    CompanyRecord even when every stage fails; in that case status="failed"
    and this list explains why.
    """

    stage: Literal["discovery", "fetch", "clean", "llm", "validate", "output"]
    url: str | None = None
    error_type: str  # e.g. "TimeoutError", "HTTP404", "Blocked403", "LLMRateLimit"
    message: str
    recoverable: bool


# ---------------------------------------------------------------------------
# RunStats
# ---------------------------------------------------------------------------

class RunStats(BaseModel):
    """Accounting metrics for a single domain run.

    Token counts and cost are cumulative across all LLM calls for this domain.
    cache_hits counts pages served from disk rather than the network.
    """

    pages_discovered: int = 0
    pages_fetched: int = 0
    pages_failed: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    estimated_cost_usd: float = 0.0
    duration_seconds: float = 0.0
    cache_hits: int = 0


# ---------------------------------------------------------------------------
# CompanyRecord  (top-level output unit)
# ---------------------------------------------------------------------------

class CompanyRecord(BaseModel):
    """One enriched company record — the atomic output of the pipeline.

    Status rules
    ------------
    success : homepage fetched, LLM returned valid output, no unrecoverable errors.
    partial : usable record but something failed (pages unreachable, field empty).
    failed  : no usable data; `errors` explains why.

    Every non-null value MUST have at least one Evidence entry.
    overall_confidence is the mean of all populated field_confidence values.
    Any field or record below REVIEW_THRESHOLD sets needs_review=True and
    writes an entry to review_queue.json.
    """

    domain: str
    status: Literal["success", "partial", "failed"]

    # Core extracted fields
    company_name: str | None = None
    overview: str | None = None  # EXACTLY two sentences
    overview_evidence: list[Evidence] = []

    target_audience: str | None = None  # one sentence, grounded in page text
    target_audience_evidence: list[Evidence] = []

    generic_emails: list[EmailHit] = []
    people: list[Person] = []

    # Provenance
    source_urls: list[str] = []

    # Confidence
    field_confidence: dict[str, float] = {}  # per-field 0.0–1.0
    overall_confidence: float = 0.0
    needs_review: bool = False

    # Diagnostics
    errors: list[ErrorRecord] = []
    stats: RunStats

    # Metadata
    extracted_at: datetime
    schema_version: str = "1.0"


# ---------------------------------------------------------------------------
# LLMResponse  (internal — not persisted in output.json)
# ---------------------------------------------------------------------------

class LLMResponse(BaseModel):
    """Raw response from an LLM provider call.

    Kept internal to the pipeline; not written to output.json.
    The `data` dict is parsed into CompanyRecord sub-models downstream.
    """

    data: dict  # parsed JSON from the model
    prompt_tokens: int
    completion_tokens: int
    model: str
    raw: str  # the raw response string for debugging
