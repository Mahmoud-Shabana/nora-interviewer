from __future__ import annotations

from pydantic import Field

from .models import EvidenceState, InterviewSession, JobSpec, StrictModel


class FeedbackItem(StrictModel):
    competency_id: str
    competency: str
    status: str
    summary: str
    evidence_turn_ids: list[str] = Field(default_factory=list)


class CandidateFeedbackReport(StrictModel):
    session_id: str
    role: str
    supported_evidence: list[FeedbackItem] = Field(default_factory=list)
    needs_more_evidence: list[FeedbackItem] = Field(default_factory=list)
    conflicting_evidence: list[FeedbackItem] = Field(default_factory=list)
    note: str = (
        "This report summarizes job-related evidence observed in the interview. "
        "It is not a final hiring decision or a personality assessment."
    )


def build_candidate_feedback(
    session: InterviewSession,
    job: JobSpec,
) -> CandidateFeedbackReport:
    report = CandidateFeedbackReport(session_id=session.id, role=job.title)

    for competency in job.competencies:
        node = session.evidence_graph.get(competency.id)
        state = node.state if node else EvidenceState.UNKNOWN
        turn_ids = []
        if node:
            turn_ids = list(dict.fromkeys(item.turn_id for item in node.evidence))

        if state in {EvidenceState.DEMONSTRATED, EvidenceState.VERIFIED}:
            item = FeedbackItem(
                competency_id=competency.id,
                competency=competency.description,
                status=state.value,
                summary=(
                    f"The interview contains {state.value} job-related evidence "
                    f"for {competency.description}."
                ),
                evidence_turn_ids=turn_ids,
            )
            report.supported_evidence.append(item)
        elif state is EvidenceState.CONTRADICTED:
            item = FeedbackItem(
                competency_id=competency.id,
                competency=competency.description,
                status=state.value,
                summary=(
                    f"The interview contains conflicting evidence for "
                    f"{competency.description}; human review is recommended."
                ),
                evidence_turn_ids=turn_ids,
            )
            report.conflicting_evidence.append(item)
        else:
            label = (
                "insufficient evidence"
                if state in {
                    EvidenceState.UNKNOWN,
                    EvidenceState.CLAIMED,
                    EvidenceState.INSUFFICIENT,
                }
                else state.value
            )
            item = FeedbackItem(
                competency_id=competency.id,
                competency=competency.description,
                status=state.value,
                summary=(
                    f"There is {label} to make a strong evidence-based statement "
                    f"about {competency.description}."
                ),
                evidence_turn_ids=turn_ids,
            )
            report.needs_more_evidence.append(item)

    return report
