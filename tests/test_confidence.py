"""
tests/test_confidence.py
========================
Unit tests for app/extract/confidence.py.

Verifies the scoring table produces expected numbers for known inputs.
All tests are offline — deterministic, no LLM, no network.
"""

import pytest
from app.models import Evidence, EmailHit, Person


def _verified_evidence(url: str = "https://example.com/contact", snippet: str = "Contact us") -> Evidence:
    return Evidence(source_url=url, snippet=snippet, verified=True)


def _unverified_evidence(url: str = "https://example.com/about", snippet: str = "About us") -> Evidence:
    return Evidence(source_url=url, snippet=snippet, verified=False)


class TestScoreEmail:
    """Tests for score_email() — confidence scoring of a single EmailHit."""

    def test_perfect_score_when_all_signals_present(self):
        """Max score when: verified evidence + correct page type + corroborated + format valid."""
        from app.extract.confidence import score_email

        hit = EmailHit(
            email="contact@example.com",
            kind="generic",
            evidence=[_verified_evidence("https://example.com/contact", "contact@example.com")],
        )
        fallback = [
            EmailHit(email="contact@example.com", kind="generic", evidence=[])
        ]
        score = score_email(hit, fallback)
        # verified(0.40) + page_type(0.20) + corroborated(0.20) + format(0.10) = 0.90
        # (multi-page not applicable for one evidence entry)
        assert score >= 0.85
        assert score <= 1.0

    def test_zero_score_when_no_evidence(self):
        """Score must be 0.0 when there is no evidence at all."""
        from app.extract.confidence import score_email

        hit = EmailHit(email="info@example.com", kind="generic", evidence=[])
        score = score_email(hit, fallback_emails=[])
        assert score == 0.0

    def test_corroboration_adds_points(self):
        """Score must be higher when fallback also found the same email."""
        from app.extract.confidence import score_email

        hit = EmailHit(
            email="hello@example.com",
            kind="generic",
            evidence=[_unverified_evidence()],
        )
        without = score_email(hit, fallback_emails=[])
        with_corr = score_email(
            hit,
            fallback_emails=[EmailHit(email="hello@example.com", kind="generic", evidence=[])],
        )
        assert with_corr > without

    def test_unverified_evidence_does_not_add_verified_points(self):
        """verified=False evidence must not contribute the +0.40 verified points."""
        from app.extract.confidence import score_email, VERIFIED_EVIDENCE_POINTS

        hit_unverified = EmailHit(
            email="sales@example.com",
            kind="generic",
            evidence=[_unverified_evidence()],
        )
        hit_verified = EmailHit(
            email="sales@example.com",
            kind="generic",
            evidence=[_verified_evidence()],
        )
        score_u = score_email(hit_unverified, fallback_emails=[])
        score_v = score_email(hit_verified, fallback_emails=[])
        assert score_v - score_u >= VERIFIED_EVIDENCE_POINTS - 0.01

    def test_score_capped_at_1(self):
        """Score must never exceed 1.0 even with all signals."""
        from app.extract.confidence import score_email

        hit = EmailHit(
            email="info@example.com",
            kind="generic",
            evidence=[
                _verified_evidence("https://example.com/contact", "info@example.com"),
                _verified_evidence("https://example.com/about", "info@example.com"),
            ],
        )
        fallback = [EmailHit(email="info@example.com", kind="generic", evidence=[])]
        score = score_email(hit, fallback)
        assert score <= 1.0


class TestScoreField:
    """Tests for score_field() — scoring of plain string fields (overview, target_audience)."""

    def test_verified_evidence_adds_points(self):
        from app.extract.confidence import score_field

        ev = [_verified_evidence()]
        score = score_field("overview", "We build APIs. We serve developers.", ev)
        assert score >= 0.40

    def test_valid_two_sentence_overview_adds_format_points(self):
        from app.extract.confidence import score_field, FORMAT_VALID_POINTS

        ev_v = [_verified_evidence()]
        # Two sentences — passes format validation
        good = score_field("overview", "We build APIs. We serve developers.", ev_v)
        # Three sentences — fails format validation
        bad = score_field("overview", "We build APIs. We serve developers. We are great.", ev_v)
        assert good > bad
        assert good - bad >= FORMAT_VALID_POINTS - 0.01

    def test_empty_value_scores_zero(self):
        from app.extract.confidence import score_field

        assert score_field("overview", None, []) == 0.0


class TestCapFunction:
    """Tests for the _cap() helper."""

    def test_caps_at_1(self):
        from app.extract.confidence import _cap
        assert _cap(1.5) == 1.0

    def test_rounds_to_2dp(self):
        from app.extract.confidence import _cap
        assert _cap(0.8666) == 0.87

    def test_preserves_valid_score(self):
        from app.extract.confidence import _cap
        assert _cap(0.75) == 0.75
