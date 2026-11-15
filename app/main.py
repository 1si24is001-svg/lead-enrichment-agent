"""
app/main.py
===========
CLI entry-point for the Lead Enrichment Agent.

Usage
-----
    python -m app.main --domains postman.com supabase.com vapi.ai --output output.json

Exit codes
----------
    0 : all domains processed (even if some records are status="failed")
    1 : bad CLI arguments or missing API key (no output written)

No domain-specific logic lives here or anywhere else in the codebase.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _build_parser() -> argparse.ArgumentParser:
    """Build and return the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="lead-enrichment-agent",
        description="Crawl company websites and extract structured intelligence with evidence.",
    )

    # --- Domain input (mutually exclusive) ---
    domain_group = parser.add_mutually_exclusive_group(required=True)
    domain_group.add_argument(
        "--domains",
        nargs="+",
        metavar="DOMAIN",
        help="One or more company domains to enrich (e.g. postman.com supabase.com).",
    )
    domain_group.add_argument(
        "--domains-file",
        metavar="PATH",
        help="Path to a newline-separated file of domains.",
    )

    # --- Output ---
    parser.add_argument(
        "--output",
        default="output.json",
        metavar="PATH",
        help="Output file path. Default: output.json",
    )
    parser.add_argument(
        "--format",
        choices=["json", "csv", "both"],
        default="json",
        help="Output format. Default: json",
    )

    # --- Crawl budget ---
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        metavar="N",
        help="Maximum pages to fetch per domain (overrides MAX_PAGES_PER_DOMAIN env var). Default: 6",
    )

    # --- LLM provider ---
    parser.add_argument(
        "--provider",
        choices=["openai", "gemini"],
        default=None,
        help="LLM provider (overrides LLM_PROVIDER env var).",
    )

    # --- Cache control ---
    cache_group = parser.add_mutually_exclusive_group()
    cache_group.add_argument(
        "--replay",
        action="store_true",
        help="Cache-only mode: never touch the network. Errors clearly on a cache miss.",
    )
    cache_group.add_argument(
        "--no-cache",
        action="store_true",
        help="Ignore existing cache; always fetch from network and overwrite cache.",
    )

    # --- Confidence ---
    parser.add_argument(
        "--review-threshold",
        type=float,
        default=None,
        metavar="F",
        help="Confidence below which records are flagged for human review. Default: 0.6",
    )

    # --- Logging ---
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING"],
        default="INFO",
        help="Logging verbosity. Default: INFO",
    )

    return parser


def _normalize_domain(raw: str) -> str:
    """Strip scheme, www., trailing slash; lowercase.

    Examples
    --------
    >>> _normalize_domain("https://www.Postman.com/")
    'postman.com'
    """
    domain = raw.strip().lower()
    for prefix in ("https://", "http://"):
        if domain.startswith(prefix):
            domain = domain[len(prefix):]
    if domain.startswith("www."):
        domain = domain[4:]
    domain = domain.rstrip("/").split("/")[0]  # strip any path
    return domain


def _load_domains_from_file(path: str) -> list[str]:
    """Read newline-separated domains from a file."""
    p = Path(path)
    if not p.exists():
        raise SystemExit(f"[main] --domains-file not found: {path}")
    lines = p.read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.startswith("#")]


def main(argv: list[str] | None = None) -> int:
    """Parse arguments, wire settings, run pipeline, write outputs.

    Returns the process exit code (0 on success / partial failure, 1 on arg error).
    """
    # --- Imports deferred so argparse --help works without heavy deps installed ---
    from app.config import settings
    from app.util.logging import setup_logging
    from app.pipeline import enrich_domain
    from app.output.writer import write_outputs
    from app.output.report import print_summary

    parser = _build_parser()
    args = parser.parse_args(argv)

    # --- Apply CLI overrides to settings singleton ---
    if args.provider:
        settings.llm_provider = args.provider
    if args.max_pages is not None:
        settings.max_pages_per_domain = args.max_pages
    if args.review_threshold is not None:
        settings.review_threshold = args.review_threshold

    # --- Logging ---
    setup_logging(args.log_level)

    # --- Collect domains ---
    if args.domains:
        raw_domains = args.domains
    else:
        raw_domains = _load_domains_from_file(args.domains_file)

    if not raw_domains:
        parser.error("No domains provided.")

    domains = [_normalize_domain(d) for d in raw_domains]

    # --- API key check (skip in replay mode — no LLM calls needed) ---
    if not args.replay:
        settings.validate_api_key()

    # --- Run pipeline per domain (failures are isolated) ---
    records = []
    for domain in domains:
        record = enrich_domain(
            domain=domain,
            settings=settings,
            replay=args.replay,
            no_cache=args.no_cache,
        )
        records.append(record)

    # --- Write outputs ---
    output_path = Path(args.output)
    write_outputs(
        records=records,
        output_path=output_path,
        fmt=args.format,
        review_threshold=settings.review_threshold,
    )

    # --- Console summary ---
    print_summary(records)

    return 0


if __name__ == "__main__":
    sys.exit(main())
