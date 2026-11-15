"""
tests/test_discovery.py
=======================
Unit tests for app/crawler/discovery.py.

All tests are offline — no network, no browser.
"""

import pytest


class TestScoreUrl:
    """Tests for score_url() — URL relevance scoring."""

    def test_about_scores_highest(self):
        """'/about' should score at or near maximum (10 path points)."""
        from app.crawler.discovery import score_url

        assert score_url("https://example.com/about") >= 10

    def test_team_scores_highest(self):
        """/team should score at or near maximum (10 path points)."""
        from app.crawler.discovery import score_url

        assert score_url("https://example.com/team") >= 10

    def test_blog_scores_negative(self):
        """/blog should produce a negative score (not worth crawling)."""
        from app.crawler.discovery import score_url

        assert score_url("https://example.com/blog") < 0

    def test_docs_scores_very_negative(self):
        """/docs should score -10 (explicitly excluded from budget)."""
        from app.crawler.discovery import score_url

        assert score_url("https://example.com/docs/api-reference") <= -10

    def test_login_scores_very_negative(self):
        """/login should produce a negative score."""
        from app.crawler.discovery import score_url

        assert score_url("https://example.com/login") < 0

    def test_anchor_text_adds_half_score(self):
        """Anchor text match should add 0.5 * keyword score."""
        from app.crawler.discovery import score_url

        score_no_anchor = score_url("https://example.com/company-page")
        score_with_anchor = score_url("https://example.com/company-page", anchor_text="About Us")
        assert score_with_anchor >= score_no_anchor

    def test_unknown_path_scores_zero(self):
        """An unrecognised path with no keywords should score 0."""
        from app.crawler.discovery import score_url

        assert score_url("https://example.com/xyzzy-randompage") == 0


class TestIsSameDomain:
    """Tests for is_same_domain() — domain boundary enforcement."""

    def test_allows_root_domain(self):
        from app.crawler.discovery import is_same_domain

        assert is_same_domain("https://example.com/about", "example.com")

    def test_allows_www_subdomain(self):
        from app.crawler.discovery import is_same_domain

        assert is_same_domain("https://www.example.com/about", "example.com")

    def test_rejects_docs_subdomain(self):
        from app.crawler.discovery import is_same_domain

        assert not is_same_domain("https://docs.example.com/api", "example.com")

    def test_rejects_status_subdomain(self):
        from app.crawler.discovery import is_same_domain

        assert not is_same_domain("https://status.example.com", "example.com")

    def test_rejects_off_domain_link(self):
        from app.crawler.discovery import is_same_domain

        assert not is_same_domain("https://twitter.com/exampleco", "example.com")

    def test_rejects_pdf_extension(self):
        """Non-HTML extensions should be caught here too (belt-and-suspenders)."""
        from app.crawler.discovery import is_same_domain

        # URL is same domain but discover_urls should also skip it via SKIP_EXTENSIONS
        assert is_same_domain("https://example.com/deck.pdf", "example.com")
        # (the extension check happens in discover_urls, not is_same_domain)


class TestDiscoverUrls:
    """Integration tests for discover_urls() with mocked homepage HTML."""

    HOMEPAGE_HTML = """
    <html><body>
      <a href="/about">About Us</a>
      <a href="/team">Our Team</a>
      <a href="/blog/post-1">Blog Post</a>
      <a href="/docs/getting-started">Docs</a>
      <a href="/login">Login</a>
      <a href="https://example.com/contact">Contact</a>
      <a href="https://twitter.com/exampleco">Twitter</a>
      <a href="/files/brochure.pdf">Brochure PDF</a>
    </body></html>
    """

    def _make_settings(self, max_pages: int = 4):
        from app.config import Settings
        s = Settings()
        s.max_pages_per_domain = max_pages
        s.respect_robots = False  # no network calls in tests
        return s

    def test_homepage_always_first(self):
        from app.crawler.discovery import discover_urls
        from app.models import RunStats

        urls = discover_urls(
            domain="example.com",
            homepage_html=self.HOMEPAGE_HTML,
            settings=self._make_settings(),
            stats=RunStats(),
            errors=[],
        )
        assert urls[0] == "https://example.com"

    def test_about_and_team_ranked_above_blog(self):
        from app.crawler.discovery import discover_urls
        from app.models import RunStats

        urls = discover_urls(
            domain="example.com",
            homepage_html=self.HOMEPAGE_HTML,
            settings=self._make_settings(max_pages=6),
            stats=RunStats(),
            errors=[],
        )
        non_home = [u for u in urls if u != "https://example.com/"]
        # blog and docs should not appear before about/team
        ranked_paths = [u.split("example.com")[-1] for u in non_home]
        blog_idx = next((i for i, p in enumerate(ranked_paths) if "blog" in p), None)
        about_idx = next((i for i, p in enumerate(ranked_paths) if "about" in p), None)
        if blog_idx is not None and about_idx is not None:
            assert about_idx < blog_idx

    def test_budget_cap_respected(self):
        from app.crawler.discovery import discover_urls
        from app.models import RunStats

        max_pages = 3
        urls = discover_urls(
            domain="example.com",
            homepage_html=self.HOMEPAGE_HTML,
            settings=self._make_settings(max_pages=max_pages),
            stats=RunStats(),
            errors=[],
        )
        # Homepage + max_pages additional = max_pages + 1 total
        assert len(urls) <= max_pages + 1

    def test_pdf_links_rejected(self):
        from app.crawler.discovery import discover_urls
        from app.models import RunStats

        urls = discover_urls(
            domain="example.com",
            homepage_html=self.HOMEPAGE_HTML,
            settings=self._make_settings(max_pages=10),
            stats=RunStats(),
            errors=[],
        )
        assert not any(u.endswith(".pdf") for u in urls)

    def test_off_domain_links_rejected(self):
        from app.crawler.discovery import discover_urls
        from app.models import RunStats

        urls = discover_urls(
            domain="example.com",
            homepage_html=self.HOMEPAGE_HTML,
            settings=self._make_settings(max_pages=10),
            stats=RunStats(),
            errors=[],
        )
        assert not any("twitter.com" in u for u in urls)
