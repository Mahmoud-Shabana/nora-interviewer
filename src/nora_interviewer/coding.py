from __future__ import annotations

import json
from uuid import uuid4

from pydantic import Field

from .models import (
    InterviewSession,
    JobSpec,
    StrictModel,
    ToolEvaluation,
    ToolInvocation,
    ToolKind,
    ToolSubmission,
)
from .sandbox import (
    SandboxLimits,
    SandboxRunner,
    SandboxUnavailable,
)


_RESULT_PREFIX = "__NORA_TEST_RESULT__"


class CodingChallengeRequest(StrictModel):
    title: str = Field(min_length=2, max_length=200)
    instructions: str = Field(min_length=2, max_length=20_000)
    competency_tags: list[str] = Field(default_factory=list)
    starter_code: str = ""
    public_tests: list[str] = Field(default_factory=list)
    hidden_tests: list[str] = Field(default_factory=list)
    opened_from_turn_id: str | None = None
    timeout_seconds: float = Field(default=5.0, gt=0, le=30)


class _PrivateChallenge(StrictModel):
    id: str
    hidden_tests: list[str]
    public_tests: list[str]
    timeout_seconds: float


class CodingChallengeManager:
    def __init__(self) -> None:
        self._private: dict[str, _PrivateChallenge] = {}

    def create(self, request: CodingChallengeRequest) -> ToolInvocation:
        challenge_id = str(uuid4())
        invocation = ToolInvocation(
            kind=ToolKind.CODING,
            title=request.title,
            instructions=request.instructions,
            competency_tags=request.competency_tags,
            opened_from_turn_id=request.opened_from_turn_id,
            payload={
                "challenge_id": challenge_id,
                "language": "python",
                "starter_code": request.starter_code,
                "public_tests": request.public_tests,
                "hidden_test_count": len(request.hidden_tests),
            },
        )
        self._private[invocation.id] = _PrivateChallenge(
            id=challenge_id,
            hidden_tests=request.hidden_tests,
            public_tests=request.public_tests,
            timeout_seconds=request.timeout_seconds,
        )
        return invocation

    def get(self, tool_id: str) -> _PrivateChallenge:
        try:
            return self._private[tool_id]
        except KeyError as exc:
            raise ValueError("coding challenge private state is unavailable") from exc


def _build_harness(tests: list[str]) -> str:
    encoded = json.dumps(tests)
    return f"""import json
from solution import *

tests = {encoded}
passed = 0
failures = []
for index, test in enumerate(tests):
    try:
        exec(test, globals(), globals())
        passed += 1
    except Exception as exc:
        failures.append({{"index": index, "error": f"{{type(exc).__name__}}: {{exc}}"}})

result = {{"passed": passed, "total": len(tests), "failures": failures}}
print("{_RESULT_PREFIX}" + json.dumps(result, sort_keys=True))
raise SystemExit(0 if not failures else 1)
"""


def _parse_result(stdout: str) -> dict | None:
    for line in reversed(stdout.splitlines()):
        if line.startswith(_RESULT_PREFIX):
            try:
                return json.loads(line[len(_RESULT_PREFIX):])
            except json.JSONDecodeError:
                return None
    return None


class CodingInterviewTool:
    kind = ToolKind.CODING

    def __init__(
        self,
        challenges: CodingChallengeManager,
        runner: SandboxRunner,
    ) -> None:
        self.challenges = challenges
        self.runner = runner

    async def evaluate(
        self,
        invocation: ToolInvocation,
        submission: ToolSubmission,
        session: InterviewSession,
        job: JobSpec,
    ) -> ToolEvaluation:
        source = submission.content.get("code")
        if not isinstance(source, str) or not source.strip():
            return ToolEvaluation(
                tool_id=invocation.id,
                submission_id=submission.id,
                passed=False,
                score=0.0,
                summary="Coding submission did not contain non-empty source code.",
                evidence={"reason": "missing_code"},
            )

        challenge = self.challenges.get(invocation.id)
        tests = [*challenge.public_tests, *challenge.hidden_tests]
        harness = _build_harness(tests)

        try:
            result = await self.runner.run_python(
                source=source,
                harness=harness,
                limits=SandboxLimits(timeout_seconds=challenge.timeout_seconds),
            )
        except SandboxUnavailable as exc:
            return ToolEvaluation(
                tool_id=invocation.id,
                submission_id=submission.id,
                passed=None,
                score=None,
                summary=(
                    "Submission recorded, but automatic code execution is unavailable. "
                    "Manual or external sandbox review is required."
                ),
                evidence={
                    "sandbox_unavailable": str(exc),
                    "review_required": True,
                },
            )

        parsed = _parse_result(result.stdout)
        if result.timed_out:
            return ToolEvaluation(
                tool_id=invocation.id,
                submission_id=submission.id,
                passed=False,
                score=0.0,
                summary="Code execution exceeded the configured time limit.",
                evidence={
                    "timed_out": True,
                    "duration_ms": result.duration_ms,
                },
            )

        if parsed is None:
            return ToolEvaluation(
                tool_id=invocation.id,
                submission_id=submission.id,
                passed=False,
                score=0.0,
                summary="Sandbox completed without a valid Nora test result.",
                evidence={
                    "exit_code": result.exit_code,
                    "stderr": result.stderr[-4000:],
                    "duration_ms": result.duration_ms,
                },
            )

        total = int(parsed.get("total", 0))
        passed_count = int(parsed.get("passed", 0))
        score = (passed_count / total) if total else None
        return ToolEvaluation(
            tool_id=invocation.id,
            submission_id=submission.id,
            passed=(passed_count == total and total > 0),
            score=score,
            summary=f"Passed {passed_count}/{total} configured tests.",
            evidence={
                "passed_tests": passed_count,
                "total_tests": total,
                "failures": parsed.get("failures", []),
                "duration_ms": result.duration_ms,
                "exit_code": result.exit_code,
                "sandbox": "docker-or-external",
            },
        )
