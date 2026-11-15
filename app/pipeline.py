"""
app/pipeline.py
===============
enrich_domain() — orchestrates one domain end-to-end.

Stage order
-----------
1. Discovery  : find relevant URLs on the same registrable domain
2. Fetch      : headless browser retrieval with retry + backoff
3. Clean      : HTML → plain text, boilerplate removal, budget trim
4. LLM        : single call per domain, structured extraction
5. Verify     : check every evidence snippet against source text
6. Fallback   : regex email + LinkedIn (runs always, not only on failure)
7. Confidence : deterministic rule-based scoring
8. Assemble   : build CompanyRecord and flag for review if needed

One domain failing must never affect the others.  Every exception is caught,
recorded as an ErrorRecord, and the function always returns a CompanyRecord.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

from app.config import Settings
from app.crawler import browser as _browser_module
from app.crawler import discovery as _discovery_module
from app.extract import clean as _clean_module
from app.extract import llm as _llm_module
from app.extract import fallback as _fallback_module
from app.extract import verify as _verify_module
from app.extract import confidence as _confidence_module
from app.models import CompanyRecord, EmailHit, ErrorRecord, Evidence, Person, RunStats

logger = logging.getLogger(__name__)


def enrich_domain(
    domain: str,
    settings: Settings,
    replay: bool = False,
    no_cache: bool = False,
) -> CompanyRecord:
    """Run the full enrichment pipeline for a single domain.

    Parameters
    ----------
    domain:
        Normalised domain name (e.g. ``postman.com``), no scheme or www.
    settings:
        Shared settings singleton (may be mutated by CLI overrides before call).
    replay:
        If True, serve all pages and LLM responses from cache only; raise a
        descriptive error (not an exception) on any cache miss.
    no_cache:
        If True, ignore existing cache entries and always fetch/call fresh.

    Returns
    -------
    CompanyRecord
        Always returns a record.  ``status`` reflects the pipeline outcome.
    """
    start = time.monotonic()
    stats = RunStats()
    errors: list[ErrorRecord] = []
    cleaned_pages: dict[str, str] = {}
    raw_pages: dict[str, str] = {}
    discovery_scores: dict[str, int] = {}

    logger.info("[pipeline] Starting enrichment for domain: %s", domain)

    try:
        # ── Stage 1 + 2: Fetch homepage, then discover + fetch remaining pages ──
        homepage_url = f"https://{domain}"

        from app.crawler.browser import fetch_pages as _fetch_pages
        from app.crawler.discovery import discover_urls, score_url

        # Fetch homepage first (needed for discovery)
        homepage_pages = _fetch_pages(
            [homepage_url],
            domain,
            settings,
            replay=replay,
            no_cache=no_cache,
            stats=stats,
            errors=errors,
        )

        if not homepage_pages:
            logger.warning("[pipeline] %s: homepage fetch failed — marking failed", domain)
            stats.duration_seconds = time.monotonic() - start
            return CompanyRecord(
                domain=domain,
                status="failed",
                errors=errors,
                stats=stats,
                extracted_at=datetime.now(timezone.utc),
            )

        homepage_html = homepage_pages.get(homepage_url, "")

        # ── Stage 1: Discovery (uses homepage HTML) ──
        try:
            urls = discover_urls(
                domain,
                homepage_html,
                settings,
                stats=stats,
                errors=errors,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[pipeline] %s: discovery error: %s", domain, exc)
            errors.append(ErrorRecord(
                stage="discovery",
                url=homepage_url,
                error_type=type(exc).__name__,
                message=str(exc),
                recoverable=True,
            ))
            urls = [homepage_url]

        # Score each URL (for budget allocation in clean step)
        from app.crawler.discovery import score_url
        for url in urls:
            if url == homepage_url:
                discovery_scores[url] = 5  # homepage gets baseline score
            else:
                discovery_scores[url] = max(score_url(url), 1)

        # ── Stage 2: Fetch remaining pages ──
        remaining = [u for u in urls if u != homepage_url]
        if remaining:
            more_pages = _fetch_pages(
                remaining,
                domain,
                settings,
                replay=replay,
                no_cache=no_cache,
                stats=stats,
                errors=errors,
            )
        else:
            more_pages = {}

        raw_pages = {**homepage_pages, **more_pages}
        # Update stats
        stats.pages_fetched = len(raw_pages)

        # ── Stage 3: Clean ──
        from app.extract.clean import clean_pages
        try:
            cleaned_pages = clean_pages(
                raw_pages,
                domain,
                discovery_scores,
                settings,
                stats=stats,
                errors=errors,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[pipeline] %s: clean error: %s", domain, exc)
            errors.append(ErrorRecord(
                stage="clean",
                url=None,
                error_type=type(exc).__name__,
                message=str(exc),
                recoverable=True,
            ))

        # ── Stage 4: LLM extraction ──
        from app.extract.llm import call_llm
        llm_data: dict | None = None
        try:
            llm_data = call_llm(
                domain,
                cleaned_pages,
                settings,
                replay=replay,
                no_cache=no_cache,
                stats=stats,
                errors=errors,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[pipeline] %s: LLM error: %s", domain, exc)
            errors.append(ErrorRecord(
                stage="llm",
                url=None,
                error_type=type(exc).__name__,
                message=str(exc),
                recoverable=True,
            ))

        # ── Stage 5a: Fallback regex (always runs) ──
        from app.extract.fallback import regex_extract
        fallback: dict = {}
        try:
            fallback = regex_extract(domain, raw_pages, errors)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[pipeline] %s: fallback error: %s", domain, exc)

        fallback_emails: list[EmailHit] = fallback.get("generic_emails", [])
        fallback_linkedin: list[str] = fallback.get("linkedin_urls", [])

        # ── Assemble partial CompanyRecord from LLM data ──
        record = _assemble_record(
            domain=domain,
            llm_data=llm_data,
            fallback_emails=fallback_emails,
            fallback_linkedin=fallback_linkedin,
            source_urls=list(raw_pages.keys()),
            stats=stats,
            errors=errors,
        )

        # ── Stage 5b: Verify evidence ──
        from app.extract.verify import verify_evidence
        try:
            verified, total = verify_evidence(record, cleaned_pages)
            if total > 0:
                logger.info("[pipeline] %s: %d/%d evidence snippets verified", domain, verified, total)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[pipeline] %s: verify error: %s", domain, exc)

        # ── Stage 6: Confidence scoring ──
        from app.extract.confidence import score_record
        try:
            record = score_record(record, fallback_emails, fallback_linkedin, settings)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[pipeline] %s: confidence scoring error: %s", domain, exc)

        # ── Determine final status ──
        unrecoverable = [e for e in errors if not e.recoverable]
        if not raw_pages:
            record.status = "failed"
        elif unrecoverable or llm_data is None:
            record.status = "partial"
        else:
            record.status = "success"

        stats.duration_seconds = time.monotonic() - start
        record.stats = stats
        logger.info("[pipeline] %s: done — status=%s conf=%.2f", domain, record.status, record.overall_confidence)
        return record

    except Exception as exc:  # noqa: BLE001 — intentional broad catch
        # No exception escapes the pipeline.
        logger.exception("[pipeline] Unhandled error for domain %s: %s", domain, exc)
        errors.append(
            ErrorRecord(
                stage="discovery",
                url=None,
                error_type=type(exc).__name__,
                message=str(exc),
                recoverable=False,
            )
        )
        stats.duration_seconds = time.monotonic() - start
        return CompanyRecord(
            domain=domain,
            status="failed",
            errors=errors,
            stats=stats,
            extracted_at=datetime.now(timezone.utc),
        )


def _unpack_val_ev(raw: object) -> tuple[str | None, list[dict]]:
    """Unpack a field that may be a plain string or an object with 'value' and 'evidence'."""
    if isinstance(raw, dict):
        val = raw.get("value")
        ev = raw.get("evidence", [])
        if isinstance(ev, dict):
            ev = [ev]
        elif not isinstance(ev, list):
            ev = []
        return (str(val).strip() if val is not None else None), [e for e in ev if isinstance(e, dict)]
    elif isinstance(raw, str):
        s = raw.strip()
        return (s if s else None), []
    return None, []


def _assemble_record(
    domain: str,
    llm_data: dict | None,
    fallback_emails: list[EmailHit],
    fallback_linkedin: list[str],
    source_urls: list[str],
    stats: RunStats,
    errors: list[ErrorRecord],
) -> CompanyRecord:
    """Build a CompanyRecord from LLM output (or fallback if LLM failed).

    Does NOT set status or confidence — those are set by the caller after
    verify and score_record run.
    """
    from pydantic import ValidationError

    company_name: str | None = None
    overview: str | None = None
    overview_evidence: list[Evidence] = []
    target_audience: str | None = None
    target_audience_evidence: list[Evidence] = []
    generic_emails: list[EmailHit] = []
    people: list[Person] = []

    if llm_data:
        try:
            c_val, _ = _unpack_val_ev(llm_data.get("company_name") or llm_data.get("name"))
            company_name = c_val

            o_val, o_ev = _unpack_val_ev(llm_data.get("overview"))
            overview = o_val
            all_o_ev = o_ev + [
                e for e in llm_data.get("overview_evidence", []) if isinstance(e, dict)
            ]
            for ev_raw in all_o_ev:
                try:
                    overview_evidence.append(Evidence(**ev_raw))
                except (ValidationError, TypeError):
                    pass

            t_val, t_ev = _unpack_val_ev(llm_data.get("target_audience"))
            target_audience = t_val
            all_t_ev = t_ev + [
                e for e in llm_data.get("target_audience_evidence", []) if isinstance(e, dict)
            ]
            for ev_raw in all_t_ev:
                try:
                    target_audience_evidence.append(Evidence(**ev_raw))
                except (ValidationError, TypeError):
                    pass

            # Parse generic_emails from LLM
            llm_email_addrs: set[str] = set()
            raw_email_list = llm_data.get("generic_emails") or llm_data.get("emails") or []
            for email_raw in raw_email_list:
                if isinstance(email_raw, str):
                    em_val, em_ev = email_raw, []
                elif isinstance(email_raw, dict):
                    em_val, em_ev = _unpack_val_ev(email_raw.get("email"))
                    if not em_val and "value" in email_raw:
                        em_val, em_ev = _unpack_val_ev(email_raw)
                    ev_list = email_raw.get("evidence", [])
                    if isinstance(ev_list, list):
                        em_ev.extend([e for e in ev_list if isinstance(e, dict)])
                else:
                    continue
                if em_val:
                    try:
                        hit = EmailHit(
                            email=em_val,
                            kind="generic",
                            evidence=[Evidence(**ev) for ev in em_ev if isinstance(ev, dict)],
                        )
                        generic_emails.append(hit)
                        llm_email_addrs.add(hit.email.lower())
                    except (ValidationError, TypeError, Exception):
                        pass

            # Merge fallback emails (dedupe)
            for fb_email in fallback_emails:
                if fb_email.email.lower() not in llm_email_addrs:
                    generic_emails.append(fb_email)

            # Parse people
            for person_raw in llm_data.get("people", []):
                if not isinstance(person_raw, dict):
                    continue
                try:
                    p_name, n_ev = _unpack_val_ev(person_raw.get("name"))
                    p_role, r_ev = _unpack_val_ev(person_raw.get("role"))
                    p_li, l_ev = _unpack_val_ev(person_raw.get("linkedin_url"))

                    raw_ev = person_raw.get("evidence", [])
                    if isinstance(raw_ev, dict):
                        raw_ev = [raw_ev]
                    elif not isinstance(raw_ev, list):
                        raw_ev = []
                    all_p_ev = n_ev + r_ev + l_ev + [e for e in raw_ev if isinstance(e, dict)]

                    p_evidence = []
                    for ev_dict in all_p_ev:
                        try:
                            p_evidence.append(Evidence(**ev_dict))
                        except (ValidationError, TypeError):
                            pass

                    if p_name:
                        person = Person(
                            name=p_name,
                            role=p_role,
                            linkedin_url=p_li,
                            evidence=p_evidence,
                        )
                        people.append(person)
                except (ValidationError, TypeError, Exception):
                    pass

        except Exception as exc:  # noqa: BLE001
            logger.warning("[pipeline] Error parsing LLM data: %s", exc)
            errors.append(ErrorRecord(
                stage="validate",
                url=None,
                error_type=type(exc).__name__,
                message=f"Failed to parse LLM output: {exc}",
                recoverable=True,
            ))

    else:
        # LLM failed — use fallback emails only
        generic_emails = fallback_emails

    try:
        return CompanyRecord(
            domain=domain,
            status="partial",  # will be overwritten by caller
            company_name=company_name,
            overview=overview,
            overview_evidence=overview_evidence,
            target_audience=target_audience,
            target_audience_evidence=target_audience_evidence,
            generic_emails=generic_emails,
            people=people,
            source_urls=source_urls,
            errors=errors,
            stats=stats,
            extracted_at=datetime.now(timezone.utc),
        )
    except ValidationError as exc:
        logger.warning("[pipeline] ValidationError assembling CompanyRecord: %s", exc)
        errors.append(ErrorRecord(
            stage="validate",
            url=None,
            error_type="ValidationError",
            message=f"Schema validation error on assembly: {exc}",
            recoverable=False,
        ))
        return CompanyRecord(
            domain=domain,
            status="failed",
            source_urls=source_urls,
            errors=errors,
            stats=stats,
            extracted_at=datetime.now(timezone.utc),
        )
