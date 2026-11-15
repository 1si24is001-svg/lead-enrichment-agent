"""
app/config.py
=============
Settings dataclass populated from environment variables via python-dotenv.

All constants that appear in the spec live here so they can be overridden from
the CLI or env without touching pipeline code.  Price tables are kept here so
cost logging works for any provider and is easy to update.

Usage
-----
    from app.config import Settings
    cfg = Settings()   # reads .env automatically
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the project root (two levels up from this file)
_PROJECT_ROOT = Path(__file__).parent.parent
load_dotenv(_PROJECT_ROOT / ".env", override=False)


# ---------------------------------------------------------------------------
# Cost table  (USD per 1 M tokens; update when providers change pricing)
# ---------------------------------------------------------------------------

# Format: { provider: { model_substring: (input_price, output_price) } }
# Match is done by checking whether model_substring appears in the model name.
TOKEN_PRICES: dict[str, dict[str, tuple[float, float]]] = {
    "openai": {
        "gpt-4o-mini": (0.15, 0.60),    # $0.15 / 1M input, $0.60 / 1M output
        "gpt-4o":      (5.00, 15.00),
        "gpt-4-turbo": (10.00, 30.00),
        "gpt-3.5-turbo": (0.50, 1.50),
    },
    "gemini": {
        "gemini-3.6-flash": (0.075, 0.30),
        "gemini-2.0-flash": (0.075, 0.30),
        "gemini-1.5-flash": (0.075, 0.30),
        "gemini-1.5-pro":   (3.50, 10.50),
        "gemini-2.5-pro":   (1.25, 10.00),
    },
}

DEFAULT_TOKEN_PRICE: tuple[float, float] = (1.00, 3.00)  # fallback if model not matched


def _price_for_model(provider: str, model: str) -> tuple[float, float]:
    """Return (input_price_per_1m, output_price_per_1m) for the given model.

    Falls back to DEFAULT_TOKEN_PRICE if the model is not in the table.
    """
    table = TOKEN_PRICES.get(provider.lower(), {})
    for substring, prices in table.items():
        if substring in model.lower():
            return prices
    return DEFAULT_TOKEN_PRICE


# ---------------------------------------------------------------------------
# Discovery scoring table (spec §Stage 1)
# ---------------------------------------------------------------------------

PAGE_SCORES: dict[str, int] = {
    "about": 10,
    "about-us": 10,
    "company": 9,
    "who-we-are": 9,
    "team": 10,
    "leadership": 10,
    "management": 9,
    "people": 8,
    "founders": 9,
    "contact": 10,
    "contact-us": 10,
    "support": 5,
    "pricing": 7,
    "plans": 6,
    "customers": 4,
    "case-studies": 3,
    "careers": 3,
    "jobs": 3,
    "blog": -5,
    "docs": -10,
    "documentation": -10,
    "login": -10,
    "signup": -10,
    "privacy": -8,
    "terms": -8,
    "cookie": -8,
}

# Extensions we skip during link discovery
SKIP_EXTENSIONS: frozenset[str] = frozenset({
    ".pdf", ".zip", ".jpg", ".jpeg", ".png", ".svg", ".xml",
    ".gif", ".mp4", ".mp3", ".webp", ".ico", ".woff", ".woff2",
    ".ttf", ".eot", ".css", ".js",
})

# Generic/role-based email prefixes that are allowed through the filter
GENERIC_EMAIL_PREFIXES: frozenset[str] = frozenset({
    "info", "hello", "contact", "support", "sales",
    "press", "careers", "security", "privacy",
})


# ---------------------------------------------------------------------------
# Settings dataclass
# ---------------------------------------------------------------------------

@dataclass
class Settings:
    """All runtime configuration in one place.

    Populated from environment variables; CLI flags override these at startup
    by mutating the singleton before any pipeline code runs.
    """

    # --- LLM provider ---
    llm_provider: str = field(
        default_factory=lambda: os.getenv("LLM_PROVIDER", "openai").lower()
    )
    openai_api_key: str | None = field(
        default_factory=lambda: os.getenv("OPENAI_API_KEY")
    )
    openai_model: str = field(
        default_factory=lambda: os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    )
    gemini_api_key: str | None = field(
        default_factory=lambda: os.getenv("GEMINI_API_KEY")
    )
    gemini_model: str = field(
        default_factory=lambda: os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
    )

    # --- Crawl budget ---
    max_pages_per_domain: int = field(
        default_factory=lambda: int(os.getenv("MAX_PAGES_PER_DOMAIN", "6"))
    )

    # --- Text budget ---
    max_chars_per_page: int = 6_000
    max_chars_per_domain: int = 18_000

    # --- Confidence / review ---
    review_threshold: float = field(
        default_factory=lambda: float(os.getenv("REVIEW_THRESHOLD", "0.6"))
    )

    # --- Boilerplate removal ---
    boilerplate_page_fraction: float = 0.60  # line on >=60% of pages → drop

    # --- Network / browser ---
    request_timeout_ms: int = field(
        default_factory=lambda: int(os.getenv("REQUEST_TIMEOUT_MS", "20000"))
    )
    fetch_settle_ms: int = 1_500          # wait after networkidle
    retry_count: int = 2                  # number of retries on transient errors
    retry_backoff_seconds: list[float] = field(
        default_factory=lambda: [2.0, 4.0]
    )

    # --- robots.txt ---
    respect_robots: bool = field(
        default_factory=lambda: os.getenv("RESPECT_ROBOTS", "true").lower() == "true"
    )

    # --- Paths ---
    cache_dir: Path = field(default_factory=lambda: _PROJECT_ROOT / "cache")
    output_dir: Path = field(default_factory=lambda: _PROJECT_ROOT)

    # --- LLM retry ---
    llm_max_attempts: int = 2  # first attempt + one retry with validation error

    # --- Viewport ---
    browser_viewport_width: int = 1440
    browser_viewport_height: int = 900
    browser_user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )

    # ---------------------------------------------------------------------------
    # Derived helpers
    # ---------------------------------------------------------------------------

    def active_model(self) -> str:
        """Return the model name for the currently selected provider."""
        if self.llm_provider == "openai":
            return self.openai_model
        elif self.llm_provider == "gemini":
            return self.gemini_model
        raise ValueError(f"Unknown LLM provider: {self.llm_provider!r}")

    def active_api_key(self) -> str | None:
        """Return the API key for the currently selected provider."""
        if self.llm_provider == "openai":
            return self.openai_api_key
        elif self.llm_provider == "gemini":
            return self.gemini_api_key
        return None

    def token_prices(self) -> tuple[float, float]:
        """Return (input_price_per_1m, output_price_per_1m) for the active model."""
        return _price_for_model(self.llm_provider, self.active_model())

    def estimate_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        """Estimate USD cost for a single LLM call."""
        input_price, output_price = self.token_prices()
        return (
            prompt_tokens * input_price / 1_000_000
            + completion_tokens * output_price / 1_000_000
        )

    def validate_api_key(self) -> None:
        """Raise SystemExit if no API key is set and we're not in replay mode.

        Called from main.py before starting the pipeline.  Replay mode bypasses
        this check because it never touches the LLM.
        """
        key = self.active_api_key()
        if not key:
            raise SystemExit(
                f"[config] No API key found for provider '{self.llm_provider}'.\n"
                f"Set {'OPENAI_API_KEY' if self.llm_provider == 'openai' else 'GEMINI_API_KEY'} "
                f"in your .env file or environment.  "
                f"To run without a key, use --replay (cache only)."
            )


# ---------------------------------------------------------------------------
# Module-level singleton — import and mutate from main.py before pipeline runs
# ---------------------------------------------------------------------------

settings = Settings()
