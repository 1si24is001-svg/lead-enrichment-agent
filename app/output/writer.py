"""
app/output/writer.py
====================
Writes pipeline output to disk.

Files produced
--------------
output.json        — list of CompanyRecord, pretty-printed, stable key order.
output.csv         — flattened; one row per domain; list fields joined with "; ".
review_queue.json  — only low-confidence items; each entry has:
                     domain, field, value, confidence, source_url, reason.

The output path is --output from CLI (default: output.json).
CSV path = same stem with .csv extension.
review_queue.json is always written next to output.json.
"""

from __future__ import annotations

import csv
import json
import logging
from pathlib import Path
from typing import Any

from app.models import CompanyRecord

logger = logging.getLogger(__name__)


def write_outputs(
    records: list[CompanyRecord],
    output_path: Path,
    fmt: str,
    review_threshold: float,
) -> None:
    """Write output.json, output.csv (if requested), and review_queue.json.

    Parameters
    ----------
    records:
        All CompanyRecord objects from the pipeline run.
    output_path:
        Path for the primary output file (e.g. output.json).
    fmt:
        One of "json", "csv", "both".
    review_threshold:
        Records / fields below this confidence are written to review_queue.
    """
    if fmt in ("json", "both"):
        write_json(records, output_path)

    if fmt in ("csv", "both"):
        csv_path = output_path.with_suffix(".csv")
        write_csv(records, csv_path)

    review_path = output_path.parent / "review_queue.json"
    write_review_queue(records, review_path, review_threshold)


def write_json(records: list[CompanyRecord], path: Path) -> None:
    """Write records to a pretty-printed JSON file with stable key order."""
    data = [
        json.loads(r.model_dump_json())  # Pydantic v2 serialisation
        for r in records
    ]
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False, sort_keys=False),
        encoding="utf-8",
    )
    logger.info("[writer] Wrote %d records to %s", len(records), path)


def write_csv(records: list[CompanyRecord], path: Path) -> None:
    """Write records to a CSV file; list fields joined with '; '."""
    if not records:
        path.write_text("", encoding="utf-8")
        return

    rows = [_flatten_record(r) for r in records]
    fieldnames = list(rows[0].keys()) if rows else []

    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    logger.info("[writer] Wrote CSV to %s", path)


def write_review_queue(
    records: list[CompanyRecord],
    path: Path,
    threshold: float,
) -> None:
    """Write low-confidence items to review_queue.json.

    Each entry documents exactly what a human reviewer needs to check
    and why it was flagged, bridging automated extraction and manual QA.
    """
    items: list[dict[str, Any]] = []

    for record in records:
        if not record.needs_review:
            continue

        # Record-level flag
        if record.overall_confidence < threshold:
            items.append({
                "domain": record.domain,
                "field": "overall",
                "value": record.status,
                "confidence": record.overall_confidence,
                "source_url": None,
                "reason": f"Overall confidence {record.overall_confidence:.2f} below threshold {threshold:.2f}",
            })

        # Field-level flags
        for field_name, field_conf in record.field_confidence.items():
            if field_conf < threshold:
                value = None
                source_url = None

                if field_name == "overview":
                    value = record.overview
                    source_url = record.overview_evidence[0].source_url if record.overview_evidence else None
                elif field_name == "target_audience":
                    value = record.target_audience
                    source_url = record.target_audience_evidence[0].source_url if record.target_audience_evidence else None
                elif field_name == "generic_emails":
                    value = "; ".join(e.email for e in record.generic_emails)
                    source_url = record.generic_emails[0].evidence[0].source_url if record.generic_emails and record.generic_emails[0].evidence else None
                elif field_name == "people":
                    value = "; ".join(p.name for p in record.people)

                items.append({
                    "domain": record.domain,
                    "field": field_name,
                    "value": value,
                    "confidence": field_conf,
                    "source_url": source_url,
                    "reason": f"Field confidence {field_conf:.2f} below threshold {threshold:.2f}",
                })

        # Failed status
        if record.status == "failed":
            items.append({
                "domain": record.domain,
                "field": "status",
                "value": "failed",
                "confidence": 0.0,
                "source_url": None,
                "reason": f"Pipeline failed: {'; '.join(e.message for e in record.errors[:3])}",
            })

    path.write_text(
        json.dumps(items, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info("[writer] Wrote %d review queue items to %s", len(items), path)


def _flatten_record(record: CompanyRecord) -> dict[str, Any]:
    """Flatten a CompanyRecord to a single-row dict for CSV output."""
    return {
        "domain": record.domain,
        "status": record.status,
        "company_name": record.company_name or "",
        "overview": record.overview or "",
        "target_audience": record.target_audience or "",
        "generic_emails": "; ".join(e.email for e in record.generic_emails),
        "people": "; ".join(p.name for p in record.people),
        "people_roles": "; ".join(p.role or "" for p in record.people),
        "linkedin_urls": "; ".join(
            p.linkedin_url for p in record.people if p.linkedin_url
        ),
        "source_urls": "; ".join(record.source_urls),
        "overall_confidence": record.overall_confidence,
        "needs_review": record.needs_review,
        "pages_fetched": record.stats.pages_fetched,
        "pages_failed": record.stats.pages_failed,
        "prompt_tokens": record.stats.prompt_tokens,
        "completion_tokens": record.stats.completion_tokens,
        "estimated_cost_usd": record.stats.estimated_cost_usd,
        "duration_seconds": record.stats.duration_seconds,
        "cache_hits": record.stats.cache_hits,
        "errors": "; ".join(f"{e.stage}:{e.error_type}" for e in record.errors),
        "extracted_at": record.extracted_at.isoformat(),
    }
