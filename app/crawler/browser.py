"""
app/crawler/browser.py
======================
Playwright (sync API, Chromium, headless) page fetcher.

Design decisions
----------------
- One browser instance is reused across all pages and domains.
- One browser context is created per domain (isolated cookies / storage).
- Retry twice with exponential backoff (2s, 4s) on timeout or 5xx.
- 404 and 403 are NOT retried — they are definitive answers.
- Every failure becomes an ErrorRecord; no exception escapes this module.
- Respects the RESPECT_ROBOTS flag from config (checked by discovery.py before
  calling here; browser.py itself does not re-check robots.txt).

Cache
-----
Fetched pages are stored in cache/pages/<sha1(url)>.json so they can be served
in --replay mode without touching the network.
"""

from __future__ import annotations

import logging
import time

from app.config import Settings
from app.crawler.cache import PageCache, CacheMissError
from app.models import ErrorRecord, RunStats

logger = logging.getLogger(__name__)

_SETTLE_SECONDS = 1.5  # wait after networkidle for late JS rendering


def fetch_pages(
    urls: list[str],
    domain: str,
    settings: Settings,
    *,
    replay: bool,
    no_cache: bool,
    stats: RunStats,
    errors: list[ErrorRecord],
) -> dict[str, str]:
    """Fetch a list of URLs and return {url: html_text}.

    Parameters
    ----------
    urls:
        Ordered list of URLs to fetch (homepage first).
    domain:
        The registrable domain being processed (used for context isolation).
    settings:
        Settings singleton.
    replay:
        Cache-only mode; records an ErrorRecord on cache miss (does not raise).
    no_cache:
        Ignore existing cache entries.
    stats:
        Mutated in-place with fetch counts and cache hits.
    errors:
        Mutated in-place; failures appended here, never raised.

    Returns
    -------
    dict[str, str]
        Mapping of URL → raw HTML string for successfully fetched pages.
    """
    cache = PageCache(settings.cache_dir)
    pages: dict[str, str] = {}

    if replay:
        # Serve everything from cache; record errors on miss
        for url in urls:
            try:
                entry = cache.require(url)
                pages[url] = entry["html"]
                stats.cache_hits += 1
                logger.debug("[browser] cache hit (replay): %s", url)
            except CacheMissError as exc:
                logger.error("[browser] %s", exc)
                errors.append(ErrorRecord(
                    stage="fetch",
                    url=url,
                    error_type="CacheMiss",
                    message=str(exc),
                    recoverable=False,
                ))
                stats.pages_failed += 1
        stats.pages_fetched = len(pages)
        return pages

    # Live fetch with Playwright
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        errors.append(ErrorRecord(
            stage="fetch",
            url=None,
            error_type="ImportError",
            message="playwright not installed. Run: pip install playwright && playwright install chromium",
            recoverable=False,
        ))
        return pages

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=settings.browser_user_agent,
            viewport={
                "width": settings.browser_viewport_width,
                "height": settings.browser_viewport_height,
            },
        )
        try:
            for url in urls:
                # Check cache first (unless --no-cache)
                if not no_cache:
                    cached = cache.get(url)
                    if cached:
                        pages[url] = cached["html"]
                        stats.cache_hits += 1
                        logger.debug("[browser] cache hit: %s", url)
                        continue

                html = _fetch_one(url, context, cache, settings, errors)
                if html is not None:
                    pages[url] = html
                    stats.pages_fetched += 1
                else:
                    stats.pages_failed += 1
        finally:
            context.close()
            browser.close()

    return pages


def _fetch_one(
    url: str,
    context: object,  # playwright BrowserContext
    cache: PageCache,
    settings: Settings,
    errors: list[ErrorRecord],
) -> str | None:
    """Fetch a single URL with retry logic; return HTML or None on failure.

    Retries up to settings.retry_count times on timeout or 5xx.
    Does NOT retry on 404 or 403.
    """
    from playwright.sync_api import TimeoutError as PWTimeout

    backoff = settings.retry_backoff_seconds
    last_error: str | None = None

    for attempt in range(settings.retry_count + 1):
        try:
            page = context.new_page()
            try:
                response = page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=settings.request_timeout_ms,
                )
                try:
                    page.wait_for_load_state("networkidle", timeout=3000)
                except PWTimeout:
                    pass
                status = response.status if response else 0

                # Definitive failures — do not retry
                if status in (403, 404):
                    error_type = f"HTTP{status}"
                    logger.warning("[browser] %s → %s: %s", url, status, error_type)
                    errors.append(ErrorRecord(
                        stage="fetch",
                        url=url,
                        error_type=error_type,
                        message=f"HTTP {status} — not retrying",
                        recoverable=False,
                    ))
                    return None

                # Server errors — retry
                if status >= 500:
                    last_error = f"HTTP{status}"
                    if attempt < settings.retry_count:
                        wait = backoff[attempt] if attempt < len(backoff) else backoff[-1]
                        logger.warning("[browser] %s → %s; retrying in %.0fs", url, status, wait)
                        time.sleep(wait)
                        continue

                # Wait for late JS
                time.sleep(_SETTLE_SECONDS)
                html = page.content()
                logger.info("[browser] fetched %s (%d chars)", url, len(html))

                cache.put(url, html, status)
                return html

            finally:
                page.close()

        except PWTimeout as exc:
            last_error = "TimeoutError"
            if attempt < settings.retry_count:
                wait = backoff[attempt] if attempt < len(backoff) else backoff[-1]
                logger.warning("[browser] Timeout on %s; retrying in %.0fs", url, wait)
                time.sleep(wait)
            else:
                logger.error("[browser] Timeout on %s after %d attempts", url, attempt + 1)

        except Exception as exc:  # noqa: BLE001
            last_error = type(exc).__name__
            logger.error("[browser] Error fetching %s: %s", url, exc)
            break  # non-timeout errors are not retried

    errors.append(ErrorRecord(
        stage="fetch",
        url=url,
        error_type=last_error or "UnknownError",
        message=f"Failed to fetch {url} after {settings.retry_count + 1} attempts: {last_error}",
        recoverable=True,
    ))
    return None
