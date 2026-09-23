from __future__ import annotations

from pydantic import Field

from .models import (
    AppealStatus,
    EvidenceState,
    InterviewSession,
    JobSpec,
    StrictModel,
    ToolStatus,
)


class CompetencyReviewSummary(StrictModel):
    competency_id: str
    description: str
    state: EvidenceState
    confidence: float | None = None
    evidence_count: int = Field(ge=0)
    source_types: list[str] = Field(default_factory=list)


class ReviewReason(StrictModel):
    code: str = Field(min_length=1, max_length=120)
    summary: str = Field(min_length=1, max_length=500)
    severity: str = Field(pattern=r"^(info|attention|high)$")


class AppealReviewSummary(StrictModel):
    id: str
    message: str
    turn_ids: list[str] = Field(default_factory=list)
    status: AppealStatus
    reviewed_by: str | None = None
    review_note: str | None = None


class IntegrityReviewSummary(StrictModel):
    id: str
    kind: str
    confidence: float = Field(ge=0.0, le=1.0)
    note: str
    requires_human_review: bool = True


class RecruiterSessionReport(StrictModel):
    session_id: str
    job_id: str
    role: str
    candidate_ref: str
    status: str
    competencies: list[CompetencyReviewSummary]
    reasons: list[ReviewReason] = Field(default_factory=list)
    appeals: list[AppealReviewSummary] = Field(default_factory=list)
    integrity: list[IntegrityReviewSummary] = Field(default_factory=list)
    pending_appeals: int = Field(ge=0)
    integrity_signals: int = Field(ge=0)
    unresolved_tools: int = Field(ge=0)
    transcript_revisions: int = Field(ge=0)
    requires_human_review: bool
    note: str = (
        "This report summarizes interview evidence and review conditions. "
        "It does not make or recommend a final hiring decision."
    )


class ReviewQueueItem(StrictModel):
    session_id: str
    job_id: str
    candidate_ref: str
    role: str
    status: str
    requires_human_review: bool
    reason_codes: list[str] = Field(default_factory=list)
    pending_appeals: int = Field(ge=0)
    integrity_signals: int = Field(ge=0)
    unresolved_tools: int = Field(ge=0)


def build_recruiter_report(
    session: InterviewSession,
    job: JobSpec,
) -> RecruiterSessionReport:
    competencies: list[CompetencyReviewSummary] = []
    reasons: list[ReviewReason] = []

    for competency in job.competencies:
        node = session.evidence_graph.get(competency.id)
        state = node.state if node else EvidenceState.UNKNOWN
        confidence = node.confidence if node else None
        evidence = node.evidence if node else []
        competencies.append(
            CompetencyReviewSummary(
                competency_id=competency.id,
                description=competency.description,
                state=state,
                confidence=confidence,
                evidence_count=len(evidence),
                source_types=sorted({item.source for item in evidence}),
            )
        )

        if state is EvidenceState.CONTRADICTED:
            reasons.append(
                ReviewReason(
                    code="conflicting_evidence",
                    severity="high",
                    summary=(
                        f"Competency {competency.id!r} contains contradicted evidence."
                    ),
                )
            )
        elif state in {
            EvidenceState.UNKNOWN,
            EvidenceState.INSUFFICIENT,
            EvidenceState.CLAIMED,
        }:
            reasons.append(
                ReviewReason(
                    code="insufficient_evidence",
                    severity="attention",
                    summary=(
                        f"Competency {competency.id!r} lacks demonstrated or verified evidence."
                    ),
                )
            )

    appeals = [
        AppealReviewSummary(
            id=item.id,
            message=item.message,
            turn_ids=item.turn_ids,
            status=item.status,
            reviewed_by=item.reviewed_by,
            review_note=item.review_note,
        )
        for item in session.appeals
    ]
    pending_appeals = sum(
        item.status is AppealStatus.PENDING
        for item in session.appeals
    )
    if pending_appeals:
        reasons.append(
            ReviewReason(
                code="pending_appeal",
                severity="high",
                summary=f"{pending_appeals} candidate appeal(s) require review.",
            )
        )

    integrity = [
        IntegrityReviewSummary(
            id=item.id,
            kind=item.kind,
            confidence=item.confidence,
            note=item.note,
            requires_human_review=item.requires_human_review,
        )
        for item in session.integrity_signals
    ]
    integrity_signals = len(integrity)
    if integrity_signals:
        reasons.append(
            ReviewReason(
                code="integrity_signal",
                severity="high",
                summary=(
                    f"{integrity_signals} integrity signal(s) require human review."
                ),
            )
        )

    unresolved_tools = sum(
        tool.status in {ToolStatus.OPEN, ToolStatus.SUBMITTED}
        for tool in session.tools
    )
    unresolved_tools += sum(
        evaluation.passed is None
        for evaluation in session.tool_evaluations
    )
    if unresolved_tools:
        reasons.append(
            ReviewReason(
                code="tool_review_pending",
                severity="attention",
                summary=(
                    f"{unresolved_tools} practical artifact review item(s) remain unresolved."
                ),
            )
        )

    if session.transcript_revisions:
        reasons.append(
            ReviewReason(
                code="transcript_revised",
                severity="info",
                summary=(
                    f"{len(session.transcript_revisions)} candidate transcript "
                    "revision(s) are present in the audit history."
                ),
            )
        )

    requires_human_review = any(
        reason.severity in {"attention", "high"}
        for reason in reasons
    )

    return RecruiterSessionReport(
        session_id=session.id,
        job_id=session.job_id,
        role=job.title,
        candidate_ref=session.candidate_ref,
        status=session.status.value,
        competencies=competencies,
        reasons=reasons,
        appeals=appeals,
        integrity=integrity,
        pending_appeals=pending_appeals,
        integrity_signals=integrity_signals,
        unresolved_tools=unresolved_tools,
        transcript_revisions=len(session.transcript_revisions),
        requires_human_review=requires_human_review,
    )


def to_queue_item(report: RecruiterSessionReport) -> ReviewQueueItem:
    return ReviewQueueItem(
        session_id=report.session_id,
        job_id=report.job_id,
        candidate_ref=report.candidate_ref,
        role=report.role,
        status=report.status,
        requires_human_review=report.requires_human_review,
        reason_codes=list(dict.fromkeys(reason.code for reason in report.reasons)),
        pending_appeals=report.pending_appeals,
        integrity_signals=report.integrity_signals,
        unresolved_tools=report.unresolved_tools,
    )
