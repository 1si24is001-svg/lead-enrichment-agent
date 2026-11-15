"""
app/extract/confidence.py
=========================
Deterministic, rule-based confidence scoring.

Why rule-based?
---------------
LLMs are poorly calibrated at self-scoring — their confidence numbers are
not reliable.  Every point in this scoring table corresponds to a verifiable
signal, making the score auditable and reproducible.  Documented in
docs/DECISIONS.md.

Scoring table
-------------
| Signal                                                                              | Points |
|-------------------------------------------------------------------------------------|--------|
| Evidence snippet present AND verified in source (verify.py set verified=True)      |  +0.40 |
| Source page type matches expectation (emails from /contact, people from /team etc.) |  +0.20 |
| Corroborated by the regex fallback (fallback.py also found this value)             |  +0.20 |
| Value found on >= 2 distinct pages                                                 |  +0.10 |
| Passes format validation (valid email / valid LinkedIn URL / overview = 2 sentences)|  +0.10 |

Cap at 1.0, round to 2dp.
overall_confidence = mean of all populated field scores.
Any field below REVIEW_THRESHOLD sets needs_review=True.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from app.config import Settings
from app.models import CompanyRecord, EmailHit, Evidence, Person

logger = logging.getLogger(__name__)

# Points table
VERIFIED_EVIDENCE_POINTS: float = 0.40
PAGE_TYPE_MATCH_POINTS: float = 0.20
CORROBORATION_POINTS: float = 0.20
MULTI_PAGE_POINTS: float = 0.10
FORMAT_VALID_POINTS: float = 0.10

# Page-type expectations: field → list of URL path fragments that are "expected" sources
FIELD_PAGE_TYPE_MAP: dict[str, list[str]] = {
    "generic_emails": ["contact", "contact-us", "support", "hello"],
    "people": ["team", "about", "about-us", "leadership", "management", "founders", "people"],
    "overview": ["about", "about-us", "company", "who-we-are", "home"],
    "target_audience": ["about", "pricing", "customers", "home"],
}

_LINKEDIN_URL_PATTERN = re.compile(
    r"https?://(?:www\.)?linkedin\.com/(in|company)/[a-zA-Z0-9\-_%]+/?",
    re.IGNORECASE,
)


def score_record(
    record: CompanyRecord,
    fallback_emails: list[EmailHit],
    fallback_linkedin: list[str],
    settings: Settings,
) -> CompanyRecord:
    """Compute and attach confidence scores to a CompanyRecord.

    Mutates record.field_confidence, record.overall_confidence,
    record.needs_review, and each item's .confidence in-place.
    Returns the mutated record.
    """
    field_scores: dict[str, float] = {}

    # Score overview
    if record.overview:
        s = score_field(
            "overview",
            record.overview,
            record.overview_evidence,
            fallback_value=None,
        )
        field_scores["overview"] = s

    # Score target_audience
    if record.target_audience:
        s = score_field(
            "target_audience",
            record.target_audience,
            record.target_audience_evidence,
            fallback_value=None,
        )
        field_scores["target_audience"] = s

    # Score each email
    email_scores: list[float] = []
    for hit in record.generic_emails:
        s = score_email(hit, fallback_emails)
        hit.confidence = s
        email_scores.append(s)
    if email_scores:
        field_scores["generic_emails"] = sum(email_scores) / len(email_scores)

    # Score each person
    person_scores: list[float] = []
    for person in record.people:
        s = score_person(person, fallback_linkedin)
        person.confidence = s
        person_scores.append(s)
    if person_scores:
        field_scores["people"] = sum(person_scores) / len(person_scores)

    # Attach to record
    record.field_confidence = {k: round(v, 2) for k, v in field_scores.items()}

    if field_scores:
        record.overall_confidence = round(
            sum(field_scores.values()) / len(field_scores), 2
        )
    else:
        record.overall_confidence = 0.0

    # Flag for review
    below_threshold = (
        record.overall_confidence < settings.review_threshold
        or any(v < settings.review_threshold for v in field_scores.values())
    )
    record.needs_review = below_threshold

    return record


def score_email(
    hit: EmailHit,
    fallback_emails: list[EmailHit],
) -> float:
    """Compute confidence for a single EmailHit."""
    if not hit.evidence and hit.email.lower() not in {e.email.lower() for e in fallback_emails}:
        return 0.0

    score = 0.0

    # Verified evidence
    if _has_verified_evidence(hit.evidence):
        score += VERIFIED_EVIDENCE_POINTS

    # Page type match
    if _source_url_matches_expectation("generic_emails", hit.evidence):
        score += PAGE_TYPE_MATCH_POINTS

    # Corroboration by regex fallback
    fallback_addresses = {e.email.lower() for e in fallback_emails}
    if hit.email.lower() in fallback_addresses:
        score += CORROBORATION_POINTS

    # Multi-page coverage
    if _multi_page_coverage(hit.evidence):
        score += MULTI_PAGE_POINTS

    # Format validation (email format + generic prefix)
    from app.config import GENERIC_EMAIL_PREFIXES
    local = hit.email.split("@")[0].lower() if "@" in hit.email else ""
    if local in GENERIC_EMAIL_PREFIXES and hit.evidence:
        score += FORMAT_VALID_POINTS

    return _cap(score)


def score_person(
    person: Person,
    fallback_linkedin: list[str],
) -> float:
    """Compute confidence for a single Person."""
    score = 0.0

    # Verified evidence
    if _has_verified_evidence(person.evidence):
        score += VERIFIED_EVIDENCE_POINTS

    # Page type match
    if _source_url_matches_expectation("people", person.evidence):
        score += PAGE_TYPE_MATCH_POINTS

    # LinkedIn corroboration (person has a LI URL that's in fallback)
    if person.linkedin_url and person.linkedin_url in fallback_linkedin:
        score += CORROBORATION_POINTS

    # Multi-page coverage
    if _multi_page_coverage(person.evidence):
        score += MULTI_PAGE_POINTS

    # Format validation: valid LinkedIn URL if present
    if person.linkedin_url:
        if _LINKEDIN_URL_PATTERN.match(person.linkedin_url):
            score += FORMAT_VALID_POINTS
    else:
        # No LinkedIn URL is fine — give format points if name is non-empty
        if person.name and person.name.strip():
            score += FORMAT_VALID_POINTS

    return _cap(score)


def score_field(
    field_name: str,
    value: Any,
    evidence: list[Evidence],
    fallback_value: Any = None,
) -> float:
    """Generic field scorer for string-value fields (overview, target_audience, etc.)."""
    score = 0.0

    if not value or not evidence:
        return score

    # Verified evidence
    if _has_verified_evidence(evidence):
        score += VERIFIED_EVIDENCE_POINTS

    # Page type match
    if _source_url_matches_expectation(field_name, evidence):
        score += PAGE_TYPE_MATCH_POINTS

    # Corroboration (fallback_value provided means regex also found something)
    if fallback_value is not None:
        score += CORROBORATION_POINTS

    # Multi-page coverage
    if _multi_page_coverage(evidence):
        score += MULTI_PAGE_POINTS

    # Format validation
    if field_name == "overview" and _is_valid_overview(value):
        score += FORMAT_VALID_POINTS
    elif field_name == "target_audience" and isinstance(value, str) and value.strip():
        # One-sentence check: ends with period and has no more than one sentence boundary
        stripped = value.strip()
        sentence_boundaries = re.split(r"[.!?]+\s+", stripped)
        if len([s for s in sentence_boundaries if s.strip()]) == 1:
            score += FORMAT_VALID_POINTS

    return _cap(score)


def _has_verified_evidence(evidence: list[Evidence]) -> bool:
    """Return True if at least one evidence snippet is verified."""
    return any(e.verified for e in evidence)


def _source_url_matches_expectation(field_name: str, evidence: list[Evidence]) -> bool:
    """Return True if any evidence URL contains an expected path fragment."""
    expected_paths = FIELD_PAGE_TYPE_MAP.get(field_name, [])
    for ev in evidence:
        url_lower = ev.source_url.lower()
        if any(path in url_lower for path in expected_paths):
            return True
    return False


def _multi_page_coverage(evidence: list[Evidence]) -> bool:
    """Return True if evidence comes from >= 2 distinct source URLs."""
    urls = {e.source_url for e in evidence}
    return len(urls) >= 2


def _is_valid_overview(text: str | None) -> bool:
    """Return True if text contains exactly two sentences."""
    if not text:
        return False
    sentences = re.split(r"[.!?]+\s+", text.strip().rstrip(".!?"))
    return len([s for s in sentences if s.strip()]) == 2


def _cap(score: float) -> float:
    """Cap score at 1.0 and round to 2 decimal places."""
    return round(min(score, 1.0), 2)
