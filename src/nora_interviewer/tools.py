from __future__ import annotations

from typing import Protocol

from .domain_evaluators import (
    DataAnalysisEvaluator,
    DocumentAnalysisEvaluator,
    SystemDesignEvaluator,
)
from .models import (
    InterviewSession,
    JobSpec,
    ToolEvaluation,
    ToolInvocation,
    ToolKind,
    ToolStatus,
    ToolSubmission,
)


class InterviewTool(Protocol):
    kind: ToolKind

    async def evaluate(
        self,
        invocation: ToolInvocation,
        submission: ToolSubmission,
        session: InterviewSession,
        job: JobSpec,
    ) -> ToolEvaluation: ...


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[ToolKind, InterviewTool] = {}

    def register(self, tool: InterviewTool) -> None:
        self._tools[tool.kind] = tool

    def get(self, kind: ToolKind) -> InterviewTool:
        try:
            return self._tools[kind]
        except KeyError as exc:
            raise ValueError(f"no evaluator registered for tool kind: {kind.value}") from exc


class ManualReviewTool:
    """Default evaluator for artifacts that need a human or external evaluator.

    It deliberately returns no automatic pass/fail score.
    """

    def __init__(self, kind: ToolKind) -> None:
        self.kind = kind

    async def evaluate(
        self,
        invocation: ToolInvocation,
        submission: ToolSubmission,
        session: InterviewSession,
        job: JobSpec,
    ) -> ToolEvaluation:
        return ToolEvaluation(
            tool_id=invocation.id,
            submission_id=submission.id,
            passed=None,
            score=None,
            summary=(
                f"{self.kind.value} submission recorded for human or external evaluation. "
                "No automatic score was produced."
            ),
            evidence={
                "artifact_keys": sorted(submission.content.keys()),
                "competency_tags": invocation.competency_tags,
                "review_required": True,
            },
        )


def default_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    for kind in ToolKind:
        registry.register(ManualReviewTool(kind))

    registry.register(
        SystemDesignEvaluator()
    )
    registry.register(
        DocumentAnalysisEvaluator()
    )
    registry.register(
        DataAnalysisEvaluator()
    )
    return registry
