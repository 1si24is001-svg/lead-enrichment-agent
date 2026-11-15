"""
app/extract/clean.py
====================
HTML → clean plain text, with boilerplate removal and budget trimming.

Processing steps
----------------
1. Parse HTML with BeautifulSoup/lxml.
2. Strip noise elements: script, style, noscript, svg, iframe, form,
   nav, header, footer, [aria-hidden="true"].
3. Strip elements whose class or id contains any of:
   cookie | banner | newsletter | modal | popup | breadcrumb
4. Convert the remainder to markdown-ish plain text.
5. Collapse runs of whitespace and blank lines.
6. **Boilerplate killer**: after cleaning all pages for a domain, drop any
   line that appears on >= BOILERPLATE_PAGE_FRACTION (60%) of that domain's
   pages.  Removes nav/footer copy without per-site selector lists.
   Log how many lines and characters were removed.
7. Apply per-page and per-domain character budgets, truncating at a paragraph
   boundary (blank line), never mid-word.

Character budgets (from config)
--------------------------------
MAX_CHARS_PER_PAGE   = 6,000
MAX_CHARS_PER_DOMAIN = 18,000

Budget is allocated across pages in proportion to their discovery score,
so high-value pages (about, team, contact) get more of the domain budget.
"""

from __future__ import annotations

import logging
import re
from collections import Counter

from bs4 import BeautifulSoup, Comment

from app.config import Settings
from app.models import ErrorRecord, RunStats

logger = logging.getLogger(__name__)

# Elements that are always stripped entirely
_STRIP_TAGS = {
    "script", "style", "noscript", "svg", "iframe",
    "form", "nav", "header", "footer",
}

# Class/id substrings that trigger element removal
_STRIP_CLASS_ID_PATTERNS = re.compile(
    r"cookie|banner|newsletter|modal|popup|breadcrumb",
    re.IGNORECASE,
)


def clean_html(html: str) -> str:
    """Convert raw HTML to cleaned plain text (single page).

    Steps 1–5 above.  Does NOT apply boilerplate removal or budget trimming;
    those are applied at the domain level in clean_pages().
    """
    soup = BeautifulSoup(html, "lxml")

    # Remove HTML comments
    for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
        comment.extract()

    # Strip noise tags
    for tag in soup.find_all(_STRIP_TAGS):
        tag.decompose()

    # Strip aria-hidden="true"
    for tag in soup.find_all(attrs={"aria-hidden": "true"}):
        tag.decompose()

    # Strip by class/id patterns
    for tag in soup.find_all(True):
        if tag is None or tag.attrs is None:
            continue
        classes = " ".join(tag.get("class", []))
        tag_id = tag.get("id", "")
        if _STRIP_CLASS_ID_PATTERNS.search(classes) or _STRIP_CLASS_ID_PATTERNS.search(tag_id):
            tag.decompose()

    # Extract text
    text = soup.get_text(separator="\n")

    # Collapse whitespace within lines
    lines = []
    for line in text.splitlines():
        line = re.sub(r"[ \t]+", " ", line).strip()
        lines.append(line)

    # Collapse multiple consecutive blank lines into one
    result_lines: list[str] = []
    prev_blank = False
    for line in lines:
        is_blank = line == ""
        if is_blank and prev_blank:
            continue
        result_lines.append(line)
        prev_blank = is_blank

    return "\n".join(result_lines).strip()


