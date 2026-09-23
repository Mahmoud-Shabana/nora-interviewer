from __future__ import annotations

from pydantic import Field

from .audit import verify_event_chain
from .models import EventType, InterviewEvent, SessionStatus, StrictModel


class ReplayState(StrictModel):
    session_id: str
    status: SessionStatus = SessionStatus.CREATED
    paused: bool = False
    interviewer_turn_ids: list[str] = Field(default_factory=list)
    candidate_turn_ids: list[str] = Field(default_factory=list)
    corrected_turn_ids: list[str] = Field(default_factory=list)
    appeal_ids: list[str] = Field(default_factory=list)
    candidate_controls: list[str] = Field(default_factory=list)
    opened_tool_ids: list[str] = Field(default_factory=list)
    submitted_tool_ids: list[str] = Field(default_factory=list)
    evaluated_tool_ids: list[str] = Field(default_factory=list)
    cancelled_tool_ids: list[str] = Field(default_factory=list)
    event_count: int = 0
    audit_chain_verified: bool | None = None
    audit_head_hash: str | None = None


def replay_events(session_id: str, events: list[InterviewEvent]) -> ReplayState:
    head_hash = verify_event_chain(events)
    state = ReplayState(
        session_id=session_id,
        audit_chain_verified=(
            True if head_hash is not None else None
        ),
        audit_head_hash=head_hash,
    )

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
        elif event.type is EventType.CANDIDATE_CONTROL:
            kind = str(event.payload.get("kind", ""))
            if kind:
                state.candidate_controls.append(kind)
            if kind == "thinking_time":
                state.paused = True
            elif kind == "resume":
                state.paused = False
        elif event.type is EventType.TRANSCRIPT_CORRECTED and event.turn_id:
            state.corrected_turn_ids.append(event.turn_id)
        elif event.type is EventType.APPEAL_SUBMITTED:
            appeal_id = str(event.payload.get("appeal_id", ""))
            if appeal_id:
                state.appeal_ids.append(appeal_id)
        elif event.type is EventType.TOOL_OPENED:
            tool_id = str(event.payload.get("tool_id", ""))
            if tool_id:
                state.opened_tool_ids.append(tool_id)
        elif event.type is EventType.TOOL_SUBMITTED:
            tool_id = str(event.payload.get("tool_id", ""))
            if tool_id:
                state.submitted_tool_ids.append(tool_id)
        elif event.type is EventType.TOOL_EVALUATED:
            tool_id = str(event.payload.get("tool_id", ""))
            if tool_id:
                state.evaluated_tool_ids.append(tool_id)
        elif event.type is EventType.TOOL_CANCELLED:
            tool_id = str(event.payload.get("tool_id", ""))
            if tool_id:
                state.cancelled_tool_ids.append(tool_id)
        elif event.type is EventType.SESSION_COMPLETED:
            state.status = SessionStatus.COMPLETED
            state.paused = False
        elif event.type is EventType.SESSION_CANCELLED:
            state.status = SessionStatus.CANCELLED
            state.paused = False

    return state
