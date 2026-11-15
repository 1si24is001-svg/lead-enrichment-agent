"""
app/crawler/discovery.py
========================
Link extraction, relevance scoring, and crawl budget management.

Algorithm
---------
1. Extract all <a href> links from the homepage HTML.
2. Filter to same registrable domain only; reject off-domain and subdomains
   not matching the root (e.g. follow example.com and www.example.com,
   reject docs.example.com and status.example.com).
3. Reject non-HTML extensions (.pdf .zip .jpg .png .svg .xml etc.).
4. Score each URL: max(PAGE_SCORES hit in path) + 0.5 * max(hit in anchor text).
5. Sort descending, dedupe by normalised URL.
6. Take top MAX_PAGES_PER_DOMAIN; homepage always included, never counted
   against the budget.
7. Optionally respect robots.txt (RESPECT_ROBOTS=true by default).

Scoring table is defined in app/config.py::PAGE_SCORES.
"""

from __future__ import annotations

import logging
import urllib.robotparser
from pathlib import PurePosixPath
from urllib.parse import urlparse, urljoin, urlunparse, urlencode, parse_qsl

from bs4 import BeautifulSoup

from app.config import Settings, PAGE_SCORES, SKIP_EXTENSIONS
from app.models import ErrorRecord, RunStats

logger = logging.getLogger(__name__)


def discover_urls(
    domain: str,
    homepage_html: str,
    settings: Settings,
    *,
    stats: RunStats,
    errors: list[ErrorRecord],
) -> list[str]:
    """Return an ordered list of URLs to crawl for this domain.

    The homepage is always first and is never counted against the budget.
    Remaining slots are filled by descending relevance score.

    Parameters
    ----------
    domain:
        Normalised domain (e.g. ``postman.com``).
    homepage_html:
        Raw HTML of the homepage (already fetched by the caller).
    settings:
        Settings singleton.
    stats:
        Mutated in-place.
    errors:
        Failures appended here.

    Returns
    -------
    list[str]
        Ordered list starting with the homepage.
    """
    homepage_url = f"https://{domain}"
    soup = BeautifulSoup(homepage_html, "lxml")

    # Collect robots parser if needed
    robots_parser: urllib.robotparser.RobotFileParser | None = None
    if settings.respect_robots:
        robots_parser = _load_robots(domain, settings)

    # Extract all candidate links with anchor text
    candidates: dict[str, tuple[int, str]] = {}  # norm_url -> (score, raw_url)

    for tag in soup.find_all("a", href=True):
        href = tag["href"].strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue

        full_url = urljoin(homepage_url, href)
        parsed = urlparse(full_url)

        # Only http(s) URLs
        if parsed.scheme not in ("http", "https"):
            continue

        # Same registrable domain check
        if not is_same_domain(full_url, domain):
            continue

        # Skip non-HTML extensions
        path = parsed.path.lower()
        if any(path.endswith(ext) for ext in SKIP_EXTENSIONS):
            continue

        # Strip fragment for deduplication
        clean_url = urlunparse(parsed._replace(fragment=""))
        norm = normalise_url(clean_url)

        # Skip homepage itself
        if norm == normalise_url(homepage_url) or norm == normalise_url(homepage_url + "/"):
            continue

        anchor_text = tag.get_text(strip=True)
        s = score_url(clean_url, anchor_text)

        # Skip strongly negative URLs (docs, login, signup, privacy, terms)
        if s < -5:
            continue

        # robots.txt check
        if robots_parser and not robots_parser.can_fetch("*", clean_url):
            logger.debug("[discovery] Blocked by robots.txt: %s", clean_url)
            continue

        if norm not in candidates or candidates[norm][0] < s:
            candidates[norm] = (s, clean_url)

    # Sort by score descending
    sorted_candidates = sorted(candidates.values(), key=lambda x: x[0], reverse=True)

    # Take top N (budget), homepage is extra
    budget = settings.max_pages_per_domain
    selected = [raw for _, raw in sorted_candidates[:budget]]

    stats.pages_discovered = len(selected) + 1  # +1 for homepage
    logger.info(
        "[discovery] %s: homepage + %d additional pages selected from %d candidates",
        domain, len(selected), len(candidates),
    )

    return [homepage_url] + selected


def score_url(url: str, anchor_text: str = "") -> int:
    """Compute the relevance score for a candidate URL.

    Score = max keyword hit in URL path + 0.5 * max keyword hit in anchor text.
    Returns 0 if no keyword matches.  Negative scores (blog, docs, login) are
    preserved so they can be filtered below a threshold.
    """
    parsed = urlparse(url)
    path_parts = parsed.path.lower().strip("/").split("/")
    path_str = parsed.path.lower()

    # Score from path
    path_score = 0
    for keyword, points in PAGE_SCORES.items():
        if keyword in path_parts or f"/{keyword}" in path_str or f"{keyword}/" in path_str:
            if points > path_score or path_score == 0:
                path_score = max(path_score, points) if points > 0 else min(path_score, points)
                path_score = points if abs(points) > abs(path_score) else path_score

    # More precise: take the best single keyword match in path
    path_hits = [
        points for keyword, points in PAGE_SCORES.items()
        if keyword in path_parts or keyword in path_str
    ]
    path_score = max(path_hits, key=abs) if path_hits else 0

    # Score from anchor text
    anchor_lower = anchor_text.lower()
    anchor_hits = [
        points for keyword, points in PAGE_SCORES.items()
        if keyword in anchor_lower
    ]
    anchor_score = max(anchor_hits, key=abs) if anchor_hits else 0

    return int(path_score + 0.5 * anchor_score)


def is_same_domain(candidate_url: str, root_domain: str) -> bool:
    """Return True if candidate_url belongs to the same registrable domain.

    Allows root domain and www. subdomain only.
    Rejects docs., status., app., and other subdomains.
    """
    try:
        parsed = urlparse(candidate_url)
        host = parsed.netloc.lower().split(":")[0]  # strip port
        root = root_domain.lower()
        return host == root or host == f"www.{root}"
    except Exception:
        return False


def normalise_url(url: str) -> str:
    """Normalise a URL for deduplication purposes.

    Strips fragments, lowercases scheme + host, sorts query params.
    """
    try:
        parsed = urlparse(url)
        norm = urlunparse((
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path.rstrip("/") or "/",
            parsed.params,
            urlencode(sorted(parse_qsl(parsed.query))),
            "",  # no fragment
        ))
        return norm
    except Exception:
        return url.lower()


def _load_robots(domain: str, settings: Settings | None = None) -> urllib.robotparser.RobotFileParser | None:
    """Load and parse robots.txt for the domain. Returns None on failure."""
    import urllib.request

    rp = urllib.robotparser.RobotFileParser()
    robots_url = f"https://{domain}/robots.txt"
    try:
        ua = (
            settings.browser_user_agent
            if settings
            else "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        req = urllib.request.Request(robots_url, headers={"User-Agent": ua})
        with urllib.request.urlopen(req, timeout=10) as resp:
            content = resp.read().decode("utf-8", errors="ignore")
            rp.parse(content.splitlines())
        return rp
    except Exception as exc:
        logger.debug("[discovery] Could not load robots.txt for %s: %s", domain, exc)
        return None