def clean_pages(
    pages: dict[str, str],
    domain: str,
    discovery_scores: dict[str, int],
    settings: Settings,
    *,
    stats: RunStats,
    errors: list[ErrorRecord],
) -> dict[str, str]:
    """Clean all pages for a domain and apply boilerplate removal + budgets.

    Parameters
    ----------
    pages:
        {url: raw_html} from the fetcher.
    domain:
        The registrable domain (used only for logging).
    discovery_scores:
        {url: score} from discovery.py — used to allocate domain budget.
    settings:
        Settings singleton (reads MAX_CHARS_PER_PAGE, MAX_CHARS_PER_DOMAIN,
        BOILERPLATE_PAGE_FRACTION).
    stats, errors:
        Mutated in-place.

    Returns
    -------
    dict[str, str]
        {url: cleaned_text} ready for the LLM prompt.
    """
    if not pages:
        return {}

    # Step 1: clean each page individually
    pre_boilerplate: dict[str, str] = {}
    for url, html in pages.items():
        try:
            text = clean_html(html)
            # Apply per-page budget first
            text = trim_to_budget(text, settings.max_chars_per_page)
            pre_boilerplate[url] = text
        except Exception as exc:  # noqa: BLE001
            logger.warning("[clean] Failed to clean %s: %s", url, exc)
            errors.append(ErrorRecord(
                stage="clean",
                url=url,
                error_type=type(exc).__name__,
                message=str(exc),
                recoverable=True,
            ))

    if not pre_boilerplate:
        return {}

    # Step 2: boilerplate removal (cross-page)
    filtered, lines_removed, chars_removed = remove_boilerplate(
        pre_boilerplate,
        fraction=settings.boilerplate_page_fraction,
    )
    if lines_removed:
        logger.info(
            "[clean] %s: boilerplate removal dropped %d lines / %d chars",
            domain, lines_removed, chars_removed,
        )

    # Step 3: allocate domain budget proportionally by discovery score
    total_score = sum(max(discovery_scores.get(u, 1), 1) for u in filtered)
    domain_budget = settings.max_chars_per_domain
    result: dict[str, str] = {}
    used_chars = 0

    for url, text in filtered.items():
        remaining = domain_budget - used_chars
        if remaining <= 0:
            break
        score = max(discovery_scores.get(url, 1), 1)
        page_budget = int(domain_budget * score / total_score)
        page_budget = min(page_budget, remaining, settings.max_chars_per_page)
        trimmed = trim_to_budget(text, page_budget)
        result[url] = trimmed
        used_chars += len(trimmed)

    return result


def remove_boilerplate(
    cleaned_pages: dict[str, str],
    fraction: float = 0.60,
) -> tuple[dict[str, str], int, int]:
    """Drop lines that appear on >= `fraction` of the pages.

    Returns
    -------
    tuple of:
      - filtered dict {url: text}
      - lines_removed  (total across all pages)
      - chars_removed  (total across all pages)
    """
    if len(cleaned_pages) < 2:
        return cleaned_pages, 0, 0

    page_count = len(cleaned_pages)
    threshold = int(page_count * fraction)
    if threshold < 2:
        threshold = 2

    # Count line frequency across pages (strip and lowercase for matching)
    line_counter: Counter[str] = Counter()
    for text in cleaned_pages.values():
        # Use a set per page so a line counted at most once per page
        seen = set()
        for raw_line in text.splitlines():
            key = raw_line.strip().lower()
            if key and key not in seen:
                line_counter[key] += 1
                seen.add(key)

    # Lines appearing on >= threshold pages are boilerplate
    boilerplate = {line for line, count in line_counter.items() if count >= threshold}

    total_lines_removed = 0
    total_chars_removed = 0
    result: dict[str, str] = {}

    for url, text in cleaned_pages.items():
        filtered_lines = []
        for raw_line in text.splitlines():
            key = raw_line.strip().lower()
            if key and key in boilerplate:
                total_lines_removed += 1
                total_chars_removed += len(raw_line) + 1  # +1 for newline
            else:
                filtered_lines.append(raw_line)
        result[url] = "\n".join(filtered_lines)

    return result, total_lines_removed, total_chars_removed


def trim_to_budget(text: str, max_chars: int) -> str:
    """Truncate text to max_chars, cutting at a paragraph boundary (blank line).

    Never truncates mid-word.  If no paragraph boundary is found before the
    limit, falls back to the last word boundary.
    """
    if len(text) <= max_chars:
        return text

    # Try to cut at the last blank line before max_chars
    candidate = text[:max_chars]
    para_boundary = candidate.rfind("\n\n")
    if para_boundary > 0:
        return text[:para_boundary].strip()

    # Fall back to last newline
    newline_boundary = candidate.rfind("\n")
    if newline_boundary > 0:
        return text[:newline_boundary].strip()

    # Fall back to last word boundary
    space_boundary = candidate.rfind(" ")
    if space_boundary > 0:
        return text[:space_boundary].strip()

    return candidate.strip()
