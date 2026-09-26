from __future__ import annotations

from datetime import datetime, timezone
from time import perf_counter

from fastapi import HTTPException
from pydantic_core import to_jsonable_python

from .audit import append_event, verify_event_chain
from .coding import CodingChallengeManager, CodingChallengeRequest, CodingInterviewTool
from .controls import handle_candidate_control
from .counterfactual import CounterfactualReplayReport, CounterfactualReplayer
from .evidence import EvidenceGraph
from .evidence_judge import (
    DisabledEvidenceJudge,
    EvidenceJudge,
    EvidenceJudgeError,
    GroundedEvidenceGate,
)
from .feedback import CandidateFeedbackReport, build_candidate_feedback
from .models import (
    AppealReviewRequest,
    CandidateAppeal,
    CandidateAppealRequest,
    CandidateControlKind,
    CandidateControlRequest,
    CandidateControlResult,
    CancelSessionRequest,
    CreateSession,
    EvidenceJudgeRun,
    EvidenceObservation,
    EvidenceState,
    EventType,
    IntegrityReviewRequest,
    IntegrityReviewStatus,
    IntegritySignal,
    IntegritySignalRequest,
    InterviewEvent,
    InterviewSession,
    JobSpec,
    QuestionLane,
    SessionStatus,
    SessionStep,
    Speaker,
    ToolEvaluation,
    ToolInvocation,
    ToolStatus,
    ToolStep,
    ToolSubmission,
    ToolSubmissionRequest,
    TranscriptCorrectionRequest,
    TranscriptRevision,
    Turn,
    VoxRubricTrace,
)
from .planner import DualLanePlanner
from .providers.base import InterviewBrain
from .replay import ReplayState, replay_events
from .sandbox import default_sandbox_runner
from .storage import Store, StoreConflictError
from .tool_templates import ToolTemplateRegistry, default_tool_template_registry
from .tools import ToolRegistry, default_tool_registry


