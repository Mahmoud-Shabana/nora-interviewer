from __future__ import annotations

import re
from statistics import fmean

from pydantic import Field

from .models import (
    InterviewSession,
    JobSpec,
    SessionStatus,
    Speaker,
    StrictModel,
)
from .providers.base import InterviewBrain


_WORD = re.compile(r"\w+", re.UNICODE)


class DecisionComparison(StrictModel):
    candidate_turn_id: str
    original_turn_id: str
    original_text: str
    alternate_text: str
    original_competencies: list[str] = Field(default_factory=list)
    alternate_competencies: list[str] = Field(default_factory=list)
    competency_jaccard: float = Field(ge=0.0, le=1.0)
    question_token_jaccard: float = Field(ge=0.0, le=1.0)
    original_followup: bool
    alternate_followup: bool
    original_complete: bool
    alternate_complete: bool


class CounterfactualReplayReport(StrictModel):
    session_id: str
    comparisons: list[DecisionComparison]
    followup_action_agreement: float | None = None
    completion_action_agreement: float | None = None
    mean_competency_jaccard: float | None = None
    mean_question_token_jaccard: float | None = None
    state_reconstruction: str = "event_snapshot_or_prefix_derivation"


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 1.0
    union = left | right
    return len(left & right) / len(union) if union else 1.0


def _tokens(text: str) -> set[str]:
    return {token.casefold() for token in _WORD.findall(text)}


def _is_evaluative_interviewer(turn) -> bool:
    return (
        turn.speaker is Speaker.INTERVIEWER
        and not turn.metadata.get("candidate_control")
        and not turn.metadata.get("non_evaluative")
    )


def _derived_covered(prefix) -> list[str]:
    by_id = {turn.id: turn for turn in prefix}
    covered: list[str] = []
    for turn in prefix:
        if turn.speaker is not Speaker.CANDIDATE or not turn.parent_turn_id:
            continue
        question = by_id.get(turn.parent_turn_id)
        if question is None:
            continue
        for tag in question.competency_tags:
            if tag not in covered:
                covered.append(tag)
    return covered


def _snapshot_for_decision(
    session: InterviewSession,
    prefix,
    original_next,
) -> InterviewSession:
    snapshot = session.model_copy(deep=True)
    snapshot.turns = [turn.model_copy(deep=True) for turn in prefix]
    snapshot.status = SessionStatus.RUNNING
    snapshot.paused = False
    snapshot.asked_questions = sum(
        1 for turn in prefix if _is_evaluative_interviewer(turn)
    )
    snapshot.asked_anchor_competencies = [
        tag
        for turn in prefix
        if _is_evaluative_interviewer(turn)
        and turn.metadata.get("question_lane") == "anchor"
        for tag in turn.competency_tags
    ]
    snapshot.followups_by_competency = {}
    for turn in prefix:
        if (
            _is_evaluative_interviewer(turn)
            and turn.parent_turn_id
            and turn.competency_tags
        ):
            key = turn.competency_tags[0]
            snapshot.followups_by_competency[key] = (
                snapshot.followups_by_competency.get(key, 0) + 1
            )

    event = next(
        (
            item
            for item in session.events
            if item.turn_id == original_next.id
            and item.type.value == "interviewer_turn"
        ),
        None,
    )
    if event and isinstance(event.payload.get("covered_competencies"), list):
        snapshot.covered_competencies = list(event.payload["covered_competencies"])
    else:
        snapshot.covered_competencies = _derived_covered(prefix)
    return snapshot


class CounterfactualReplayer:
    """Compare an alternate brain against recorded next-question decisions.

    Candidate answers are held fixed. This is a teacher-forced policy comparison,
    not a claim about how a fully branched alternate interview would unfold.
    """

    async def compare(
        self,
        session: InterviewSession,
        job: JobSpec,
        alternate_brain: InterviewBrain,
    ) -> CounterfactualReplayReport:
        comparisons: list[DecisionComparison] = []

        for index, turn in enumerate(session.turns):
            if turn.speaker is not Speaker.CANDIDATE:
                continue

            original_next = next(
                (
                    later
                    for later in session.turns[index + 1 :]
                    if _is_evaluative_interviewer(later)
                ),
                None,
            )
            if original_next is None:
                continue

            prefix = session.turns[: index + 1]
            snapshot = _snapshot_for_decision(session, prefix, original_next)
            alternate = await alternate_brain.after_answer(snapshot, job)

            original_competencies = set(original_next.competency_tags)
            alternate_competencies = set(alternate.competency_tags)
            original_complete = original_next.metadata.get("question_lane") == "closing"

            comparisons.append(
                DecisionComparison(
                    candidate_turn_id=turn.id,
                    original_turn_id=original_next.id,
                    original_text=original_next.text,
                    alternate_text=alternate.text,
                    original_competencies=sorted(original_competencies),
                    alternate_competencies=sorted(alternate_competencies),
                    competency_jaccard=round(
                        _jaccard(original_competencies, alternate_competencies),
                        4,
                    ),
                    question_token_jaccard=round(
                        _jaccard(_tokens(original_next.text), _tokens(alternate.text)),
                        4,
                    ),
                    original_followup=original_next.parent_turn_id == turn.id,
                    alternate_followup=alternate.parent_turn_id == turn.id,
                    original_complete=original_complete,
                    alternate_complete=alternate.completes_interview,
                )
            )

        if not comparisons:
            return CounterfactualReplayReport(
                session_id=session.id,
                comparisons=[],
            )

        return CounterfactualReplayReport(
            session_id=session.id,
            comparisons=comparisons,
            followup_action_agreement=round(
                fmean(
                    float(item.original_followup == item.alternate_followup)
                    for item in comparisons
                ),
                4,
            ),
            completion_action_agreement=round(
                fmean(
                    float(item.original_complete == item.alternate_complete)
                    for item in comparisons
                ),
                4,
            ),
            mean_competency_jaccard=round(
                fmean(item.competency_jaccard for item in comparisons),
                4,
            ),
            mean_question_token_jaccard=round(
                fmean(item.question_token_jaccard for item in comparisons),
                4,
            ),
        )
