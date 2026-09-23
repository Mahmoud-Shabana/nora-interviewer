import asyncio

from nora_interviewer.coding import (
    CodingChallengeManager,
    CodingChallengeRequest,
    CodingInterviewTool,
)
from nora_interviewer.models import InterviewSession, JobSpec, ToolSubmission
from nora_interviewer.sandbox import DisabledSandboxRunner, SandboxResult


class FakePassingRunner:
    async def run_python(self, *, source, harness, limits):
        assert "secret_case" in harness
        return SandboxResult(
            exit_code=0,
            stdout='__NORA_TEST_RESULT__{"failures":[],"passed":2,"total":2}\n',
            duration_ms=18,
        )


def run(coro):
    return asyncio.run(coro)


def challenge():
    return CodingChallengeRequest(
        title="Implement add",
        instructions="Implement add(a, b).",
        competency_tags=["python"],
        starter_code="def add(a, b):\n    pass\n",
        public_tests=["assert add(1, 2) == 3"],
        hidden_tests=["assert add(20, 22) == 42  # secret_case"],
    )


def test_hidden_tests_are_not_exposed_in_public_invocation():
    manager = CodingChallengeManager()
    invocation = manager.create(challenge())
    serialized = invocation.model_dump_json()
    assert "secret_case" not in serialized
    assert invocation.payload["hidden_test_count"] == 1
    assert invocation.payload["public_tests"] == ["assert add(1, 2) == 3"]


def test_coding_tool_scores_runner_results():
    manager = CodingChallengeManager()
    invocation = manager.create(challenge())
    tool = CodingInterviewTool(manager, FakePassingRunner())
    session = InterviewSession(job_id="job", candidate_ref="c", locale="en")
    from nora_interviewer.models import Competency
    job = JobSpec(
        id="job",
        title="Engineer",
        description="Build systems",
        competencies=[Competency(id="python", description="Python engineering")],
    )
    submission = ToolSubmission(
        tool_id=invocation.id,
        content={"code": "def add(a, b):\n    return a + b\n"},
    )
    result = run(tool.evaluate(invocation, submission, session, job))
    assert result.passed is True
    assert result.score == 1.0
    assert result.evidence["passed_tests"] == 2


def test_disabled_sandbox_never_invents_a_code_score():
    manager = CodingChallengeManager()
    invocation = manager.create(challenge())
    tool = CodingInterviewTool(manager, DisabledSandboxRunner())
    session = InterviewSession(job_id="job", candidate_ref="c", locale="en")
    from nora_interviewer.models import Competency
    job = JobSpec(
        id="job",
        title="Engineer",
        description="Build systems",
        competencies=[Competency(id="python", description="Python engineering")],
    )
    submission = ToolSubmission(
        tool_id=invocation.id,
        content={"code": "def add(a, b):\n    return a + b\n"},
    )
    result = run(tool.evaluate(invocation, submission, session, job))
    assert result.passed is None
    assert result.score is None
    assert result.evidence["review_required"] is True