class InterviewService:
    def __init__(
        self,
        store: Store,
        brain: InterviewBrain,
        planner: DualLanePlanner | None = None,
        tool_registry: ToolRegistry | None = None,
        evidence_judge: EvidenceJudge | None = None,
    ) -> None:
        self.store = store
        self.brain = brain
        self.planner = planner or DualLanePlanner()
        self.tool_registry = tool_registry or default_tool_registry()
        self.evidence_judge = evidence_judge or DisabledEvidenceJudge()
        self.coding_challenges = CodingChallengeManager()
        self.tool_registry.register(
            CodingInterviewTool(
                challenges=self.coding_challenges,
                runner=default_sandbox_runner(),
            )
        )
        self.tool_template_registry: ToolTemplateRegistry = (
            default_tool_template_registry(self.coding_challenges)
        )
        self.counterfactual_replayer = CounterfactualReplayer()

    async def create_job(
        self,
        job: JobSpec,
        *,
        organization_id: str | None = None,
    ) -> JobSpec:
        if organization_id is not None:
            if (
                job.organization_id is not None
                and job.organization_id != organization_id
            ):
                raise HTTPException(
                    403,
                    "Job organization does not match authenticated organization",
                )
            job = job.model_copy(
                update={"organization_id": organization_id},
            )

        for item in job.tool_templates:
            try:
                self.tool_template_registry.get(item.template_id)
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
        await self.store.put_job(job)
        return job

    async def create_session(
        self,
        request: CreateSession,
        *,
        organization_id: str | None = None,
    ) -> InterviewSession:
        if not request.consent_to_ai_interview or not request.consent_to_transcript:
            raise HTTPException(400, "Explicit consent to the AI interview and transcript is required.")
        job = await self.store.get_job(request.job_id)
        if not job:
            raise HTTPException(404, "Job not found")
        if organization_id is not None:
            if job.organization_id is None:
                raise HTTPException(
                    403,
                    "Organization-scoped identity cannot create a session for an unscoped job",
                )
            if job.organization_id != organization_id:
                raise HTTPException(
                    403,
                    "Job belongs to a different organization",
                )
        session = InterviewSession(
            job_id=job.id,
            candidate_ref=request.candidate_ref,
            organization_id=job.organization_id,
            locale=request.locale,
            integrity_level=request.integrity_level,
        )
        EvidenceGraph.initialize(session, job)
        append_event(
            session,
            EventType.SESSION_CREATED,
            payload={
                "job_id": job.id,
                "organization_id": session.organization_id,
                "locale": session.locale,
                "integrity_level": session.integrity_level.value,
            },
        )
        await self._persist_session(session)
        return session

    async def start(self, session_id: str) -> SessionStep:
        session, job = await self._get(session_id)
        if session.status in {
            SessionStatus.COMPLETED,
            SessionStatus.CANCELLED,
        }:
            return SessionStep(session_id=session.id, status=session.status)
        if session.status is SessionStatus.RUNNING and session.turns:
            last = session.turns[-1]
            return SessionStep(
                session_id=session.id,
                status=session.status,
                interviewer_turn=last if last.speaker is Speaker.INTERVIEWER else None,
            )

        append_event(session, EventType.INTERVIEW_STARTED)
        decision = self.planner.next_anchor(session, job)
        latency_ms = 0
        if decision is None:
            started = perf_counter()
            decision = await self.brain.opening(session, job)
            latency_ms = max(0, round((perf_counter() - started) * 1000))

        turn = self._apply_decision(session, decision, latency_ms=latency_ms)
        tool_invocation = await self._open_requested_tool(
            session,
            job,
            decision,
            opened_from_turn_id=turn.id,
        )
        session.status = SessionStatus.RUNNING
        await self._persist_session(session)
        return SessionStep(
            session_id=session.id,
            status=session.status,
            interviewer_turn=turn,
            tool_invocation=tool_invocation,
        )

    async def answer(
        self,
        session_id: str,
        text: str,
        *,
        turn_metadata: dict | None = None,
    ) -> SessionStep:
        session, job = await self._get(session_id)
        if session.status is SessionStatus.CREATED:
            await self.start(session_id)
            session, job = await self._get(session_id)
        if session.status is SessionStatus.COMPLETED:
            raise HTTPException(409, "Interview is already complete")
        if session.status is SessionStatus.CANCELLED:
            raise HTTPException(409, "Interview is cancelled")
        if session.paused:
            raise HTTPException(409, "Interview is paused; send a resume candidate control first.")

        previous_question = next(
            (
                turn
                for turn in reversed(session.turns)
                if turn.speaker is Speaker.INTERVIEWER
                and not turn.metadata.get("non_evaluative")
                and not turn.metadata.get("candidate_control")
            ),
            None,
        )
        candidate = Turn(
            speaker=Speaker.CANDIDATE,
            text=text,
            parent_turn_id=previous_question.id if previous_question else None,
            metadata=dict(turn_metadata or {}),
        )
        session.turns.append(candidate)
        append_event(
            session,
            EventType.CANDIDATE_TURN,
            turn=candidate,
            payload={
                "parent_turn_id": candidate.parent_turn_id,
                "metadata": candidate.metadata,
            },
        )

        if previous_question and previous_question.competency_tags:
            created = EvidenceGraph.record_candidate_claim(
                session,
                question_turn_id=previous_question.id,
                answer_turn_id=candidate.id,
                competency_ids=previous_question.competency_tags,
            )
            for item in created:
                append_event(
                    session,
                    EventType.EVIDENCE_OBSERVED,
                    turn=candidate,
                    payload={
                        "evidence_id": item.id,
                        "state": item.state.value,
                        "source": item.source,
                    },
                )

            await self._judge_candidate_evidence(
                session=session,
                job=job,
                question=previous_question,
                answer=candidate,
            )

        started = perf_counter()
        adaptive_decision = await self.brain.after_answer(session, job)
        latency_ms = max(0, round((perf_counter() - started) * 1000))

        if adaptive_decision.parent_turn_id:
            decision = adaptive_decision
        else:
            decision = self.planner.next_anchor(session, job) or adaptive_decision
            if self.planner.lane_for(decision) is QuestionLane.ANCHOR:
                latency_ms = 0

        interviewer = self._apply_decision(session, decision, latency_ms=latency_ms)

        if decision.parent_turn_id and decision.competency_tags:
            key = decision.competency_tags[0]
            session.followups_by_competency[key] = session.followups_by_competency.get(key, 0) + 1
        tool_invocation = await self._open_requested_tool(
            session,
            job,
            decision,
            opened_from_turn_id=interviewer.id,
        )

        if decision.completes_interview:
            session.status = SessionStatus.COMPLETED
            if session.completed_at is None:
                session.completed_at = datetime.now(timezone.utc)
            append_event(session, EventType.SESSION_COMPLETED)

        await self._persist_session(session)
        return SessionStep(
            session_id=session.id,
            status=session.status,
            interviewer_turn=interviewer,
            tool_invocation=tool_invocation,
        )

    async def cancel_session(
        self,
        session_id: str,
        request: CancelSessionRequest,
    ) -> InterviewSession:
        session, _ = await self._get(session_id)

        if session.status is SessionStatus.COMPLETED:
            raise HTTPException(
                409,
                "Completed interviews cannot be cancelled",
            )
        if session.status is SessionStatus.CANCELLED:
            return session

        cancelled_tools: list[str] = []
        for tool in session.tools:
            if tool.status in {
                ToolStatus.OPEN,
                ToolStatus.SUBMITTED,
            }:
                tool.status = ToolStatus.CANCELLED
                cancelled_tools.append(tool.id)
                append_event(
                    session,
                    EventType.TOOL_CANCELLED,
                    payload={
                        "tool_id": tool.id,
                        "kind": tool.kind.value,
                        "reason": "session_cancelled",
                    },
                )

        session.paused = False
        session.status = SessionStatus.CANCELLED
        session.cancelled_at = datetime.now(timezone.utc)
        session.cancellation_reason = request.reason
        append_event(
            session,
            EventType.SESSION_CANCELLED,
            payload={
                "reason": request.reason,
                "cancelled_tool_ids": cancelled_tools,
            },
        )
        await self._persist_session(session)
        return session

    async def _judge_candidate_evidence(
        self,
        *,
        session: InterviewSession,
        job: JobSpec,
        question: Turn,
        answer: Turn,
        supersede_existing: bool = False,
        supersedes_run_id: str | None = None,
    ) -> EvidenceJudgeRun | None:
        if self.evidence_judge.judge_id == "disabled":
            return None

        competency_ids = list(dict.fromkeys(question.competency_tags))
        if not competency_ids:
            return None

        revision_count = sum(
            1
            for revision in session.transcript_revisions
            if revision.turn_id == answer.id
        )
        run = EvidenceJudgeRun(
            judge_id=self.evidence_judge.judge_id,
            question_turn_id=question.id,
            answer_turn_id=answer.id,
            competency_ids=competency_ids,
            transcript_revision_count=revision_count,
            supersedes_run_id=supersedes_run_id,
        )

        try:
            response = await self.evidence_judge.evaluate(
                question=question,
                answer=answer,
                job=job,
                competency_ids=competency_ids,
            )
            raw_observations = GroundedEvidenceGate.validate(
                answer=answer,
                response=response,
                judge_id=self.evidence_judge.judge_id,
            )
            observations = [
                observation.model_copy(
                    update={"judge_run_id": run.id}
                )
                for observation in raw_observations
            ]

            if supersede_existing:
                superseded = EvidenceGraph.supersede_semantic_evidence_for_turn(
                    session,
                    turn_id=answer.id,
                )
                for item in superseded:
                    append_event(
                        session,
                        EventType.EVIDENCE_SUPERSEDED,
                        turn=answer,
                        payload={
                            "evidence_id": item.id,
                            "judge_run_id": item.judge_run_id,
                            "answer_turn_id": answer.id,
                            "superseded_by_run_id": run.id,
                        },
                    )

            audit = response.audit
            run.audit = audit
            if audit.get("kind") == "evidence_judge_ensemble":
                disagreements = [
                    item
                    for item in audit.get("competencies", [])
                    if isinstance(item, dict)
                    and not item.get("threshold_met", False)
                ]
                subjudge_failures = [
                    item
                    for item in audit.get("failures", [])
                    if isinstance(item, dict)
                ]
                if disagreements or subjudge_failures:
                    append_event(
                        session,
                        EventType.EVIDENCE_JUDGE_DISAGREEMENT,
                        turn=answer,
                        payload={
                            "judge_run_id": run.id,
                            "judge_id": self.evidence_judge.judge_id,
                            "question_turn_id": question.id,
                            "answer_turn_id": answer.id,
                            "agreement_threshold": audit.get(
                                "agreement_threshold"
                            ),
                            "required_votes": audit.get(
                                "required_votes"
                            ),
                            "disagreements": disagreements,
                            "subjudge_failures": subjudge_failures,
                        },
                    )

            for observation in observations:
                item = EvidenceGraph.apply_observation(
                    session,
                    job,
                    observation,
                )
                run.observation_ids.append(item.id)
                append_event(
                    session,
                    EventType.EVIDENCE_OBSERVED,
                    turn=answer,
                    payload={
                        "evidence_id": item.id,
                        "judge_run_id": run.id,
                        "competency_id": observation.competency_id,
                        "state": observation.state.value,
                        "confidence": observation.confidence,
                        "quote": observation.quote,
                        "source": observation.source,
                    },
                )

            session.evidence_judge_runs.append(run)
            append_event(
                session,
                EventType.EVIDENCE_JUDGE_RUN_RECORDED,
                turn=answer,
                payload={
                    "judge_run_id": run.id,
                    "judge_id": run.judge_id,
                    "question_turn_id": run.question_turn_id,
                    "answer_turn_id": run.answer_turn_id,
                    "observation_ids": run.observation_ids,
                    "transcript_revision_count": run.transcript_revision_count,
                    "supersedes_run_id": run.supersedes_run_id,
                    "failed": False,
                },
            )
            return run

        except (
            EvidenceJudgeError,
            ValueError,
            TypeError,
        ) as exc:
            run.error_type = type(exc).__name__
            run.error = str(exc)[:2000]
            session.evidence_judge_runs.append(run)
            append_event(
                session,
                EventType.EVIDENCE_JUDGE_FAILED,
                turn=answer,
                payload={
                    "judge_run_id": run.id,
                    "judge_id": self.evidence_judge.judge_id,
                    "question_turn_id": question.id,
                    "answer_turn_id": answer.id,
                    "competency_ids": competency_ids,
                    "error_type": run.error_type,
                    "error": run.error,
                },
            )
            append_event(
                session,
                EventType.EVIDENCE_JUDGE_RUN_RECORDED,
                turn=answer,
                payload={
                    "judge_run_id": run.id,
                    "judge_id": run.judge_id,
                    "question_turn_id": run.question_turn_id,
                    "answer_turn_id": run.answer_turn_id,
                    "observation_ids": [],
                    "transcript_revision_count": run.transcript_revision_count,
                    "supersedes_run_id": run.supersedes_run_id,
                    "failed": True,
                },
            )
            return run

    async def reevaluate_evidence(
        self,
        session_id: str,
        answer_turn_id: str,
    ) -> EvidenceJudgeRun:
        session, job = await self._get(session_id)
        if self.evidence_judge.judge_id == "disabled":
            raise HTTPException(
                409,
                "Evidence judge is disabled for this deployment",
            )

        answer = next(
            (
                turn
                for turn in session.turns
                if turn.id == answer_turn_id
            ),
            None,
        )
        if answer is None:
            raise HTTPException(404, "Candidate answer turn not found")
        if answer.speaker is not Speaker.CANDIDATE:
            raise HTTPException(
                400,
                "Evidence re-evaluation requires a candidate answer turn",
            )
        if not answer.parent_turn_id:
            raise HTTPException(
                400,
                "Candidate answer has no linked interviewer question",
            )

        question = next(
            (
                turn
                for turn in session.turns
                if turn.id == answer.parent_turn_id
            ),
            None,
        )
        if question is None or question.speaker is not Speaker.INTERVIEWER:
            raise HTTPException(
                400,
                "Candidate answer references an invalid interviewer question",
            )

        prior_runs = [
            run
            for run in session.evidence_judge_runs
            if run.answer_turn_id == answer.id
        ]
        latest = max(
            prior_runs,
            key=lambda run: run.created_at,
            default=None,
        )
        run = await self._judge_candidate_evidence(
            session=session,
            job=job,
            question=question,
            answer=answer,
            supersede_existing=True,
            supersedes_run_id=latest.id if latest else None,
        )
        if run is None:
            raise HTTPException(
                400,
                "No competency-tagged evidence could be re-evaluated",
            )

        await self._persist_session(session)
        return run

    async def candidate_control(
        self,
        session_id: str,
        request: CandidateControlRequest,
    ) -> CandidateControlResult:
        session, _ = await self._get(session_id)
        if session.status is SessionStatus.COMPLETED:
            raise HTTPException(409, "Interview is already complete")
        if session.status is SessionStatus.CANCELLED:
            raise HTTPException(409, "Interview is cancelled")

        try:
            result = handle_candidate_control(session, request)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

        append_event(
            session,
            EventType.CANDIDATE_CONTROL,
            payload={
                "kind": request.kind.value,
                "text": request.text,
                "target_turn_id": result.target_turn_id,
                "pauses_interview": result.pauses_interview,
            },
        )

        if result.interviewer_turn:
            session.turns.append(result.interviewer_turn)
            append_event(
                session,
                EventType.INTERVIEWER_TURN,
                turn=result.interviewer_turn,
                payload={
                    "candidate_control": request.kind.value,
                    "non_evaluative": True,
                },
            )

        if (
            request.kind is CandidateControlKind.CORRECT_LAST_ANSWER
            and result.target_turn_id
            and request.text
        ):
            self._apply_transcript_correction(
                session,
                TranscriptCorrectionRequest(
                    turn_id=result.target_turn_id,
                    corrected_text=request.text,
                    reason="Candidate correction requested during live interview.",
                ),
            )

        await self._persist_session(session)
        return result

    async def _open_requested_tool(
        self,
        session: InterviewSession,
        job: JobSpec,
        decision,
        *,
        opened_from_turn_id: str,
    ) -> ToolInvocation | None:
        request = decision.tool_request
        if request is None:
            return None

        if len(session.tools) >= job.max_tools:
            raise HTTPException(409, "Job tool budget has been exhausted")

        used_templates = {
            str(tool.payload.get("template_id"))
            for tool in session.tools
            if tool.payload.get("template_id")
        }
        if request.template_id in used_templates:
            raise HTTPException(
                409,
                f"Tool template already used in this session: {request.template_id}",
            )

        policy = {item.template_id: item for item in job.tool_templates}
        allowed = policy.get(request.template_id)
        if allowed is None:
            raise HTTPException(
                400,
                f"Brain requested tool template not allowed by job: {request.template_id}",
            )

        if allowed.competency_ids:
            outside = sorted(
                set(decision.competency_tags) - set(allowed.competency_ids)
            )
            if outside:
                raise HTTPException(
                    400,
                    f"Tool request uses competencies outside its job policy: {outside}",
                )

        try:
            invocation = self.tool_template_registry.instantiate(
                request.template_id,
                session=session,
                job=job,
                competency_tags=decision.competency_tags,
                opened_from_turn_id=opened_from_turn_id,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

        return self._append_tool(
            session,
            job,
            invocation,
        )

    async def open_coding_challenge(
        self,
        session_id: str,
        request: CodingChallengeRequest,
    ) -> ToolInvocation:
        session, job = await self._get(session_id)
        known_competencies = {competency.id for competency in job.competencies}
        unknown = [tag for tag in request.competency_tags if tag not in known_competencies]
        if unknown:
            raise HTTPException(400, f"Coding challenge references unknown competencies: {unknown}")

        if request.opened_from_turn_id:
            known_turns = {turn.id for turn in session.turns}
            if request.opened_from_turn_id not in known_turns:
                raise HTTPException(400, "Coding challenge references unknown opening turn")

        invocation = self.coding_challenges.create(request)
        self._append_tool(
            session,
            job,
            invocation,
        )
        await self._persist_session(session)
        return invocation

    def _append_tool(
        self,
        session: InterviewSession,
        job: JobSpec,
        invocation: ToolInvocation,
    ) -> ToolInvocation:
        if session.status is SessionStatus.COMPLETED:
            raise HTTPException(409, "Interview is already complete")
        if session.status is SessionStatus.CANCELLED:
            raise HTTPException(409, "Interview is cancelled")
        if any(tool.id == invocation.id for tool in session.tools):
            raise HTTPException(409, "Tool invocation id already exists")

        known_competencies = {competency.id for competency in job.competencies}
        unknown = [tag for tag in invocation.competency_tags if tag not in known_competencies]
        if unknown:
            raise HTTPException(400, f"Tool references unknown competencies: {unknown}")

        if invocation.opened_from_turn_id:
            known_turns = {turn.id for turn in session.turns}
            if invocation.opened_from_turn_id not in known_turns:
                raise HTTPException(400, "Tool references unknown opening turn")

        session.tools.append(invocation)
        append_event(
            session,
            EventType.TOOL_OPENED,
            payload={
                "tool_id": invocation.id,
                "kind": invocation.kind.value,
                "competency_tags": invocation.competency_tags,
                "opened_from_turn_id": invocation.opened_from_turn_id,
            },
        )
        return invocation

    async def open_tool(
        self,
        session_id: str,
        invocation: ToolInvocation,
    ) -> ToolInvocation:
        session, job = await self._get(session_id)
        self._append_tool(
            session,
            job,
            invocation,
        )
        await self._persist_session(session)
        return invocation

    async def submit_tool(
        self,
        session_id: str,
        tool_id: str,
        request: ToolSubmissionRequest,
    ) -> ToolStep:
        session, job = await self._get(session_id)
        if session.status is SessionStatus.COMPLETED:
            raise HTTPException(409, "Interview is already complete")
        if session.status is SessionStatus.CANCELLED:
            raise HTTPException(409, "Interview is cancelled")

        invocation = next((tool for tool in session.tools if tool.id == tool_id), None)
        if invocation is None:
            raise HTTPException(404, "Tool invocation not found")
        if invocation.status is not ToolStatus.OPEN:
            raise HTTPException(409, f"Tool is not open: {invocation.status.value}")

        submission = ToolSubmission(tool_id=tool_id, content=request.content)
        session.tool_submissions.append(submission)
        invocation.status = ToolStatus.SUBMITTED
        append_event(
            session,
            EventType.TOOL_SUBMITTED,
            payload={
                "tool_id": tool_id,
                "submission_id": submission.id,
                "artifact_keys": sorted(submission.content.keys()),
            },
        )

        artifact_turn = Turn(
            speaker=Speaker.CANDIDATE,
            text=f"[{invocation.kind.value} artifact submitted]",
            parent_turn_id=invocation.opened_from_turn_id,
            competency_tags=invocation.competency_tags,
            metadata={
                "artifact": True,
                "tool_id": invocation.id,
                "tool_submission_id": submission.id,
                "tool_kind": invocation.kind.value,
            },
        )
        session.turns.append(artifact_turn)
        append_event(
            session,
            EventType.CANDIDATE_TURN,
            turn=artifact_turn,
            payload={
                "artifact": True,
                "tool_id": invocation.id,
                "submission_id": submission.id,
            },
        )

        try:
            evaluator = self.tool_registry.get(invocation.kind)
            evaluation = await evaluator.evaluate(invocation, submission, session, job)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

        session.tool_evaluations.append(evaluation)
        invocation.status = ToolStatus.EVALUATED
        append_event(
            session,
            EventType.TOOL_EVALUATED,
            payload={
                "tool_id": tool_id,
                "submission_id": submission.id,
                "passed": evaluation.passed,
                "score": evaluation.score,
                "summary": evaluation.summary,
            },
        )

        if evaluation.passed is not None:
            state = (
                EvidenceState.DEMONSTRATED
                if evaluation.passed
                else EvidenceState.INSUFFICIENT
            )
            for competency_id in invocation.competency_tags:
                observation = EvidenceObservation(
                    competency_id=competency_id,
                    turn_id=artifact_turn.id,
                    state=state,
                    confidence=1.0,
                    note=evaluation.summary,
                    source=f"tool:{invocation.kind.value}",
                )
                item = EvidenceGraph.apply_observation(
                    session,
                    job,
                    observation,
                )
                append_event(
                    session,
                    EventType.EVIDENCE_OBSERVED,
                    turn=artifact_turn,
                    payload={
                        "evidence_id": item.id,
                        "competency_id": competency_id,
                        "state": state.value,
                        "confidence": observation.confidence,
                        "source": observation.source,
                    },
                )

        started = perf_counter()
        decision = await self.brain.after_tool(
            session,
            job,
            invocation,
            submission,
            evaluation,
        )
        latency_ms = max(0, round((perf_counter() - started) * 1000))
        interviewer = self._apply_decision(
            session,
            decision,
            latency_ms=latency_ms,
        )
        next_tool = await self._open_requested_tool(
            session,
            job,
            decision,
            opened_from_turn_id=interviewer.id,
        )

        if decision.parent_turn_id and decision.competency_tags:
            key = decision.competency_tags[0]
            session.followups_by_competency[key] = (
                session.followups_by_competency.get(key, 0) + 1
            )

        if decision.completes_interview:
            session.status = SessionStatus.COMPLETED
            if session.completed_at is None:
                session.completed_at = datetime.now(timezone.utc)
            append_event(session, EventType.SESSION_COMPLETED)

        await self._persist_session(session)
        return ToolStep(
            tool_id=tool_id,
            evaluation=evaluation,
            interviewer_turn=interviewer,
            next_tool_invocation=next_tool,
            status=session.status,
        )

    def _apply_transcript_correction(
        self,
        session: InterviewSession,
        request: TranscriptCorrectionRequest,
    ) -> TranscriptRevision:
        turn = next((t for t in session.turns if t.id == request.turn_id), None)
        if turn is None:
            raise HTTPException(404, "Turn not found")
        if turn.speaker is not Speaker.CANDIDATE:
            raise HTTPException(400, "Only candidate transcript turns can be corrected")

        revision = TranscriptRevision(
            turn_id=turn.id,
            original_text=turn.text,
            corrected_text=request.corrected_text,
            reason=request.reason,
        )
        session.transcript_revisions.append(revision)
        turn.text = request.corrected_text
        turn.metadata["transcript_revision_id"] = revision.id
        turn.metadata["transcript_revision_count"] = sum(
            1 for item in session.transcript_revisions if item.turn_id == turn.id
        )
        append_event(
            session,
            EventType.TRANSCRIPT_CORRECTED,
            turn=turn,
            payload={
                "revision_id": revision.id,
                "original_text": revision.original_text,
                "corrected_text": revision.corrected_text,
                "reason": revision.reason,
            },
        )

        superseded = EvidenceGraph.supersede_semantic_evidence_for_turn(
            session,
            turn_id=turn.id,
        )
        for item in superseded:
            append_event(
                session,
                EventType.EVIDENCE_SUPERSEDED,
                turn=turn,
                payload={
                    "evidence_id": item.id,
                    "judge_run_id": item.judge_run_id,
                    "answer_turn_id": turn.id,
                    "reason": "transcript_corrected",
                },
            )
        return revision

    async def correct_transcript(
        self,
        session_id: str,
        request: TranscriptCorrectionRequest,
    ) -> TranscriptRevision:
        session, _ = await self._get(session_id)
        revision = self._apply_transcript_correction(
            session,
            request,
        )
        await self._persist_session(session)
        return revision

    async def submit_appeal(
        self,
        session_id: str,
        request: CandidateAppealRequest,
    ) -> CandidateAppeal:
        session, _ = await self._get(session_id)
        known_turn_ids = {turn.id for turn in session.turns}
        unknown = [turn_id for turn_id in request.turn_ids if turn_id not in known_turn_ids]
        if unknown:
            raise HTTPException(400, f"Appeal references unknown turns: {unknown}")

        appeal = CandidateAppeal(message=request.message, turn_ids=request.turn_ids)
        session.appeals.append(appeal)
        append_event(
            session,
            EventType.APPEAL_SUBMITTED,
            payload={"appeal_id": appeal.id, "turn_ids": appeal.turn_ids},
        )
        await self._persist_session(session)
        return appeal

    async def review_appeal(
        self,
        session_id: str,
        appeal_id: str,
        request: AppealReviewRequest,
    ) -> CandidateAppeal:
        session, _ = await self._get(session_id)
        appeal = next(
            (
                item
                for item in session.appeals
                if item.id == appeal_id
            ),
            None,
        )
        if appeal is None:
            raise HTTPException(404, "Appeal not found")
        if appeal.status.value == "reviewed":
            raise HTTPException(409, "Appeal is already reviewed")

        appeal.status = appeal.status.__class__.REVIEWED
        appeal.reviewed_by = request.reviewer_id
        appeal.review_note = request.note
        append_event(
            session,
            EventType.APPEAL_REVIEWED,
            payload={
                "appeal_id": appeal.id,
                "reviewer_id": request.reviewer_id,
                "note": request.note,
            },
        )
        await self._persist_session(session)
        return appeal

    async def submit_integrity_signal(
        self,
        session_id: str,
        request: IntegritySignalRequest,
    ) -> IntegritySignal:
        session, _ = await self._get(session_id)
        signal = IntegritySignal(
            kind=request.kind,
            confidence=request.confidence,
            note=request.note,
            evidence=request.evidence,
            requires_human_review=True,
        )
        session.integrity_signals.append(signal)
        append_event(
            session,
            EventType.INTEGRITY_SIGNAL,
            payload={
                "signal_id": signal.id,
                "kind": signal.kind,
                "confidence": signal.confidence,
                "requires_human_review": True,
            },
        )
        await self._persist_session(session)
        return signal

    async def review_integrity_signal(
        self,
        session_id: str,
        signal_id: str,
        request: IntegrityReviewRequest,
    ) -> IntegritySignal:
        session, _ = await self._get(session_id)
        signal = next(
            (
                item
                for item in session.integrity_signals
                if item.id == signal_id
            ),
            None,
        )
        if signal is None:
            raise HTTPException(404, "Integrity signal not found")
        if signal.review_status is IntegrityReviewStatus.REVIEWED:
            raise HTTPException(409, "Integrity signal is already reviewed")

        signal.review_status = IntegrityReviewStatus.REVIEWED
        signal.reviewed_by = request.reviewer_id
        signal.review_note = request.note
        append_event(
            session,
            EventType.INTEGRITY_REVIEWED,
            payload={
                "signal_id": signal.id,
                "reviewer_id": request.reviewer_id,
                "note": request.note,
                "requires_human_review": True,
            },
        )
        await self._persist_session(session)
        return signal

    async def observe_evidence(
        self,
        session_id: str,
        observation: EvidenceObservation,
    ):
        session, job = await self._get(session_id)
        try:
            item = EvidenceGraph.apply_observation(session, job, observation)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        turn = next(t for t in session.turns if t.id == observation.turn_id)
        append_event(
            session,
            EventType.EVIDENCE_OBSERVED,
            turn=turn,
            payload={
                "evidence_id": item.id,
                "competency_id": observation.competency_id,
                "state": observation.state.value,
                "confidence": observation.confidence,
                "source": item.source,
            },
        )
        await self._persist_session(session)
        return session.evidence_graph[observation.competency_id]

    async def candidate_feedback(self, session_id: str) -> CandidateFeedbackReport:
        session, job = await self._get(session_id)
        return build_candidate_feedback(session, job)

    async def events(self, session_id: str) -> list[InterviewEvent]:
        session, _ = await self._get(session_id)
        return session.events

    async def replay(self, session_id: str) -> ReplayState:
        session, _ = await self._get(session_id)
        return replay_events(session.id, session.events)

    async def decision_replay(
        self,
        session_id: str,
    ) -> CounterfactualReplayReport:
        session, job = await self._get(session_id)
        return await self.counterfactual_replayer.compare(
            session,
            job,
            self.brain,
        )

    async def export_voxrubric(self, session_id: str) -> VoxRubricTrace:
        session, job = await self._get(session_id)
        turns = [
            {
                "id": t.id,
                "speaker": t.speaker.value,
                "text": t.text,
                "parent_turn_id": t.parent_turn_id,
                "rubric_tags": t.competency_tags,
                "response_latency_ms": t.response_latency_ms,
                "metadata": t.metadata,
            }
            for t in session.turns
        ]
        anchor_turns = sum(
            1
            for turn in session.turns
            if turn.speaker is Speaker.INTERVIEWER
            and turn.metadata.get("question_lane") == QuestionLane.ANCHOR.value
        )
        candidate_controls = [
            event.payload
            for event in session.events
            if event.type is EventType.CANDIDATE_CONTROL
        ]
        voice_events = [
            {
                "seq": event.seq,
                "type": event.type.value,
                "turn_id": event.turn_id,
                "payload": event.payload,
            }
            for event in session.events
            if event.type.value.startswith("voice_")
        ]
        evidence_judge_failures = [
            {
                "seq": event.seq,
                "turn_id": event.turn_id,
                "payload": event.payload,
            }
            for event in session.events
            if event.type is EventType.EVIDENCE_JUDGE_FAILED
        ]
        audit_head_hash = verify_event_chain(
            session.events
        )
        audit_events = [
            {
                "seq": event.seq,
                "type": event.type.value,
                "turn_id": event.turn_id,
                "payload": to_jsonable_python(event.payload),
                "created_at": event.created_at.isoformat(),
                "hash_version": event.hash_version,
                "prev_hash": event.prev_hash,
                "event_hash": event.event_hash,
            }
            for event in session.events
        ]
        return VoxRubricTrace(
            session_id=session.id,
            role=job.title,
            locale=session.locale,
            turns=turns,
            metadata={
                "source": "nora-interviewer",
                "job_id": job.id,
                "candidate_ref": session.candidate_ref,
                "status": session.status.value,
                "anchor_ratio_target": job.anchor_ratio,
                "anchor_turns": anchor_turns,
                "interviewer_turns": session.asked_questions,
                "candidate_controls": candidate_controls,
                "voice_events": voice_events,
                "evidence_judge_failures": evidence_judge_failures,
                "audit_chain": {
                    "verified": (
                        True
                        if audit_head_hash is not None
                        else None
                    ),
                    "head_hash": audit_head_hash,
                    "event_count": len(session.events),
                    "hash_version": (
                        1
                        if audit_head_hash is not None
                        else None
                    ),
                },
                "audit_events": audit_events,
                "evidence_graph": {
                    key: value.model_dump(mode="json")
                    for key, value in session.evidence_graph.items()
                },
                "evidence_judge_runs": [
                    run.model_dump(mode="json")
                    for run in session.evidence_judge_runs
                ],
                "transcript_revisions": [
                    revision.model_dump(mode="json")
                    for revision in session.transcript_revisions
                ],
                "appeals": [appeal.model_dump(mode="json") for appeal in session.appeals],
                "integrity_level": session.integrity_level.value,
                "integrity_signals": [
                    signal.model_dump(mode="json")
                    for signal in session.integrity_signals
                ],
                "tools": [tool.model_dump(mode="json") for tool in session.tools],
                "tool_submissions": [
                    submission.model_dump(mode="json")
                    for submission in session.tool_submissions
                ],
                "tool_evaluations": [
                    evaluation.model_dump(mode="json")
                    for evaluation in session.tool_evaluations
                ],
                "event_count": len(session.events),
            },
        )

    async def _persist_session(
        self,
        session: InterviewSession,
    ) -> None:
        try:
            await self.store.put_session(session)
        except StoreConflictError as exc:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Interview state changed concurrently. "
                    "Reload the session and retry the operation."
                ),
            ) from exc

    async def _get(self, session_id: str) -> tuple[InterviewSession, JobSpec]:
        session = await self.store.get_session(session_id)
        if not session:
            raise HTTPException(404, "Session not found")
        job = await self.store.get_job(session.job_id)
        if not job:
            raise HTTPException(500, "Session references a missing job")
        return session, job

    def _apply_decision(
        self,
        session: InterviewSession,
        decision,
        *,
        latency_ms: int | None = None,
    ) -> Turn:
        lane = self.planner.lane_for(decision)
        turn = Turn(
            speaker=Speaker.INTERVIEWER,
            text=decision.text,
            parent_turn_id=decision.parent_turn_id,
            competency_tags=decision.competency_tags,
            response_latency_ms=latency_ms,
            metadata={
                "decision_reason": decision.reason,
                "latency_scope": "brain_only" if latency_ms else "planner",
                "question_lane": lane.value,
            },
        )
        session.turns.append(turn)
        if lane is not QuestionLane.CLOSING:
            session.asked_questions += 1
        if lane is QuestionLane.ANCHOR:
            for competency_id in decision.competency_tags:
                if competency_id not in session.asked_anchor_competencies:
                    session.asked_anchor_competencies.append(competency_id)
        append_event(
            session,
            EventType.INTERVIEWER_TURN,
            turn=turn,
            payload={
                "question_lane": lane.value,
                "decision_reason": decision.reason,
                "competency_tags": decision.competency_tags,
                "covered_competencies": list(session.covered_competencies),
                "asked_questions": session.asked_questions,
            },
        )
        return turn
