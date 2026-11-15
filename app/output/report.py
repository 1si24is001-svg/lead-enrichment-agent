"""
app/output/report.py
====================
Console run summary + token/cost accounting.

Prints a formatted table to stdout after all domains are processed:

    domain          status   pages  people  emails  conf   tokens   cost     time
    postman.com     success      6       4       2   0.84   11,240   $0.011   18.2s
    supabase.com    success      6       3       1   0.79    9,870   $0.009   15.6s
    vapi.ai         partial      4       1       1   0.61    5,120   $0.005    9.4s
    ─────────────────────────────────────────────────────────────────────────────
    3 domains  ·  16 pages  ·  26,230 tokens  ·  $0.025  ·  43.2s  ·  0 hallucinated fields

The "hallucinated fields" count = number of evidence objects with verified=False
across all records.  This is the key number: zero hallucinations is the goal.
"""

from __future__ import annotations

import logging

from app.models import CompanyRecord
from app.extract.verify import collect_all_evidence

logger = logging.getLogger(__name__)

_HEADER = (
    f"{'domain':<20} {'status':<8} {'pages':>5} {'people':>7} "
    f"{'emails':>7} {'conf':>6} {'tokens':>8} {'cost':>8} {'time':>7}"
)
_SEP = "-" * len(_HEADER)


def print_summary(records: list[CompanyRecord]) -> None:
    """Print the formatted run summary table to stdout.

    Parameters
    ----------
    records:
        All CompanyRecord objects from the pipeline run.
    """
    print()
    print(_HEADER)

    total_pages = 0
    total_tokens = 0
    total_cost = 0.0
    total_time = 0.0

    for r in records:
        tokens = r.stats.prompt_tokens + r.stats.completion_tokens
        pages = r.stats.pages_fetched
        total_pages += pages
        total_tokens += tokens
        total_cost += r.stats.estimated_cost_usd
        total_time += r.stats.duration_seconds

        print(
            f"{r.domain:<20} {r.status:<8} {pages:>5} "
            f"{len(r.people):>7} {len(r.generic_emails):>7} "
            f"{r.overall_confidence:>6.2f} {tokens:>8,} "
            f"${r.stats.estimated_cost_usd:>7.3f} {r.stats.duration_seconds:>6.1f}s"
        )

    print(_SEP)

    unverified = _count_unverified_evidence(records)
    nd = len(records)
    print(
        f"{nd} domain{'s' if nd != 1 else ''}  |  {total_pages} pages  |  "
        f"{total_tokens:,} tokens  |  ${total_cost:.3f}  |  "
        f"{total_time:.1f}s  |  {unverified} hallucinated fields"
    )
    print()


def _count_unverified_evidence(records: list[CompanyRecord]) -> int:
    """Count evidence objects with verified=False across all records.

    This is the "hallucinated fields" count in the summary line.
    """
    count = 0
    for record in records:
        for _, ev in collect_all_evidence(record):
            if not ev.verified:
                count += 1
    return count


def _total_tokens(records: list[CompanyRecord]) -> tuple[int, int]:
    """Return (total_prompt_tokens, total_completion_tokens) across all records."""
    prompt = sum(r.stats.prompt_tokens for r in records)
    completion = sum(r.stats.completion_tokens for r in records)
    return prompt, completion
