"""
tests/test_clean.py
===================
Unit tests for app/extract/clean.py.

All tests are offline — no network, no LLM, no browser.
"""

import pytest


class TestCleanHtml:
    """Tests for clean_html() — single-page HTML → plain text conversion."""

    def test_strips_script_tags(self):
        """<script> content must not appear in cleaned output."""
        from app.extract.clean import clean_html

        html = "<html><body><p>Hello</p><script>alert('evil')</script></body></html>"
        result = clean_html(html)
        assert "alert" not in result
        assert "Hello" in result

    def test_strips_style_tags(self):
        """<style> blocks must be removed."""
        from app.extract.clean import clean_html

        html = "<html><head><style>body { color: red; }</style></head><body><p>Text</p></body></html>"
        result = clean_html(html)
        assert "color: red" not in result

    def test_strips_nav_and_footer(self):
        """<nav> and <footer> elements must be removed."""
        from app.extract.clean import clean_html

        html = """
        <html><body>
          <nav>Home | About | Contact</nav>
          <p>Main content here.</p>
          <footer>© 2024 Company</footer>
        </body></html>
        """
        result = clean_html(html)
        assert "Home | About | Contact" not in result
        assert "© 2024 Company" not in result
        assert "Main content here." in result

    def test_strips_cookie_banner_by_class(self):
        """Elements with class containing 'cookie' or 'banner' must be removed."""
        from app.extract.clean import clean_html

        html = """
        <html><body>
          <div class="cookie-banner">We use cookies.</div>
          <p>Real content.</p>
        </body></html>
        """
        result = clean_html(html)
        assert "We use cookies." not in result
        assert "Real content." in result

    def test_strips_aria_hidden(self):
        """Elements with aria-hidden="true" must be removed."""
        from app.extract.clean import clean_html

        html = """
        <html><body>
          <span aria-hidden="true">Decorative icon text</span>
          <p>Visible content</p>
        </body></html>
        """
        result = clean_html(html)
        assert "Decorative icon text" not in result
        assert "Visible content" in result

    def test_preserves_main_content(self):
        """Meaningful text in the body must be preserved."""
        from app.extract.clean import clean_html

        html = "<html><body><h1>About Us</h1><p>We build APIs for developers.</p></body></html>"
        result = clean_html(html)
        assert "About Us" in result
        assert "We build APIs for developers." in result

    def test_collapses_whitespace(self):
        """Multiple blank lines and extra spaces must be collapsed."""
        from app.extract.clean import clean_html

        html = "<html><body><p>Line   one</p><p></p><p></p><p>Line two</p></body></html>"
        result = clean_html(html)
        # Should not have more than 2 consecutive newlines
        assert "\n\n\n" not in result


class TestRemoveBoilerplate:
    """Tests for remove_boilerplate() — cross-page deduplication."""

    def test_removes_line_on_all_pages(self):
        """A line appearing on all pages must be dropped."""
        from app.extract.clean import remove_boilerplate

        pages = {
            "https://example.com/": "Navbar text\nHome content",
            "https://example.com/about": "Navbar text\nAbout content",
            "https://example.com/team": "Navbar text\nTeam content",
        }
        result, lines_removed, chars_removed = remove_boilerplate(pages, fraction=0.60)
        for text in result.values():
            assert "Navbar text" not in text
        assert lines_removed > 0
        assert chars_removed > 0

    def test_keeps_line_on_minority_of_pages(self):
        """A line appearing on fewer than fraction of pages must be kept."""
        from app.extract.clean import remove_boilerplate

        pages = {
            "https://example.com/": "Unique home content\nShared footer",
            "https://example.com/about": "Unique about content\nShared footer",
            "https://example.com/team": "Unique team content\nShared footer",
            "https://example.com/pricing": "Rare line\nShared footer",
        }
        # "Rare line" appears on 1/4 = 25% of pages — below 60% threshold
        result, _, _ = remove_boilerplate(pages, fraction=0.60)
        assert any("Rare line" in text for text in result.values())

    def test_returns_line_and_char_counts(self):
        """Must return accurate (lines_removed, chars_removed) counts."""
        from app.extract.clean import remove_boilerplate

        repeated_line = "Repeated nav item"
        pages = {
            "https://example.com/": f"{repeated_line}\nUnique A",
            "https://example.com/about": f"{repeated_line}\nUnique B",
        }
        _, lines_removed, chars_removed = remove_boilerplate(pages, fraction=0.50)
        assert lines_removed >= 2  # one removal per page
        assert chars_removed >= len(repeated_line) * 2


class TestTrimToBudget:
    """Tests for trim_to_budget() — character budget enforcement."""

    def test_does_not_truncate_short_text(self):
        """Text below max_chars must be returned unchanged."""
        from app.extract.clean import trim_to_budget

        text = "Short text."
        assert trim_to_budget(text, 1000) == text

    def test_truncates_at_paragraph_boundary(self):
        """Must cut at a blank line, not mid-sentence or mid-word."""
        from app.extract.clean import trim_to_budget

        text = "First paragraph content.\n\nSecond paragraph with more words.\n\nThird paragraph."
        # Set budget to cut after first paragraph
        result = trim_to_budget(text, 30)
        assert "Third paragraph" not in result
        # Must not end mid-word
        words = result.split()
        assert all(w == w.strip() for w in words)
