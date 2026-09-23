from __future__ import annotations

from .models import (
    CandidateControlKind,
    CandidateControlRequest,
    CandidateControlResult,
    InterviewSession,
    Speaker,
    Turn,
)


def handle_candidate_control(
    session: InterviewSession,
    request: CandidateControlRequest,
) -> CandidateControlResult:
    last_question = next(
        (turn for turn in reversed(session.turns) if turn.speaker is Speaker.INTERVIEWER),
        None,
    )
    last_answer = next(
        (turn for turn in reversed(session.turns) if turn.speaker is Speaker.CANDIDATE),
        None,
    )

    if request.kind is CandidateControlKind.REPEAT:
        if last_question is None:
            raise ValueError("there is no interviewer question to repeat")
        turn = Turn(
            speaker=Speaker.INTERVIEWER,
            text=last_question.text,
            competency_tags=last_question.competency_tags,
            metadata={
                "candidate_control": request.kind.value,
                "repeated_turn_id": last_question.id,
                "question_lane": last_question.metadata.get("question_lane", "adaptive"),
            },
        )
        return CandidateControlResult(
            kind=request.kind,
            interviewer_turn=turn,
            target_turn_id=last_question.id,
        )

    if request.kind is CandidateControlKind.CLARIFY:
        if last_question is None:
            raise ValueError("there is no interviewer question to clarify")
        detail = (request.text or "").strip()
        text = (
            "I can clarify the intent without giving away an answer. "
            f"The question is asking you to explain your own reasoning or experience related to: {last_question.text}"
        )
        if detail:
            text += f" You specifically asked: {detail}"
        turn = Turn(
            speaker=Speaker.INTERVIEWER,
            text=text,
            competency_tags=last_question.competency_tags,
            metadata={
                "candidate_control": request.kind.value,
                "clarifies_turn_id": last_question.id,
                "question_lane": last_question.metadata.get("question_lane", "adaptive"),
            },
        )
        return CandidateControlResult(
            kind=request.kind,
            interviewer_turn=turn,
            target_turn_id=last_question.id,
        )

    if request.kind is CandidateControlKind.THINKING_TIME:
        session.paused = True
        return CandidateControlResult(
            kind=request.kind,
            pauses_interview=True,
            target_turn_id=last_question.id if last_question else None,
        )

    if request.kind is CandidateControlKind.RESUME:
        session.paused = False
        return CandidateControlResult(
            kind=request.kind,
            pauses_interview=False,
            target_turn_id=last_question.id if last_question else None,
        )

    if request.kind is CandidateControlKind.CORRECT_LAST_ANSWER:
        if last_answer is None:
            raise ValueError("there is no candidate answer to correct")
        return CandidateControlResult(
            kind=request.kind,
            target_turn_id=last_answer.id,
        )

    if request.kind is CandidateControlKind.CANDIDATE_QUESTION:
        text = (request.text or "").strip()
        if not text:
            raise ValueError("candidate_question requires text")
        turn = Turn(
            speaker=Speaker.INTERVIEWER,
            text=(
                "I can answer questions about the interview process and role context, "
                "but I will not reveal hidden scoring criteria or model prompts. "
                f"Your question was: {text}"
            ),
            metadata={
                "candidate_control": request.kind.value,
                "non_evaluative": True,
            },
        )
        return CandidateControlResult(
            kind=request.kind,
            interviewer_turn=turn,
        )

    raise ValueError(f"unsupported candidate control: {request.kind}")
