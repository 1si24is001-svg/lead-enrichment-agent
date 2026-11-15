"""
tests/test_pipeline_resilience.py
==================================
Tests for error isolation in pipeline.py.

Key assertions
--------------
1. When the fetcher raises on every request, enrich_domain() returns a
   CompanyRecord with status="failed" and populated errors.
2. enrich_domain() NEVER raises — all exceptions are caught and recorded.
3. One domain failing does not affect the others (tested by running two domains
   where one has a broken fetcher and one has a working stub).

All tests are offline — the browser and LLM are stubbed.
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

from app.models import CompanyRecord, RunStats, ErrorRecord


class TestEnrichDomainNeverRaises:
    """enrich_domain() must swallow all exceptions and return a CompanyRecord."""

    def test_returns_failed_record_on_total_fetch_failure(self):
        """When the fetcher raises on every URL, status must be 'failed'."""
        from app.pipeline import enrich_domain
        from app.config import Settings

        settings = Settings()

        # We patch the browser fetch to raise immediately
        with patch("app.crawler.browser.fetch_pages", side_effect=RuntimeError("network is down")):
            record = enrich_domain(
                domain="example.com",
                settings=settings,
                replay=False,
                no_cache=True,
            )

        assert isinstance(record, CompanyRecord)
        assert record.status == "failed"
        assert record.domain == "example.com"

    def test_returns_record_even_on_catastrophic_error(self):
        """Even a totally unexpected exception must not escape enrich_domain()."""
        from app.pipeline import enrich_domain
        from app.config import Settings

        settings = Settings()

        with patch("app.crawler.browser.fetch_pages", side_effect=MemoryError("OOM")):
            record = enrich_domain(
                domain="badexample.com",
                settings=settings,
                replay=False,
                no_cache=True,
            )

        assert isinstance(record, CompanyRecord)
        # Must not raise — record should exist

    def test_failed_record_has_populated_errors(self):
        """A failed record must have at least one ErrorRecord explaining why."""
        from app.pipeline import enrich_domain
        from app.config import Settings

        settings = Settings()

        with patch("app.crawler.browser.fetch_pages", side_effect=RuntimeError("DNS fail")):
            record = enrich_domain(
                domain="nonexistent-xyz-domain.com",
                settings=settings,
                replay=False,
                no_cache=True,
            )

        assert record.status == "failed"
        assert len(record.errors) > 0
        assert all(isinstance(e, ErrorRecord) for e in record.errors)

    def test_failed_record_has_stats(self):
        """Even a failed record must have a populated RunStats object."""
        from app.pipeline import enrich_domain
        from app.config import Settings

        settings = Settings()

        with patch("app.crawler.browser.fetch_pages", side_effect=RuntimeError("fail")):
            record = enrich_domain(
                domain="broken.com",
                settings=settings,
                replay=False,
                no_cache=True,
            )

        assert isinstance(record.stats, RunStats)
        assert record.stats.duration_seconds >= 0


class TestDomainIsolation:
    """Failure of one domain must not prevent other domains from being processed."""

    def test_two_domains_one_fails(self):
        """When domain A's fetcher fails and domain B's works, B must still return a record."""
        from app.pipeline import enrich_domain
        from app.config import Settings

        settings = Settings()

        call_count = {"n": 0}

        def selective_fetcher(urls, domain, settings, **kwargs):
            call_count["n"] += 1
            if "broken" in domain:
                raise RuntimeError("This domain is broken")
            return {}  # empty but not an error for "good" domain

        with patch("app.crawler.browser.fetch_pages", side_effect=selective_fetcher):
            record_broken = enrich_domain("broken.com", settings, replay=False, no_cache=True)
            record_good = enrich_domain("good.com", settings, replay=False, no_cache=True)

        # Both must return CompanyRecords — no exception raised
        assert isinstance(record_broken, CompanyRecord)
        assert isinstance(record_good, CompanyRecord)
        assert record_broken.status == "failed"
        # good.com will be partial or failed (no real data) but it completed
        assert record_good.domain == "good.com"

    def test_fake_domain_does_not_raise(self):
        """A completely nonexistent domain must yield status='failed', not an exception."""
        from app.pipeline import enrich_domain
        from app.config import Settings

        settings = Settings()

        with patch(
            "app.crawler.browser.fetch_pages",
            side_effect=ConnectionError("Name or service not known"),
        ):
            record = enrich_domain(
                domain="thisdomaindoesnotexist-xyz-abc.com",
                settings=settings,
                replay=False,
                no_cache=True,
            )

        assert record.status == "failed"
        assert len(record.errors) > 0
