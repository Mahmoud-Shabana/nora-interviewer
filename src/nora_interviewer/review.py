from __future__ import annotations

from pydantic import Field

from .models import (
    AppealStatus,
    EvidenceState,
    IntegrityReviewStatus,
    InterviewSession,
    JobSpec,
    ReviewAssignmentStatus,
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


class EvidenceJudgeRunSummary(StrictModel):
    id: str
    judge_id: str
    answer_turn_id: str
    created_at: str
    transcript_revision_count: int = Field(ge=0)
    current_transcript_revision_count: int = Field(ge=0)
    observation_count: int = Field(ge=0)
    failed: bool
    stale: bool
    supersedes_run_id: str | None = None


class ReviewAssignmentCreateRequest(StrictModel):
    reviewer_id: str = Field(min_length=1, max_length=256)
    note: str | None = Field(default=None, max_length=5000)


class ReviewAssignmentActionRequest(StrictModel):
    note: str | None = Field(default=None, max_length=5000)


class ReviewAssignmentSummary(StrictModel):
    id: str
    reviewer_id: str
    assigned_by: str
    status: ReviewAssignmentStatus
    created_at: str
    started_at: str | None = None
    completed_at: str | None = None
    cancelled_at: str | None = None
    assignment_note: str | None = None
    completion_note: str | None = None
    cancellation_reason: str | None = None


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
    review_status: IntegrityReviewStatus
    reviewed_by: str | None = None
    review_note: str | None = None


class RecruiterSessionReport(StrictModel):
    session_id: str
    job_id: str
    role: str
    candidate_ref: str
    status: str
    competencies: list[CompetencyReviewSummary]
    evidence_judge_runs: list[EvidenceJudgeRunSummary] = Field(default_factory=list)
    review_assignments: list[ReviewAssignmentSummary] = Field(default_factory=list)
    reasons: list[ReviewReason] = Field(default_factory=list)
    appeals: list[AppealReviewSummary] = Field(default_factory=list)
    integrity: list[IntegrityReviewSummary] = Field(default_factory=list)
    pending_appeals: int = Field(ge=0)
    integrity_signals: int = Field(ge=0)
    unresolved_tools: int = Field(ge=0)
    stale_evidence_runs: int = Field(default=0, ge=0)
    failed_evidence_runs: int = Field(default=0, ge=0)
    transcript_revisions: int = Field(ge=0)
    requires_human_review: bool
    note: str = (
        "This report summarizes interview evidence and review conditions. "
        "It does not make or recommend a final hiring decision."
    )


class ReviewDashboardSummary(StrictModel):
    total_sessions: int = Field(ge=0)
    review_required: int = Field(ge=0)
    pending_appeals: int = Field(ge=0)
    pending_integrity_signals: int = Field(ge=0)
    unresolved_tools: int = Field(ge=0)
    stale_evidence_runs: int = Field(default=0, ge=0)
    failed_evidence_runs: int = Field(default=0, ge=0)
    assigned_reviews: int = Field(default=0, ge=0)
    unassigned_review_required: int = Field(default=0, ge=0)
    completed_sessions: int = Field(ge=0)


class EvidenceReevaluationQueueItem(StrictModel):
    session_id: str
    job_id: str
    candidate_ref: str
    role: str
    answer_turn_id: str
    latest_run_id: str
    judge_id: str
    stale: bool
    failed: bool
    transcript_revision_count: int = Field(ge=0)
    current_transcript_revision_count: int = Field(ge=0)


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
    stale_evidence_runs: int = Field(default=0, ge=0)
    failed_evidence_runs: int = Field(default=0, ge=0)
    assigned_reviewer_id: str | None = None
    assignment_status: ReviewAssignmentStatus | None = None


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

    revisions_by_turn: dict[str, int] = {}
    for revision in session.transcript_revisions:
        revisions_by_turn[revision.turn_id] = (
            revisions_by_turn.get(revision.turn_id, 0) + 1
        )

    latest_run_by_answer = {}
    for run in session.evidence_judge_runs:
        current = latest_run_by_answer.get(run.answer_turn_id)
        if current is None or run.created_at > current.created_at:
            latest_run_by_answer[run.answer_turn_id] = run

    evidence_judge_runs = []
    for run in sorted(
        latest_run_by_answer.values(),
        key=lambda item: item.created_at,
        reverse=True,
    ):
        current_revisions = revisions_by_turn.get(
            run.answer_turn_id,
            0,
        )
        stale = run.transcript_revision_count != current_revisions
        evidence_judge_runs.append(
            EvidenceJudgeRunSummary(
                id=run.id,
                judge_id=run.judge_id,
                answer_turn_id=run.answer_turn_id,
                created_at=run.created_at.isoformat(),
                transcript_revision_count=run.transcript_revision_count,
                current_transcript_revision_count=current_revisions,
                observation_count=len(run.observation_ids),
                failed=run.error is not None,
                stale=stale,
                supersedes_run_id=run.supersedes_run_id,
            )
        )

        if run.error is not None:
            reasons.append(
                ReviewReason(
                    code="evidence_judge_failed",
                    severity="attention",
                    summary=(
                        f"Latest evidence judge run for answer "
                        f"{run.answer_turn_id!r} failed and requires review."
                    ),
                )
            )
        elif stale:
            reasons.append(
                ReviewReason(
                    code="evidence_reevaluation_needed",
                    severity="attention",
                    summary=(
                        f"Answer {run.answer_turn_id!r} changed after its latest "
                        "semantic evidence evaluation."
                    ),
                )
            )

    stale_evidence_runs = sum(
        item.stale
        for item in evidence_judge_runs
    )
    failed_evidence_runs = sum(
        item.failed
        for item in evidence_judge_runs
    )

    review_assignments = [
        ReviewAssignmentSummary(
            id=item.id,
            reviewer_id=item.reviewer_id,
            assigned_by=item.assigned_by,
            status=item.status,
            created_at=item.created_at.isoformat(),
            started_at=(
                item.started_at.isoformat()
                if item.started_at
                else None
            ),
            completed_at=(
                item.completed_at.isoformat()
                if item.completed_at
                else None
            ),
            cancelled_at=(
                item.cancelled_at.isoformat()
                if item.cancelled_at
                else None
            ),
            assignment_note=item.assignment_note,
            completion_note=item.completion_note,
            cancellation_reason=item.cancellation_reason,
        )
        for item in session.review_assignments
    ]

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
            review_status=item.review_status,
            reviewed_by=item.reviewed_by,
            review_note=item.review_note,
        )
        for item in session.integrity_signals
    ]
    integrity_signals = sum(
        item.review_status is IntegrityReviewStatus.PENDING
        for item in session.integrity_signals
    )
    if integrity_signals:
        reasons.append(
            ReviewReason(
                code="integrity_signal",
                severity="high",
                summary=(
                    f"{integrity_signals} pending integrity signal(s) require human review."
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
        evidence_judge_runs=evidence_judge_runs,
        review_assignments=review_assignments,
        reasons=reasons,
        appeals=appeals,
        integrity=integrity,
        pending_appeals=pending_appeals,
        integrity_signals=integrity_signals,
        unresolved_tools=unresolved_tools,
        stale_evidence_runs=stale_evidence_runs,
        failed_evidence_runs=failed_evidence_runs,
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
        stale_evidence_runs=report.stale_evidence_runs,
        failed_evidence_runs=report.failed_evidence_runs,
        assigned_reviewer_id=(
            next(
                (
                    item.reviewer_id
                    for item in reversed(report.review_assignments)
                    if item.status in {
                        ReviewAssignmentStatus.OPEN,
                        ReviewAssignmentStatus.IN_REVIEW,
                    }
                ),
                None,
            )
        ),
        assignment_status=(
            next(
                (
                    item.status
                    for item in reversed(report.review_assignments)
                    if item.status in {
                        ReviewAssignmentStatus.OPEN,
                        ReviewAssignmentStatus.IN_REVIEW,
                    }
                ),
                None,
            )
        ),
    )
