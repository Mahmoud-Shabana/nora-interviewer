from __future__ import annotations

from .models import EventType, InterviewEvent, InterviewSession, Turn


def append_event(
    session: InterviewSession,
    event_type: EventType,
    *,
    turn: Turn | None = None,
    payload: dict | None = None,
) -> InterviewEvent:
    event = InterviewEvent(
        seq=len(session.events) + 1,
        type=event_type,
        turn_id=turn.id if turn else None,
        payload=payload or {},
    )
    session.events.append(event)
    return event
