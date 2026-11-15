"""
app/util/logging.py
===================
Structured logging setup.

Configures the root logger with:
- Console handler (stderr) with a consistent format.
- Log level controlled by --log-level CLI flag (default: INFO).

Format
------
    2026-01-15 14:22:03 INFO     [pipeline] Starting enrichment for domain: postman.com
    2026-01-15 14:22:05 WARNING  [verify] Unverified snippet in field 'overview' (postman.com)

Call setup_logging() once from main.py before any pipeline code runs.
"""

from __future__ import annotations

import logging
import sys


def setup_logging(level: str = "INFO") -> None:
    """Configure the root logger for the application.

    Parameters
    ----------
    level:
        One of "DEBUG", "INFO", "WARNING".
    """
    numeric_level = getattr(logging, level.upper(), logging.INFO)

    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)-8s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(numeric_level)

    # Silence noisy third-party loggers
    for noisy in ("httpx", "httpcore", "openai", "google", "urllib3", "playwright"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
