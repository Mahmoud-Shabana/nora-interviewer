from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .models import (
    InterviewSession,
    JobSpec,
    ToolEvaluation,
    ToolInvocation,
    ToolKind,
    ToolSubmission,
)


def _present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


def _text_volume(value: Any) -> int:
    if isinstance(value, str):
        return len(value.strip())
    if isinstance(value, Mapping):
        return sum(
            _text_volume(item)
            for item in value.values()
        )
    if isinstance(value, (list, tuple, set)):
        return sum(
            _text_volume(item)
            for item in value
        )
    return 0


class StructuredDomainEvaluator:
    """Validate domain-artifact structure without making a hiring decision."""

    evaluator_version = "1"

    def __init__(
        self,
        *,
        kind: ToolKind,
        evaluator_id: str,
        default_deliverables: tuple[str, ...],
    ) -> None:
        self.kind = kind
        self.evaluator_id = evaluator_id
        self.default_deliverables = (
            default_deliverables
        )

    def _required_deliverables(
        self,
        invocation: ToolInvocation,
    ) -> list[str]:
        raw = invocation.payload.get(
            "deliverables"
        )
        if (
            isinstance(raw, list)
            and all(
                isinstance(item, str)
                and item.strip()
                for item in raw
            )
        ):
            return [
                item.strip()
                for item in raw
            ]
        return list(
            self.default_deliverables
        )

    def _domain_signals(
        self,
        invocation: ToolInvocation,
        submission: ToolSubmission,
    ) -> dict[str, Any]:
        return {}

    async def evaluate(
        self,
        invocation: ToolInvocation,
        submission: ToolSubmission,
        session: InterviewSession,
        job: JobSpec,
    ) -> ToolEvaluation:
        required = self._required_deliverables(
            invocation
        )
        observed = [
            key
            for key in required
            if _present(
                submission.content.get(key)
            )
        ]
        missing = [
            key
            for key in required
            if key not in observed
        ]
        completeness = (
            len(observed) / len(required)
            if required
            else 1.0
        )
        template_id = invocation.payload.get(
            "template_id"
        )
        signals = self._domain_signals(
            invocation,
            submission,
        )
        content_volume = _text_volume(
            submission.content
        )

        if missing:
            summary = (
                f"Structured {self.kind.value} artifact is incomplete: "
                f"{len(missing)} required deliverable(s) are missing. "
                "Human review is required."
            )
        else:
            summary = (
                f"Structured {self.kind.value} artifact contains all "
                "declared deliverables. Content quality and job-related "
                "evidence still require human review."
            )

        return ToolEvaluation(
            tool_id=invocation.id,
            submission_id=submission.id,
            passed=None,
            score=None,
            summary=summary,
            evidence={
                "review_required": True,
                "structured_validation": {
                    "required_deliverables": required,
                    "observed_deliverables": observed,
                    "missing_deliverables": missing,
                    "completeness_ratio": round(
                        completeness,
                        4,
                    ),
                    "content_text_characters": (
                        content_volume
                    ),
                },
                "domain_signals": signals,
                "evaluation_provenance": {
                    "evaluator_id": self.evaluator_id,
                    "evaluator_version": (
                        self.evaluator_version
                    ),
                    "tool_kind": self.kind.value,
                    "template_id": (
                        str(template_id)
                        if template_id is not None
                        else None
                    ),
                    "automatic_hiring_decision": False,
                    "automatic_score": False,
                },
                "competency_tags": (
                    invocation.competency_tags
                ),
            },
        )


class SystemDesignEvaluator(
    StructuredDomainEvaluator
):
    def __init__(self) -> None:
        super().__init__(
            kind=ToolKind.CASE_STUDY,
            evaluator_id=(
                "nora.domain.system_design"
            ),
            default_deliverables=(
                "architecture_summary",
                "failure_modes",
                "tradeoffs",
                "validation_metrics",
            ),
        )

    def _domain_signals(
        self,
        invocation: ToolInvocation,
        submission: ToolSubmission,
    ) -> dict[str, Any]:
        failure_modes = submission.content.get(
            "failure_modes"
        )
        tradeoffs = submission.content.get(
            "tradeoffs"
        )
        metrics = submission.content.get(
            "validation_metrics"
        )
        return {
            "failure_modes_present": _present(
                failure_modes
            ),
            "tradeoffs_present": _present(
                tradeoffs
            ),
            "validation_metrics_present": _present(
                metrics
            ),
        }


class DocumentAnalysisEvaluator(
    StructuredDomainEvaluator
):
    def __init__(self) -> None:
        super().__init__(
            kind=ToolKind.DOCUMENT,
            evaluator_id=(
                "nora.domain.document_analysis"
            ),
            default_deliverables=(
                "verified_facts",
                "open_questions",
                "contributing_factors",
                "remediation",
            ),
        )

    def _domain_signals(
        self,
        invocation: ToolInvocation,
        submission: ToolSubmission,
    ) -> dict[str, Any]:
        evidence_refs = submission.content.get(
            "evidence_refs"
        )
        has_refs = (
            isinstance(evidence_refs, list)
            and any(
                isinstance(item, str)
                and item.strip()
                for item in evidence_refs
            )
        )
        open_questions = submission.content.get(
            "open_questions"
        )
        return {
            "evidence_references_present": (
                has_refs
            ),
            "uncertainty_explicit": _present(
                open_questions
            ),
            "warning": (
                None
                if has_refs
                else (
                    "No explicit evidence_refs were supplied; "
                    "reviewers should verify factual grounding."
                )
            ),
        }


class DataAnalysisEvaluator(
    StructuredDomainEvaluator
):
    def __init__(self) -> None:
        super().__init__(
            kind=ToolKind.DATASET,
            evaluator_id=(
                "nora.domain.data_analysis"
            ),
            default_deliverables=(
                "analysis",
                "assumptions",
                "result",
                "validation",
            ),
        )

    def _domain_signals(
        self,
        invocation: ToolInvocation,
        submission: ToolSubmission,
    ) -> dict[str, Any]:
        assumptions = submission.content.get(
            "assumptions"
        )
        validation = submission.content.get(
            "validation"
        )
        calculations = submission.content.get(
            "calculations"
        )
        return {
            "assumptions_explicit": _present(
                assumptions
            ),
            "validation_present": _present(
                validation
            ),
            "calculations_provided": _present(
                calculations
            ),
        }
