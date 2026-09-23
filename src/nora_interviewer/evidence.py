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
            judge_run_id=observation.judge_run_id,
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



    @staticmethod
    def recompute_node(
        session: InterviewSession,
        competency_id: str,
    ) -> CompetencyEvidence:
        node = session.evidence_graph.setdefault(
            competency_id,
            CompetencyEvidence(competency_id=competency_id),
        )
        active = [item for item in node.evidence if item.active]

        if not active:
            node.state = EvidenceState.UNKNOWN
            node.confidence = None
            return node

        strongest_rank = max(_STATE_RANK[item.state] for item in active)
        strongest = [
            item for item in active
            if _STATE_RANK[item.state] == strongest_rank
        ]
        node.state = strongest[0].state

        confidences = [
            item.confidence
            for item in strongest
            if item.state not in {
                EvidenceState.CLAIMED,
                EvidenceState.UNKNOWN,
            }
        ]
        node.confidence = (
            max(confidences)
            if confidences
            else None
        )
        return node

    @staticmethod
    def supersede_semantic_evidence_for_turn(
        session: InterviewSession,
        *,
        turn_id: str,
    ) -> list[EvidenceItem]:
        superseded: list[EvidenceItem] = []
        affected: set[str] = set()

        for competency_id, node in session.evidence_graph.items():
            for item in node.evidence:
                if (
                    item.active
                    and item.turn_id == turn_id
                    and item.source.startswith("semantic_judge:")
                ):
                    item.active = False
                    superseded.append(item)
                    affected.add(competency_id)

        for competency_id in affected:
            EvidenceGraph.recompute_node(
                session,
                competency_id,
            )

        return superseded
