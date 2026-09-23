from __future__ import annotations

from datetime import datetime, timezone

from pydantic import Field

from .models import StrictModel, VoxRubricTrace
from .review import RecruiterSessionReport


class AuditBundleSummary(StrictModel):
    verified: bool | None = None
    head_hash: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    event_count: int = Field(ge=0)
    hash_version: int | None = Field(default=None, ge=1)


class ReviewBundle(StrictModel):
    schema_version: str = "1.0"
    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    report: RecruiterSessionReport
    trace: VoxRubricTrace
    audit: AuditBundleSummary


def build_review_bundle(
    *,
    report: RecruiterSessionReport,
    trace: VoxRubricTrace,
) -> ReviewBundle:
    audit_raw = trace.metadata.get("audit_chain", {})
    audit_raw = audit_raw if isinstance(audit_raw, dict) else {}

    return ReviewBundle(
        report=report,
        trace=trace,
        audit=AuditBundleSummary(
            verified=audit_raw.get("verified"),
            head_hash=audit_raw.get("head_hash"),
            event_count=int(
                audit_raw.get(
                    "event_count",
                    trace.metadata.get("event_count", 0),
                )
                or 0
            ),
            hash_version=audit_raw.get("hash_version"),
        ),
    )
