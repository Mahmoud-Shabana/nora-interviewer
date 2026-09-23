from nora_interviewer.audit import append_event
from nora_interviewer.models import EventType, InterviewSession, Speaker, Turn
from nora_interviewer.replay import replay_events


def test_replay_reconstructs_session_lifecycle():
    session = InterviewSession(job_id="job", candidate_ref="c", locale="en")
    append_event(session, EventType.SESSION_CREATED)
    append_event(session, EventType.INTERVIEW_STARTED)
    q = Turn(id="q", speaker=Speaker.INTERVIEWER, text="Question")
    a = Turn(id="a", speaker=Speaker.CANDIDATE, text="Answer")
    append_event(session, EventType.INTERVIEWER_TURN, turn=q)
    append_event(session, EventType.CANDIDATE_TURN, turn=a)
    append_event(session, EventType.TRANSCRIPT_CORRECTED, turn=a)
    append_event(session, EventType.APPEAL_SUBMITTED, payload={"appeal_id": "appeal-1"})
    append_event(session, EventType.SESSION_COMPLETED)

    state = replay_events(session.id, session.events)
    assert state.status.value == "completed"
    assert state.interviewer_turn_ids == ["q"]
    assert state.candidate_turn_ids == ["a"]
    assert state.corrected_turn_ids == ["a"]
    assert state.appeal_ids == ["appeal-1"]
    assert state.event_count == 7
