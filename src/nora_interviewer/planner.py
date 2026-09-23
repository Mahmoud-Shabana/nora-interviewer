from __future__ import annotations

from math import ceil

from .models import AgentDecision, InterviewSession, JobSpec, QuestionLane


class DualLanePlanner:
    """Balance standardized anchor questions with adaptive investigation.

    Anchors provide comparability across candidates. Adaptive turns are still
    delegated to the interview brain. The planner only decides when an anchor
    must be scheduled to preserve the configured minimum share.
    """

    def anchor_budget(self, job: JobSpec) -> int:
        available = sum(1 for c in job.competencies if c.anchor_question)
        target = ceil(job.max_questions * job.anchor_ratio)
        return min(available, target)

    def next_anchor(self, session: InterviewSession, job: JobSpec) -> AgentDecision | None:
        budget = self.anchor_budget(job)
        if len(session.asked_anchor_competencies) >= budget:
            return None

        unasked = [
            c for c in job.competencies
            if c.anchor_question and c.id not in session.asked_anchor_competencies
        ]
        if not unasked:
            return None

        if session.asked_questions == 0:
            chosen = unasked[0]
        else:
            current_share = len(session.asked_anchor_competencies) / session.asked_questions
            if current_share >= job.anchor_ratio:
                return None
            chosen = unasked[0]

        return AgentDecision(
            text=chosen.anchor_question or "",
            competency_tags=[chosen.id],
            reason=f"{QuestionLane.ANCHOR.value}:standardized_anchor",
        )

    @staticmethod
    def lane_for(decision: AgentDecision) -> QuestionLane:
        if decision.completes_interview:
            return QuestionLane.CLOSING
        if decision.reason.startswith(f"{QuestionLane.ANCHOR.value}:"):
            return QuestionLane.ANCHOR
        return QuestionLane.ADAPTIVE
