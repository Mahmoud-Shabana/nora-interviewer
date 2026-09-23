from nora_interviewer.audit import append_event
from nora_interviewer.models import EventType, InterviewSession
from nora_interviewer.replay import replay_events


def test_replay_reconstructs_pause_and_tool_lifecycle():
    session = InterviewSession(job_id="job", candidate_ref="c", locale="en")
    append_event(session, EventType.SESSION_CREATED)
    append_event(session, EventType.INTERVIEW_STARTED)
    append_event(
        session,
        EventType.CANDIDATE_CONTROL,
        payload={"kind": "thinking_time"},
    )
    append_event(
        session,
        EventType.CANDIDATE_CONTROL,
        payload={"kind": "resume"},
    )
    append_event(
        session,
        EventType.TOOL_OPENED,
        payload={"tool_id": "tool-1"},
    )
    append_event(
        session,
        EventType.TOOL_SUBMITTED,
        payload={"tool_id": "tool-1", "submission_id": "sub-1"},
    )
    append_event(
        session,
        EventType.TOOL_EVALUATED,
        payload={"tool_id": "tool-1", "submission_id": "sub-1"},
    )

    state = replay_events(session.id, session.events)
    assert state.paused is False
    assert state.candidate_controls == ["thinking_time", "resume"]
    assert state.opened_tool_ids == ["tool-1"]
    assert state.submitted_tool_ids == ["tool-1"]
    assert state.evaluated_tool_ids == ["tool-1"]
