from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from pydantic import Field
from pydantic_core import to_jsonable_python

from .audit import verify_event_chain
from .models import (
    InterviewSession,
    JobSpec,
    StrictModel,
    VoxRubricTrace,
)


class PortableArtifactReference(StrictModel):
    artifact_id: str
    kind: str
    media_type: str
    size_bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    deleted: bool = False


class PortableEvidenceRecord(StrictModel):
    competency_id: str
    state: str
    confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
    )
    turn_id: str
    source: str
    note: str
    quote: str | None = None
    quote_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )


class PortableAuditAnchor(StrictModel):
    verified: bool | None = None
    head_hash: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    event_count: int = Field(ge=0)
    hash_version: int | None = Field(
        default=None,
        ge=1,
    )


class PortableVoxRubricAnchor(StrictModel):
    schema: str = "nora.voxrubric.anchor.v1"
    trace_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    turn_count: int = Field(ge=0)
    scorecard_count: int = Field(ge=0)


class PortableEvidenceBundle(StrictModel):
    schema: str = "nora.evidence.bundle.v1"
    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(
            timezone.utc
        )
    )
    organization_id: str | None = None
    session_id: str
    job_id: str
    role: str
    locale: str
    evidence: list[PortableEvidenceRecord]
    artifacts: list[PortableArtifactReference]
    audit: PortableAuditAnchor
    voxrubric: PortableVoxRubricAnchor
    bundle_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )


def _canonical_sha256(
    payload: object,
) -> str:
    encoded = json.dumps(
        to_jsonable_python(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(
        encoded
    ).hexdigest()


def _evidence_records(
    session: InterviewSession,
) -> list[PortableEvidenceRecord]:
    records: list[
        PortableEvidenceRecord
    ] = []

    for competency_id in sorted(
        session.evidence_graph
    ):
        competency = (
            session.evidence_graph[
                competency_id
            ]
        )
        for item in competency.evidence:
            if not item.active:
                continue
            quote_hash = (
                hashlib.sha256(
                    item.quote.encode(
                        "utf-8"
                    )
                ).hexdigest()
                if item.quote is not None
                else None
            )
            records.append(
                PortableEvidenceRecord(
                    competency_id=competency_id,
                    state=item.state.value,
                    confidence=item.confidence,
                    turn_id=item.turn_id,
                    source=item.source,
                    note=item.note,
                    quote=item.quote,
                    quote_sha256=quote_hash,
                )
            )

    return records


def _artifact_refs(
    session: InterviewSession,
) -> list[PortableArtifactReference]:
    return [
        PortableArtifactReference(
            artifact_id=item.id,
            kind=item.kind,
            media_type=item.media_type,
            size_bytes=item.size_bytes,
            sha256=item.sha256,
            deleted=(
                item.deleted_at
                is not None
            ),
        )
        for item in sorted(
            session.artifacts,
            key=lambda artifact: artifact.id,
        )
    ]


def build_portable_evidence_bundle(
    *,
    session: InterviewSession,
    job: JobSpec,
    trace: VoxRubricTrace,
) -> PortableEvidenceBundle:
    audit_head = verify_event_chain(
        session.events
    )
    audit = PortableAuditAnchor(
        verified=(
            True
            if audit_head is not None
            else None
        ),
        head_hash=audit_head,
        event_count=len(
            session.events
        ),
        hash_version=(
            1
            if audit_head is not None
            else None
        ),
    )

    trace_payload = trace.model_dump(
        mode="json"
    )
    voxrubric = PortableVoxRubricAnchor(
        trace_sha256=_canonical_sha256(
            trace_payload
        ),
        turn_count=len(
            trace.turns
        ),
        scorecard_count=len(
            trace.scorecards
        ),
    )

    unsigned = {
        "schema": "nora.evidence.bundle.v1",
        "organization_id": (
            session.organization_id
        ),
        "session_id": session.id,
        "job_id": job.id,
        "role": job.title,
        "locale": session.locale,
        "evidence": [
            item.model_dump(
                mode="json"
            )
            for item in _evidence_records(
                session
            )
        ],
        "artifacts": [
            item.model_dump(
                mode="json"
            )
            for item in _artifact_refs(
                session
            )
        ],
        "audit": audit.model_dump(
            mode="json"
        ),
        "voxrubric": voxrubric.model_dump(
            mode="json"
        ),
    }

    return PortableEvidenceBundle(
        organization_id=session.organization_id,
        session_id=session.id,
        job_id=job.id,
        role=job.title,
        locale=session.locale,
        evidence=_evidence_records(
            session
        ),
        artifacts=_artifact_refs(
            session
        ),
        audit=audit,
        voxrubric=voxrubric,
        bundle_sha256=_canonical_sha256(
            unsigned
        ),
    )
