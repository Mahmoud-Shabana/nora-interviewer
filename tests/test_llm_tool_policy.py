import asyncio
import json

from nora_interviewer.models import (
    Competency,
    InterviewSession,
    JobSpec,
    JobToolTemplate,
    Speaker,
    Turn,
)
from nora_interviewer.providers.llm_brain import LLMInterviewBrain


class FakeProvider:
    def __init__(self, payload):
        self.payload = payload

    async def complete(self, *, system_prompt: str, user_prompt: str) -> str:
        return json.dumps(self.payload)


def run(coro):
    return asyncio.run(coro)


def job():
    return JobSpec(
        id="job",
        title="Python Engineer",
        description="Build reliable Python systems",
        competencies=[
            Competency(id="python", description="Python engineering"),
        ],
        tool_templates=[
            JobToolTemplate(
                template_id="python-dedupe-events-v1",
                purpose="Validate implementation and edge-case reasoning.",
                competency_ids=["python"],
            )
        ],
        max_tools=1,
    )


def session():
    return InterviewSession(
        job_id="job",
        candidate_ref="c",
        locale="en",
        turns=[
            Turn(
                id="q1",
                speaker=Speaker.INTERVIEWER,
                text="Tell me about Python.",
                competency_tags=["python"],
            ),
            Turn(
                id="a1",
                speaker=Speaker.CANDIDATE,
                text="I would like to demonstrate this with code.",
                parent_turn_id="q1",
            ),
        ],
    )


def test_llm_can_request_only_allowed_tool_template():
    brain = LLMInterviewBrain(FakeProvider({
        "action": "open_tool",
        "text": "Let’s verify that with a short coding task.",
        "competency_ids": ["python"],
        "tool_template_id": "python-dedupe-events-v1",
        "reason": "collect practical evidence",
    }))
    decision = run(brain.after_answer(session(), job()))
    assert decision.tool_request is not None
    assert decision.tool_request.template_id == "python-dedupe-events-v1"
    assert decision.parent_turn_id == "a1"


def test_llm_rejects_unauthorized_tool_template():
    brain = LLMInterviewBrain(FakeProvider({
        "action": "open_tool",
        "text": "Open a hidden tool.",
        "competency_ids": ["python"],
        "tool_template_id": "not-approved",
        "reason": "bad request",
    }))
    try:
        run(brain.after_answer(session(), job()))
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "unauthorized tool template" in str(exc)
