from __future__ import annotations

import re

from ..models import (
    AgentDecision,
    AgentToolRequest,
    InterviewSession,
    JobSpec,
    Speaker,
    ToolEvaluation,
    ToolInvocation,
    ToolSubmission,
)

_WORD = re.compile(r"\w+", re.UNICODE)


class RuleBasedBrain:
    """Deterministic development brain.

    It proves orchestration, tool flow, follow-up linkage, CI, and export without
    pretending heuristic question generation is the final intelligence layer.
    """

    async def opening(self, session: InterviewSession, job: JobSpec) -> AgentDecision:
        first = job.competencies[0]
        return AgentDecision(
            text=(
                f"Welcome. We’ll discuss your experience for the {job.title} role. "
                f"First, tell me about a concrete example that demonstrates {first.description}"
            ),
            competency_tags=[first.id],
            reason="opening_first_required_competency",
        )

    async def after_answer(self, session: InterviewSession, job: JobSpec) -> AgentDecision:
        candidate_turns = [t for t in session.turns if t.speaker is Speaker.CANDIDATE]
        if not candidate_turns:
            raise ValueError("after_answer requires a candidate turn")
        latest = candidate_turns[-1]
        previous_question = next(
            (
                t for t in reversed(session.turns[:-1])
                if t.speaker is Speaker.INTERVIEWER
                and not t.metadata.get("candidate_control")
                and not t.metadata.get("non_evaluative")
            ),
            None,
        )
        active = (
            previous_question.competency_tags[0]
            if previous_question and previous_question.competency_tags
            else None
        )
        if active is None:
            active = job.competencies[0].id

        word_count = len(_WORD.findall(latest.text))
        followups = session.followups_by_competency.get(active, 0)
        if word_count < 18 and followups < 1:
            return AgentDecision(
                text=(
                    "Could you make that more concrete—what did you personally do, "
                    "what trade-off did you make, and what was the measurable result?"
                ),
                competency_tags=[active],
                parent_turn_id=latest.id,
                reason="answer_lacks_specific_evidence",
            )

        if active not in session.covered_competencies:
            session.covered_competencies.append(active)

        if session.asked_questions >= job.max_questions:
            return self._close()

        if job.tool_templates and len(session.tools) < job.max_tools:
            for policy in job.tool_templates:
                if (
                    not policy.competency_ids
                    or active in policy.competency_ids
                ):
                    return AgentDecision(
                        text=(
                            "I have enough conversational context here. "
                            "Let’s add one short practical artifact before we move on."
                        ),
                        competency_tags=[active],
                        parent_turn_id=latest.id,
                        tool_request=AgentToolRequest(
                            template_id=policy.template_id,
                        ),
                        reason="open_allowed_practical_tool",
                    )

        remaining = [
            c for c in job.competencies
            if c.id not in session.covered_competencies
        ]
        if not remaining:
            return self._close()
        nxt = remaining[0]
        return AgentDecision(
            text=(
                "Let’s move to another area. Tell me about a situation that "
                f"demonstrates {nxt.description}"
            ),
            competency_tags=[nxt.id],
            reason="advance_to_uncovered_competency",
        )

    async def after_tool(
        self,
        session: InterviewSession,
        job: JobSpec,
        invocation: ToolInvocation,
        submission: ToolSubmission,
        evaluation: ToolEvaluation,
    ) -> AgentDecision:
        artifact_turn = next(
            (
                turn
                for turn in reversed(session.turns)
                if turn.speaker is Speaker.CANDIDATE
                and turn.metadata.get("tool_submission_id") == submission.id
            ),
            None,
        )
        tags = invocation.competency_tags or [job.competencies[0].id]

        if evaluation.passed is True:
            text = (
                "The automated checks passed. Explain one design choice in your "
                "artifact, its trade-off, and what you would change for a larger-scale case."
            )
        elif evaluation.passed is False:
            text = (
                "Some automated checks did not pass. Without guessing at hidden tests, "
                "walk me through how you would diagnose the failure and validate the fix."
            )
        else:
            text = (
                "The artifact has been recorded for review. Before we move on, explain "
                "the reasoning behind your approach and the main trade-off you considered."
            )

        return AgentDecision(
            text=text,
            competency_tags=tags,
            parent_turn_id=artifact_turn.id if artifact_turn else None,
            reason="post_tool_reasoning_probe",
        )

    @staticmethod
    def _close() -> AgentDecision:
        return AgentDecision(
            text=(
                "Thank you. That completes the interview. Your responses will now "
                "be made available for the configured human review process."
            ),
            completes_interview=True,
            reason="all_required_coverage_complete",
        )
