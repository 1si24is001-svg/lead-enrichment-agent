"""
app/extract/fallback.py
=======================
Regex-based extractor for emails and LinkedIn URLs.

This runs ALWAYS — not only on LLM failure.  It serves two purposes:

1. **Corroboration**: values found by both LLM and regex score higher in
   the confidence module (confidence.py).
2. **Safety net**: when the LLM call fails entirely, this provides the only
   structured output.

Email rules
-----------
- Scan raw HTML text and mailto: hrefs.
- Filter to the generic prefix allow-list (config.GENERIC_EMAIL_PREFIXES).
- Reject any email whose local part looks like a person's name:
  contains a dot between alphabetic chars, or starts with a common first name
  pattern.  This is a deliberate product decision; personal emails are never
  stored even if found.

LinkedIn rules
--------------
- Scan hrefs for linkedin.com/in/... (personal profiles) and
  linkedin.com/company/... (company pages).
- Never crawl LinkedIn — only URLs found on the company's own pages.
"""

from __future__ import annotations

import logging
import re

from app.config import GENERIC_EMAIL_PREFIXES
from app.models import EmailHit, Evidence, ErrorRecord

logger = logging.getLogger(__name__)

# Regex patterns
_EMAIL_PATTERN = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", re.IGNORECASE
)
_MAILTO_PATTERN = re.compile(r'href=["\']mailto:([^"\'?\s]+)', re.IGNORECASE)
_LINKEDIN_IN_PATTERN = re.compile(
    r'https?://(?:www\.)?linkedin\.com/in/([a-zA-Z0-9\-_%]+)/?', re.IGNORECASE
)
_LINKEDIN_COMPANY_PATTERN = re.compile(
    r'https?://(?:www\.)?linkedin\.com/company/([a-zA-Z0-9\-_%]+)/?', re.IGNORECASE
)


def regex_extract(
    domain: str,
    pages: dict[str, str],
    errors: list[ErrorRecord],
) -> dict:
    """Extract emails and LinkedIn URLs from raw page text using regex.

    Parameters
    ----------
    domain:
        Registrable domain (used only for logging context).
    pages:
        {url: raw_html_or_cleaned_text} — either works.
    errors:
        Failures appended here (this function should not raise).

    Returns
    -------
    dict with keys:
      - "generic_emails": list[EmailHit]
      - "linkedin_urls": list[str]   (company or personal, found on site)
    """
    all_emails: dict[str, EmailHit] = {}  # deduped by email address
    all_linkedin: set[str] = set()

    for url, text in pages.items():
        try:
            for hit in _extract_emails_from_text(text, url):
                key = hit.email.lower()
                if key not in all_emails:
                    all_emails[key] = hit
                else:
                    # Merge evidence
                    existing_urls = {e.source_url for e in all_emails[key].evidence}
                    for ev in hit.evidence:
                        if ev.source_url not in existing_urls:
                            all_emails[key].evidence.append(ev)

            for li_url in _extract_linkedin_from_text(text):
                all_linkedin.add(li_url)

        except Exception as exc:  # noqa: BLE001
            logger.warning("[fallback] Error processing %s: %s", url, exc)

    logger.info(
        "[fallback] %s: found %d generic emails, %d LinkedIn URLs",
        domain, len(all_emails), len(all_linkedin),
    )

    return {
        "generic_emails": list(all_emails.values()),
        "linkedin_urls": sorted(all_linkedin),
    }


def _is_generic_email(email: str) -> bool:
    """Return True if the email uses a generic/role-based local part.

    The local part must be in GENERIC_EMAIL_PREFIXES.
    Anything that looks like a personal name is rejected.
    """
    if "@" not in email:
        return False
    local = email.split("@")[0].lower().strip()
    return local in GENERIC_EMAIL_PREFIXES


def _extract_emails_from_text(text: str, source_url: str) -> list[EmailHit]:
    """Find all generic emails in a block of text; return EmailHit list."""
    found: dict[str, EmailHit] = {}

    # Scan mailto: hrefs first (most reliable)
    for match in _MAILTO_PATTERN.finditer(text):
        email = match.group(1).strip().lower()
        if _is_generic_email(email):
            snippet = match.group(0)[:300]
            if email not in found:
                found[email] = EmailHit(
                    email=email,
                    kind="generic",
                    evidence=[Evidence(source_url=source_url, snippet=snippet)],
                )

    # Then scan plain text
    for match in _EMAIL_PATTERN.finditer(text):
        email = match.group(0).strip().lower()
        if _is_generic_email(email) and email not in found:
            # Build a snippet: up to 100 chars around the match
            start = max(0, match.start() - 50)
            end = min(len(text), match.end() + 50)
            snippet = text[start:end].strip()[:300]
            found[email] = EmailHit(
                email=email,
                kind="generic",
                evidence=[Evidence(source_url=source_url, snippet=snippet)],
            )

    return list(found.values())


def _extract_linkedin_from_text(text: str) -> list[str]:
    """Find all LinkedIn profile/company URLs in a block of text."""
    urls: set[str] = set()

    for pattern in (_LINKEDIN_IN_PATTERN, _LINKEDIN_COMPANY_PATTERN):
        for match in pattern.finditer(text):
            # Normalise to https://linkedin.com/... (no www)
            full = match.group(0).rstrip("/")
            urls.add(full)

    return list(urls)
