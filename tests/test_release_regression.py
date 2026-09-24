import asyncio

from nora_interviewer.audit import verify_event_chain
from nora_interviewer.models import (
    CandidateControlKind,
    CandidateControlRequest,
    Competency,
    CreateSession,
    EvidenceObservation,
    EvidenceState,
    JobSpec,
    SessionStatus,
    Speaker,
    ToolEvaluation,
    ToolInvocation,
    ToolKind,
    ToolSubmissionRequest,
)
from nora_interviewer.providers import RuleBasedBrain
from nora_interviewer.review_service import ReviewService
from nora_interviewer.service import InterviewService
from nora_interviewer.storage import InMemoryStore
from nora_interviewer.tools import ToolRegistry


class PassingReleaseCaseTool:
    kind = ToolKind.CASE_STUDY

    async def evaluate(
        self,
        invocation,
        submission,
        session,
        job,
    ):
        return ToolEvaluation(
            tool_id=invocation.id,
            submission_id=submission.id,
            passed=True,
            score=0.9,
            summary=(
                "The artifact identifies a concrete reliability control "
                "and an observable validation signal."
            ),
            evidence={
                "check": "release-regression",
                "review_required": False,
            },
        )


def run(coro):
    return asyncio.run(coro)


def test_full_release_regression_covers_interview_controls_evidence_tool_review_and_export():
    async def scenario():
        store = InMemoryStore()
        registry = ToolRegistry()
        registry.register(PassingReleaseCaseTool())
        service = InterviewService(
            store,
            RuleBasedBrain(),
            tool_registry=registry,
        )
        review = ReviewService(store)

        job = await service.create_job(
            JobSpec(
                id="release-job",
                title="Backend Engineer",
                description=(
                    "Build, debug, and operate reliable backend systems."
                ),
                competencies=[
                    Competency(
                        id="debugging",
                        description="production debugging",
                        anchor_question=(
                            "Describe a production incident you debugged."
                        ),
                    ),
                    Competency(
                        id="systems",
                        description="reliable systems design",
                        anchor_question=(
                            "Describe a reliability design trade-off."
                        ),
                    ),
                ],
                max_questions=5,
                anchor_ratio=0.5,
            )
        )
        session = await service.create_session(
            CreateSession(
                job_id=job.id,
                candidate_ref="release-candidate",
                locale="en",
                consent_to_ai_interview=True,
                consent_to_transcript=True,
            )
        )

        opening = await service.start(session.id)
        assert opening.status is SessionStatus.RUNNING
        assert opening.interviewer_turn is not None

        pause = await service.candidate_control(
            session.id,
            CandidateControlRequest(
                kind=CandidateControlKind.THINKING_TIME,
            ),
        )
        assert pause.pauses_interview is True

        resume = await service.candidate_control(
            session.id,
            CandidateControlRequest(
                kind=CandidateControlKind.RESUME,
            ),
        )
        assert resume.pauses_interview is False

        first_answer = (
            "I reproduced the timeout under the same production-like load, "
            "compared request traces with database latency, isolated a blocking "
            "driver, verified the hypothesis with a controlled rollout, and "
            "measured latency before and after the change."
        )
        step = await service.answer(
            session.id,
            first_answer,
        )
        assert step.interviewer_turn is not None

        current = await store.get_session(session.id)
        candidate_turn = next(
            turn
            for turn in current.turns
            if turn.speaker is Speaker.CANDIDATE
            and turn.text == first_answer
        )

        observed = await service.observe_evidence(
            session.id,
            EvidenceObservation(
                competency_id="debugging",
                turn_id=candidate_turn.id,
                state=EvidenceState.DEMONSTRATED,
                confidence=0.95,
                quote="compared request traces with database latency",
                note=(
                    "The answer describes a concrete diagnostic comparison "
                    "and a measured validation step."
                ),
                source="release-regression",
            ),
        )
        assert observed.state is EvidenceState.DEMONSTRATED

        invocation = await service.open_tool(
            session.id,
            ToolInvocation(
                kind=ToolKind.CASE_STUDY,
                title="Reliability case",
                instructions=(
                    "Choose one control that limits dependency failure impact "
                    "and explain how you would verify it."
                ),
                competency_tags=["systems"],
            ),
        )
        tool_step = await service.submit_tool(
            session.id,
            invocation.id,
            ToolSubmissionRequest(
                content={
                    "answer": (
                        "Use bounded timeouts plus a circuit breaker, then "
                        "verify dependency latency and fallback rate under load."
                    )
                }
            ),
        )
        assert tool_step.evaluation.passed is True
        assert tool_step.interviewer_turn is not None

        closing = await service.answer(
            session.id,
            (
                "The circuit breaker prevents a slow dependency from exhausting "
                "request capacity. I would tune its thresholds from observed "
                "latency and error distributions, test recovery behavior, and "
                "watch SLO burn rate before widening the rollout."
            ),
        )
        assert closing.status is SessionStatus.COMPLETED

        current = await store.get_session(session.id)
        assert current is not None
        assert current.status is SessionStatus.COMPLETED
        assert current.paused is False
        assert current.tool_submissions
        assert current.tool_evaluations
        assert current.evidence_graph["debugging"].state in {
            EvidenceState.DEMONSTRATED,
            EvidenceState.VERIFIED,
        }
        assert current.evidence_graph["systems"].state is EvidenceState.DEMONSTRATED

        report = await review.session_report(session.id)
        assert report.session_id == session.id
        assert report.job_id == job.id
        assert report.role == job.title

        head_hash = verify_event_chain(current.events)
        assert head_hash is not None

        trace = await service.export_voxrubric(
            session.id
        )
        assert trace.session_id == session.id
        assert trace.role == job.title
        assert trace.metadata["status"] == "completed"
        assert trace.metadata["candidate_controls"] == [
            {
                "kind": "thinking_time",
                "target_turn_id": opening.interviewer_turn.id,
                "text": None,
            },
            {
                "kind": "resume",
                "target_turn_id": opening.interviewer_turn.id,
                "text": None,
            },
        ]
        assert trace.metadata["audit_chain"]["verified"] is True
        assert trace.metadata["audit_chain"]["head_hash"] == head_hash
        assert (
            trace.metadata["audit_chain"]["event_count"]
            == len(current.events)
        )
        assert len(trace.metadata["tools"]) == 1
        assert len(trace.metadata["tool_submissions"]) == 1
        assert len(trace.metadata["tool_evaluations"]) == 1
        assert (
            trace.metadata["evidence_graph"]["debugging"]["state"]
            == current.evidence_graph["debugging"].state.value
        )

        exported_candidate_ids = {
            turn["id"]
            for turn in trace.turns
            if turn["speaker"] == "candidate"
        }
        assert candidate_turn.id in exported_candidate_ids

    run(scenario())
