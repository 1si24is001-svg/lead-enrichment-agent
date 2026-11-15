"""
app/extract/verify.py
=====================
Anti-hallucination verification guard.

For every Evidence object attached to any field, this module checks that the
snippet actually appears in the cleaned source text for that URL.

Comparison is normalised: collapse whitespace, case-insensitive.

Outcome
-------
- verified=True  : snippet found in source text.
- verified=False : snippet NOT found; a warning is logged with field name.
  The field loses its evidence points in confidence scoring.

The verified-snippet percentage is included in the run summary.
This is a headline feature of the system: it proves the LLM grounded its
answers in the actual page text rather than prior knowledge.
"""

from __future__ import annotations

import logging
import re

from app.models import Evidence, CompanyRecord

logger = logging.getLogger(__name__)


def normalise_for_comparison(text: str) -> str:
    """Collapse whitespace and lowercase for snippet matching."""
    return re.sub(r"\s+", " ", text).strip().lower()


def verify_evidence(
    record: CompanyRecord,
    cleaned_pages: dict[str, str],
) -> tuple[int, int]:
    """Check every evidence snippet against its source page.

    Mutates Evidence.verified in-place.

    Parameters
    ----------
    record:
        The CompanyRecord whose evidence objects will be verified.
    cleaned_pages:
        {url: cleaned_text} — the same text that was sent to the LLM.

    Returns
    -------
    tuple[int, int]
        (verified_count, total_count)
    """
    all_evidence = collect_all_evidence(record)
    verified = 0
    total = len(all_evidence)

    for field_name, ev in all_evidence:
        result = _check_snippet(ev.snippet, ev.source_url, cleaned_pages)
        ev.verified = result
        if result:
            verified += 1
        else:
            logger.warning(
                "[verify] Unverified snippet for field %r from %s: %r",
                field_name, ev.source_url, ev.snippet[:80],
            )

    if total > 0:
        pct = 100 * verified // total
        logger.info("[verify] %s/%s snippets verified (%d%%)", verified, total, pct)

    return verified, total


def _check_snippet(snippet: str, source_url: str, cleaned_pages: dict[str, str]) -> bool:
    """Return True if snippet (normalised) is found in the page text for source_url."""
    page_text = cleaned_pages.get(source_url)
    if page_text is None:
        # Try case-insensitive URL match as a fallback
        source_lower = source_url.lower().rstrip("/")
        for url, text in cleaned_pages.items():
            if url.lower().rstrip("/") == source_lower:
                page_text = text
                break

    if page_text is None:
        return False

    norm_snippet = normalise_for_comparison(snippet)
    norm_page = normalise_for_comparison(page_text)
    return norm_snippet in norm_page


def collect_all_evidence(record: CompanyRecord) -> list[tuple[str, Evidence]]:
    """Return a flat list of (field_name, Evidence) pairs from a CompanyRecord."""
    pairs: list[tuple[str, Evidence]] = []

    for ev in record.overview_evidence:
        pairs.append(("overview", ev))

    for ev in record.target_audience_evidence:
        pairs.append(("target_audience", ev))

    for email_hit in record.generic_emails:
        for ev in email_hit.evidence:
            pairs.append(("generic_emails", ev))

    for person in record.people:
        for ev in person.evidence:
            pairs.append(("people", ev))

    return pairs
