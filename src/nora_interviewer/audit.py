from __future__ import annotations

import hashlib
import json

from pydantic_core import to_jsonable_python

from .models import EventType, InterviewEvent, InterviewSession, Turn


HASH_VERSION = 1


class AuditChainError(ValueError):
    pass


def _hash_material(
    event: InterviewEvent,
    *,
    prev_hash: str | None,
) -> bytes:
    payload = {
        "hash_version": HASH_VERSION,
        "seq": event.seq,
        "type": event.type.value,
        "turn_id": event.turn_id,
        "payload": to_jsonable_python(event.payload),
        "created_at": event.created_at.isoformat(),
        "prev_hash": prev_hash,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return encoded.encode("utf-8")


def compute_event_hash(
    event: InterviewEvent,
    *,
    prev_hash: str | None,
) -> str:
    return hashlib.sha256(
        _hash_material(
            event,
            prev_hash=prev_hash,
        )
    ).hexdigest()


def verify_event_chain(
    events: list[InterviewEvent],
) -> str | None:
    """Verify a sealed event chain and return its head hash.

    A fully legacy, unhashed list returns None. Mixed legacy/hashed histories
    are rejected because they do not provide an end-to-end integrity claim.
    """

    if not events:
        return None

    hashed_flags = [
        any(
            value is not None
            for value in (
                event.hash_version,
                event.prev_hash,
                event.event_hash,
            )
        )
        for event in events
    ]

    if not any(hashed_flags):
        return None
    if not all(hashed_flags):
        raise AuditChainError(
            "mixed legacy and hashed audit events are not a valid sealed chain"
        )

    expected_prev: str | None = None
    for event in events:
        if event.hash_version != HASH_VERSION:
            raise AuditChainError(
                f"unsupported audit hash version at seq {event.seq}: "
                f"{event.hash_version!r}"
            )
        if event.prev_hash != expected_prev:
            raise AuditChainError(
                f"audit previous-hash mismatch at seq {event.seq}"
            )
        expected = compute_event_hash(
            event,
            prev_hash=expected_prev,
        )
        if event.event_hash != expected:
            raise AuditChainError(
                f"audit event hash mismatch at seq {event.seq}"
            )
        expected_prev = event.event_hash

    return expected_prev


def seal_event_chain(
    events: list[InterviewEvent],
) -> str | None:
    """Seal a legacy history once, or verify an already sealed history."""

    if not events:
        return None

    hashed_flags = [
        any(
            value is not None
            for value in (
                event.hash_version,
                event.prev_hash,
                event.event_hash,
            )
        )
        for event in events
    ]

    if any(hashed_flags):
        return verify_event_chain(events)

    prev_hash: str | None = None
    for event in events:
        event.hash_version = HASH_VERSION
        event.prev_hash = prev_hash
        event.event_hash = compute_event_hash(
            event,
            prev_hash=prev_hash,
        )
        prev_hash = event.event_hash

    return prev_hash


def append_event(
    session: InterviewSession,
    event_type: EventType,
    *,
    turn: Turn | None = None,
    payload: dict | None = None,
) -> InterviewEvent:
    prev_hash = seal_event_chain(
        session.events
    )

    event = InterviewEvent(
        seq=len(session.events) + 1,
        type=event_type,
        turn_id=turn.id if turn else None,
        payload=payload or {},
        hash_version=HASH_VERSION,
        prev_hash=prev_hash,
    )
    event.event_hash = compute_event_hash(
        event,
        prev_hash=prev_hash,
    )
    session.events.append(event)
    return event
