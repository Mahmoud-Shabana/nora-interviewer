from nora_interviewer.audit import (
    AuditChainError,
    append_event,
    verify_event_chain,
)
from nora_interviewer.models import (
    EventType,
    InterviewEvent,
    InterviewSession,
)
from nora_interviewer.replay import replay_events


def test_appended_events_form_verified_hash_chain():
    session = InterviewSession(
        job_id="job",
        candidate_ref="candidate",
        locale="en",
    )

    first = append_event(
        session,
        EventType.SESSION_CREATED,
        payload={"job_id": "job"},
    )
    second = append_event(
        session,
        EventType.INTERVIEW_STARTED,
    )

    assert first.prev_hash is None
    assert first.event_hash is not None
    assert second.prev_hash == first.event_hash
    assert second.event_hash is not None

    head = verify_event_chain(session.events)
    assert head == second.event_hash

    replay = replay_events(
        session.id,
        session.events,
    )
    assert replay.audit_chain_verified is True
    assert replay.audit_head_hash == second.event_hash


def test_tampered_payload_breaks_audit_chain():
    session = InterviewSession(
        job_id="job",
        candidate_ref="candidate",
        locale="en",
    )
    append_event(
        session,
        EventType.SESSION_CREATED,
        payload={"job_id": "job"},
    )
    append_event(
        session,
        EventType.INTERVIEW_STARTED,
    )

    session.events[0].payload["job_id"] = "tampered"

    try:
        replay_events(
            session.id,
            session.events,
        )
        assert False, "expected AuditChainError"
    except AuditChainError as exc:
        assert "hash mismatch" in str(exc)


def test_legacy_history_is_sealed_before_new_event():
    session = InterviewSession(
        job_id="job",
        candidate_ref="candidate",
        locale="en",
        events=[
            InterviewEvent(
                seq=1,
                type=EventType.SESSION_CREATED,
                payload={"job_id": "job"},
            )
        ],
    )
    assert session.events[0].event_hash is None

    append_event(
        session,
        EventType.INTERVIEW_STARTED,
    )

    assert session.events[0].event_hash is not None
    assert session.events[1].prev_hash == session.events[0].event_hash
    assert verify_event_chain(session.events) == session.events[1].event_hash
