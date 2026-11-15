"""
app/util/errors.py
==================
Error taxonomy for the pipeline.

Using structured error types lets the pipeline make precise decisions about
recoverability and surfaces clean diagnostics in review_queue.json and the
console summary.

Error categories
----------------
NetworkError     : DNS failure, connection refused, SSL error.
TimeoutError     : Page load or API call exceeded the timeout.
HTTP4xxError     : 4xx response (404 Not Found, 403 Forbidden, etc.).
HTTP5xxError     : 5xx response (server error) — treated as transient.
RobotsBlocked    : robots.txt disallows the URL.
ParseError       : HTML/JSON parsing failed unexpectedly.
LLMRateLimit     : 429 from the LLM provider.
LLMInvalidJSON   : LLM returned non-parseable output after retries.
ValidationError  : Pydantic model validation failed after retry.
CacheMiss        : --replay mode hit a missing cache entry.
"""

from __future__ import annotations


class LeadEnrichmentError(Exception):
    """Base class for all pipeline-specific errors.

    These are caught at the pipeline level and converted to ErrorRecord objects.
    They should not escape enrich_domain().
    """
    recoverable: bool = True


class NetworkError(LeadEnrichmentError):
    """DNS failure, connection refused, SSL error, or other network-level issue."""
    recoverable: bool = True


class FetchTimeoutError(LeadEnrichmentError):
    """Page load exceeded the configured timeout (REQUEST_TIMEOUT_MS)."""
    recoverable: bool = True  # retried with backoff


class HTTP4xxError(LeadEnrichmentError):
    """4xx HTTP response received.

    404 and 403 are not retried (they are definitive); other 4xx may vary.
    """
    def __init__(self, status_code: int, url: str) -> None:
        self.status_code = status_code
        self.url = url
        super().__init__(f"HTTP {status_code} for {url}")
    recoverable: bool = False


class HTTP5xxError(LeadEnrichmentError):
    """5xx HTTP response — treated as transient and retried with backoff."""
    def __init__(self, status_code: int, url: str) -> None:
        self.status_code = status_code
        self.url = url
        super().__init__(f"HTTP {status_code} for {url}")
    recoverable: bool = True


class RobotsBlockedError(LeadEnrichmentError):
    """robots.txt disallows crawling this URL (only when RESPECT_ROBOTS=true)."""
    recoverable: bool = False


class ParseError(LeadEnrichmentError):
    """HTML or JSON parsing failed unexpectedly."""
    recoverable: bool = False


class LLMRateLimitError(LeadEnrichmentError):
    """LLM provider returned a 429 Too Many Requests response."""
    recoverable: bool = True  # would retry with larger backoff in production


class LLMInvalidJSONError(LeadEnrichmentError):
    """LLM returned non-parseable JSON after the maximum retry attempts."""
    recoverable: bool = False


class LLMValidationError(LeadEnrichmentError):
    """Pydantic validation of the LLM output failed after the retry loop."""
    recoverable: bool = False


class CacheMissError(LeadEnrichmentError):
    """--replay mode: requested URL or LLM key is not in the cache."""
    recoverable: bool = False


def classify_exception(exc: Exception) -> str:
    """Map a raw exception to an error_type string for ErrorRecord.

    Returns the class name by default; special-cases common stdlib and
    third-party exceptions for cleaner output.
    """
    exc_type = type(exc).__name__

    # Map playwright / httpx / requests exception names to cleaner strings
    mappings = {
        "TimeoutError": "TimeoutError",
        "PlaywrightTimeoutError": "TimeoutError",
        "ConnectionError": "NetworkError",
        "SSLError": "NetworkError",
        "JSONDecodeError": "ParseError",
        "ValidationError": "ValidationError",
    }
    return mappings.get(exc_type, exc_type)
