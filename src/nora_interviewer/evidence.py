from __future__ import annotations

from .models import (
    CompetencyEvidence,
    EvidenceItem,
    EvidenceObservation,
    EvidenceState,
    InterviewSession,
    JobSpec,
    Speaker,
)


_STATE_RANK = {
    EvidenceState.UNKNOWN: 0,
    EvidenceState.INSUFFICIENT: 1,
    EvidenceState.CLAIMED: 2,
    EvidenceState.DEMONSTRATED: 3,
    EvidenceState.VERIFIED: 4,
    EvidenceState.CONTRADICTED: 5,
}


class EvidenceGraph:
    """Maintain provenance-first competency evidence without inventing scores."""

    @staticmethod
    def initialize(session: InterviewSession, job: JobSpec) -> None:
        for competency in job.competencies:
            session.evidence_graph.setdefault(
                competency.id,
                CompetencyEvidence(competency_id=competency.id),
            )

    @staticmethod
    def record_candidate_claim(
        session: InterviewSession,
        *,
        question_turn_id: str,
        answer_turn_id: str,
        competency_ids: list[str],
    ) -> list[EvidenceItem]:
        by_id = {turn.id: turn for turn in session.turns}
        question = by_id.get(question_turn_id)
        answer = by_id.get(answer_turn_id)
        if question is None or answer is None:
            raise ValueError("question and answer turns must exist")
        if question.speaker is not Speaker.INTERVIEWER or answer.speaker is not Speaker.CANDIDATE:
            raise ValueError("claim evidence requires interviewer question and candidate answer")

        created: list[EvidenceItem] = []
        for competency_id in competency_ids:
            node = session.evidence_graph.get(competency_id)
            if node is None:
                node = CompetencyEvidence(competency_id=competency_id)
                session.evidence_graph[competency_id] = node
            item = EvidenceItem(
                turn_id=answer_turn_id,
                state=EvidenceState.CLAIMED,
                confidence=1.0,
                note=f"Candidate supplied an answer to interviewer turn {question_turn_id}.",
                source="candidate_response",
            )
            node.evidence.append(item)
            if _STATE_RANK[node.state] < _STATE_RANK[EvidenceState.CLAIMED]:
                node.state = EvidenceState.CLAIMED
                node.confidence = None
            created.append(item)
        return created

    @staticmethod
    def apply_observation(
        session: InterviewSession,
        job: JobSpec,
        observation: EvidenceObservation,
    ) -> EvidenceItem:
        known = {c.id for c in job.competencies}
        if observation.competency_id not in known:
            raise ValueError("unknown competency")
        turn = next((t for t in session.turns if t.id == observation.turn_id), None)
        if turn is None:
            raise ValueError("evidence observation references unknown turn")

        if observation.quote is not None and observation.quote not in turn.text:
            raise ValueError(
                "evidence quote must be a literal substring of the referenced turn"
            )
        if (
            observation.source.startswith("semantic_judge:")
            and observation.state is EvidenceState.VERIFIED
        ):
            raise ValueError(
                "semantic transcript judges may not emit verified evidence"
            )

        node = session.evidence_graph.setdefault(
            observation.competency_id,
            CompetencyEvidence(competency_id=observation.competency_id),
        )
        item = EvidenceItem(
            turn_id=observation.turn_id,
            state=observation.state,
            confidence=observation.confidence,
            quote=observation.quote,
            note=observation.note,
            source=observation.source,
        )
        node.evidence.append(item)

        # Contradiction is never silently overwritten by a later positive observation.
        if node.state is EvidenceState.CONTRADICTED:
            return item
        if observation.state is EvidenceState.CONTRADICTED:
            node.state = EvidenceState.CONTRADICTED
            node.confidence = observation.confidence
            return item

        if _STATE_RANK[observation.state] >= _STATE_RANK[node.state]:
            node.state = observation.state
            node.confidence = observation.confidence
        return item
