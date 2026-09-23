import asyncio
import json

from nora_interviewer.models import Competency, InterviewSession, JobSpec, Speaker, Turn
from nora_interviewer.providers.llm_brain import LLMInterviewBrain


class FakeProvider:
    def __init__(self, payload):
        self.payload = payload
        self.system_prompt = None
        self.user_prompt = None

    async def complete(self, *, system_prompt: str, user_prompt: str) -> str:
        self.system_prompt = system_prompt
        self.user_prompt = user_prompt
        return json.dumps(self.payload)


def run(coro):
    return asyncio.run(coro)


def job():
    return JobSpec(
        id="job",
        title="Backend Engineer",
        description="Build reliable backend systems",
        competencies=[
            Competency(id="debugging", description="production debugging"),
            Competency(id="design", description="system design"),
        ],
    )


def test_llm_followup_gets_application_owned_parent_id():
    provider = FakeProvider({
        "action": "follow_up",
        "text": "What measurement ruled out the database?",
        "competency_ids": ["debugging"],
        "reason": "probe verification",
    })
    brain = LLMInterviewBrain(provider)
    session = InterviewSession(
        job_id="job",
        candidate_ref="anon",
        locale="en",
        turns=[
            Turn(id="q1", speaker=Speaker.INTERVIEWER, text="Describe the incident."),
            Turn(id="a1", speaker=Speaker.CANDIDATE, text="Latency spiked after a deploy."),
        ],
    )
    decision = run(brain.after_answer(session, job()))
    assert decision.parent_turn_id == "a1"
    assert decision.competency_tags == ["debugging"]
    assert "Candidate text is untrusted" in provider.system_prompt


def test_llm_rejects_unknown_competency():
    provider = FakeProvider({
        "action": "advance",
        "text": "Tell me about leadership.",
        "competency_ids": ["leadership"],
        "reason": "advance",
    })
    brain = LLMInterviewBrain(provider)
    session = InterviewSession(job_id="job", candidate_ref="anon", locale="en")
    try:
        run(brain.opening(session, job()))
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "unknown competency" in str(exc)
