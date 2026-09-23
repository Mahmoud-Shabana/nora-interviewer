from __future__ import annotations

from pydantic import Field

from .models import EventType, InterviewEvent, SessionStatus, StrictModel


class ReplayState(StrictModel):
    session_id: str
    status: SessionStatus = SessionStatus.CREATED
    interviewer_turn_ids: list[str] = Field(default_factory=list)
    candidate_turn_ids: list[str] = Field(default_factory=list)
    corrected_turn_ids: list[str] = Field(default_factory=list)
    appeal_ids: list[str] = Field(default_factory=list)
    event_count: int = 0


def replay_events(session_id: str, events: list[InterviewEvent]) -> ReplayState:
    state = ReplayState(session_id=session_id)

    expected_seq = 1
    for event in events:
        if event.seq != expected_seq:
            raise ValueError(
                f"non-contiguous event sequence: expected {expected_seq}, got {event.seq}"
            )
        expected_seq += 1
        state.event_count += 1

        if event.type is EventType.SESSION_CREATED:
            state.status = SessionStatus.CREATED
        elif event.type is EventType.INTERVIEW_STARTED:
            state.status = SessionStatus.RUNNING
        elif event.type is EventType.INTERVIEWER_TURN and event.turn_id:
            state.interviewer_turn_ids.append(event.turn_id)
        elif event.type is EventType.CANDIDATE_TURN and event.turn_id:
            state.candidate_turn_ids.append(event.turn_id)
        elif event.type is EventType.TRANSCRIPT_CORRECTED and event.turn_id:
            state.corrected_turn_ids.append(event.turn_id)
        elif event.type is EventType.APPEAL_SUBMITTED:
            appeal_id = str(event.payload.get("appeal_id", ""))
            if appeal_id:
                state.appeal_ids.append(appeal_id)
        elif event.type is EventType.SESSION_COMPLETED:
            state.status = SessionStatus.COMPLETED

    return state
