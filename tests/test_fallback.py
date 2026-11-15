"""
tests/test_fallback.py
======================
Unit tests for app/extract/fallback.py.

All tests are offline — no network, no LLM, no browser.

Key test: personal emails must be REJECTED even when found in page text.
"""

import pytest


class TestRegexEmailExtraction:
    """Tests for email extraction and filtering in fallback.py."""

    def test_extracts_generic_info_email(self):
        """info@ is a valid generic email and must be extracted."""
        from app.extract.fallback import _extract_emails_from_text

        text = "Reach us at info@example.com for inquiries."
        hits = _extract_emails_from_text(text, "https://example.com/contact")
        emails = [h.email for h in hits]
        assert "info@example.com" in emails

    def test_extracts_contact_email(self):
        """contact@ must be extracted."""
        from app.extract.fallback import _extract_emails_from_text

        text = "Email: contact@company.io"
        hits = _extract_emails_from_text(text, "https://company.io/contact")
        assert any(h.email == "contact@company.io" for h in hits)

    def test_extracts_sales_email(self):
        """sales@ must be extracted."""
        from app.extract.fallback import _extract_emails_from_text

        text = "Talk to our sales team: sales@acme.com"
        hits = _extract_emails_from_text(text, "https://acme.com/pricing")
        assert any("sales@acme.com" == h.email for h in hits)

    def test_rejects_personal_email_with_dot(self):
        """john.doe@example.com must be rejected — looks like a personal name."""
        from app.extract.fallback import _extract_emails_from_text

        text = "Contact John at john.doe@example.com"
        hits = _extract_emails_from_text(text, "https://example.com/team")
        emails = [h.email for h in hits]
        assert "john.doe@example.com" not in emails

    def test_rejects_personal_email_firstname_only(self):
        """sarah@example.com — single common first name — must be rejected."""
        from app.extract.fallback import _extract_emails_from_text

        text = "Email sarah@example.com directly."
        hits = _extract_emails_from_text(text, "https://example.com")
        emails = [h.email for h in hits]
        assert "sarah@example.com" not in emails

    def test_all_hits_have_kind_generic(self):
        """Every extracted EmailHit must have kind='generic'."""
        from app.extract.fallback import _extract_emails_from_text

        text = "hello@startup.com | support@startup.com"
        hits = _extract_emails_from_text(text, "https://startup.com")
        assert all(h.kind == "generic" for h in hits)

    def test_extracts_from_mailto_href(self):
        """Emails in mailto: hrefs must also be extracted."""
        from app.extract.fallback import _extract_emails_from_text

        text = '<a href="mailto:press@example.com">Press contact</a>'
        hits = _extract_emails_from_text(text, "https://example.com")
        emails = [h.email for h in hits]
        assert "press@example.com" in emails

    def test_deduplicates_same_email(self):
        """The same email appearing twice in text must yield one EmailHit."""
        from app.extract.fallback import _extract_emails_from_text

        text = "hello@company.com and also hello@company.com"
        hits = _extract_emails_from_text(text, "https://company.com")
        emails = [h.email for h in hits]
        assert emails.count("hello@company.com") == 1


class TestIsGenericEmail:
    """Tests for the _is_generic_email() predicate."""

    def test_info_is_generic(self):
        from app.extract.fallback import _is_generic_email
        assert _is_generic_email("info@example.com") is True

    def test_hello_is_generic(self):
        from app.extract.fallback import _is_generic_email
        assert _is_generic_email("hello@example.com") is True

    def test_security_is_generic(self):
        from app.extract.fallback import _is_generic_email
        assert _is_generic_email("security@example.com") is True

    def test_firstname_lastname_is_not_generic(self):
        from app.extract.fallback import _is_generic_email
        assert _is_generic_email("alice.smith@example.com") is False

    def test_support_is_generic(self):
        from app.extract.fallback import _is_generic_email
        assert _is_generic_email("support@example.com") is True


class TestLinkedInExtraction:
    """Tests for LinkedIn URL extraction from page text."""

    def test_extracts_company_page(self):
        from app.extract.fallback import _extract_linkedin_from_text

        text = 'Follow us: <a href="https://linkedin.com/company/acme-corp">LinkedIn</a>'
        urls = _extract_linkedin_from_text(text)
        assert any("linkedin.com/company/acme-corp" in u for u in urls)

    def test_extracts_personal_profile(self):
        from app.extract.fallback import _extract_linkedin_from_text

        text = "Connect with our CEO: https://www.linkedin.com/in/janedoe"
        urls = _extract_linkedin_from_text(text)
        assert any("linkedin.com/in/janedoe" in u for u in urls)

    def test_does_not_invent_linkedin_urls(self):
        """Must not return URLs that are not present in the text."""
        from app.extract.fallback import _extract_linkedin_from_text

        text = "We are a B2B SaaS company. No LinkedIn here."
        urls = _extract_linkedin_from_text(text)
        assert urls == []
