"""
app/crawler/cache.py
====================
Disk cache for fetched pages AND LLM responses.

Cache layout
------------
    cache/
    ├── pages/
    │   └── <sha1(url)>.json          {url, html, status, fetched_at}
    └── llm/
        └── <sha1(provider|model|prompt)>.json   {data, prompt_tokens, completion_tokens, model, raw, cached_at}

Mode behaviour
--------------
- Default (read-through): return cached entry if present; fetch/call on miss and store result.
- --replay: return cached entry; raise CacheMissError (descriptive, not a generic exception)
  on miss, naming the missing URL so the reviewer knows exactly what to do.
- --no-cache: ignore existing entries; always fetch/call and overwrite.

Why committed cache?
--------------------
The cache/ directory is deliberately committed (see .gitignore).  This lets the
reviewer run ``python -m app.main --replay`` with no API key and no Playwright
browser download, removing all setup friction.  Stored content is cleaned text
(not raw HTML) to keep the directory under ~5 MB.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class CacheMissError(Exception):
    """Raised in --replay mode when a requested URL or LLM key is not cached.

    The message includes the missing key and the cache directory path so the
    reviewer knows exactly why replay failed.
    """


class PageCache:
    """Manages disk storage and retrieval of fetched page HTML."""

    def __init__(self, cache_dir: Path) -> None:
        self._dir = cache_dir / "pages"
        self._dir.mkdir(parents=True, exist_ok=True)

    def _key(self, url: str) -> Path:
        sha = hashlib.sha1(url.encode()).hexdigest()
        return self._dir / f"{sha}.json"

    def get(self, url: str) -> dict[str, Any] | None:
        """Return cached page dict or None if not cached."""
        path = self._key(url)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logger.warning("[cache] Corrupted page cache entry for %s — ignoring.", url)
            return None

    def put(self, url: str, html: str, status: int) -> None:
        """Store a fetched page to disk."""
        data = {
            "url": url,
            "html": html,
            "status": status,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
        self._key(url).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def require(self, url: str) -> dict[str, Any]:
        """Return cached entry or raise CacheMissError (for --replay mode)."""
        entry = self.get(url)
        if entry is None:
            raise CacheMissError(
                f"[cache] --replay mode: no cached page for {url!r}.\n"
                f"Cache directory: {self._dir}\n"
                f"Run without --replay to fetch and cache this page first."
            )
        return entry


class LLMCache:
    """Manages disk storage and retrieval of LLM responses."""

    def __init__(self, cache_dir: Path) -> None:
        self._dir = cache_dir / "llm"
        self._dir.mkdir(parents=True, exist_ok=True)

    def _key(self, provider: str, model: str, prompt: str) -> Path:
        content = f"{provider}|{model}|{prompt}"
        sha = hashlib.sha1(content.encode()).hexdigest()
        return self._dir / f"{sha}.json"

    def get(self, provider: str, model: str, prompt: str) -> dict[str, Any] | None:
        """Return cached LLM response dict or None if not cached."""
        path = self._key(provider, model, prompt)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logger.warning("[cache] Corrupted LLM cache entry — ignoring.")
            return None

    def put(self, provider: str, model: str, prompt: str, response: dict[str, Any]) -> None:
        """Store an LLM response to disk."""
        data = {**response, "cached_at": datetime.now(timezone.utc).isoformat()}
        self._key(provider, model, prompt).write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def require(self, provider: str, model: str, prompt: str) -> dict[str, Any]:
        """Return cached entry or raise CacheMissError (for --replay mode)."""
        entry = self.get(provider, model, prompt)
        if entry is None:
            raise CacheMissError(
                f"[cache] --replay mode: no cached LLM response for "
                f"provider={provider!r} model={model!r}.\n"
                f"Cache directory: {self._dir}\n"
                f"Run without --replay to make the LLM call and cache the response."
            )
        return entry
