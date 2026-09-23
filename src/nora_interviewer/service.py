from __future__ import annotations

from time import perf_counter

from fastapi import HTTPException

from .models import (
    CreateSession,
    InterviewSession,
    JobSpec,
    SessionStatus,
    SessionStep,
    Speaker,
    Turn,
    VoxRubricTrace,
)
from .providers.base import InterviewBrain
from .storage import InMemoryStore


class InterviewService:
    def __init__(self, store: InMemoryStore, brain: InterviewBrain) -> None:
        self.store = store
        self.brain = brain

    async def create_job(self, job: JobSpec) -> JobSpec:
        await self.store.put_job(job)
        return job

    async def create_session(self, request: CreateSession) -> InterviewSession:
        if not request.consent_to_ai_interview or not request.consent_to_transcript:
            raise HTTPException(400, "Explicit consent to the AI interview and transcript is required.")
        job = await self.store.get_job(request.job_id)
        if not job:
            raise HTTPException(404, "Job not found")
        session = InterviewSession(
            job_id=job.id,
            candidate_ref=request.candidate_ref,
            locale=request.locale,
        )
        await self.store.put_session(session)
        return session

    async def start(self, session_id: str) -> SessionStep:
        session, job = await self._get(session_id)
        if session.status is SessionStatus.COMPLETED:
            return SessionStep(session_id=session.id, status=session.status)
        if session.status is SessionStatus.RUNNING and session.turns:
            last = session.turns[-1]
            return SessionStep(
                session_id=session.id,
                status=session.status,
                interviewer_turn=last if last.speaker is Speaker.INTERVIEWER else None,
            )
        started = perf_counter()
        decision = await self.brain.opening(session, job)
        latency_ms = max(0, round((perf_counter() - started) * 1000))
        turn = self._apply_decision(session, decision, latency_ms=latency_ms)
        session.status = SessionStatus.RUNNING
        await self.store.put_session(session)
        return SessionStep(session_id=session.id, status=session.status, interviewer_turn=turn)

    async def answer(self, session_id: str, text: str) -> SessionStep:
        session, job = await self._get(session_id)
        if session.status is SessionStatus.CREATED:
            await self.start(session_id)
            session, job = await self._get(session_id)
        if session.status is SessionStatus.COMPLETED:
            raise HTTPException(409, "Interview is already complete")

        candidate = Turn(speaker=Speaker.CANDIDATE, text=text)
        session.turns.append(candidate)
        started = perf_counter()
        decision = await self.brain.after_answer(session, job)
        latency_ms = max(0, round((perf_counter() - started) * 1000))
        interviewer = self._apply_decision(session, decision, latency_ms=latency_ms)
        if decision.parent_turn_id and decision.competency_tags:
            key = decision.competency_tags[0]
            session.followups_by_competency[key] = session.followups_by_competency.get(key, 0) + 1
        if decision.completes_interview:
            session.status = SessionStatus.COMPLETED
        await self.store.put_session(session)
        return SessionStep(session_id=session.id, status=session.status, interviewer_turn=interviewer)

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
            },
        )

    async def _get(self, session_id: str) -> tuple[InterviewSession, JobSpec]:
        session = await self.store.get_session(session_id)
        if not session:
            raise HTTPException(404, "Session not found")
        job = await self.store.get_job(session.job_id)
        if not job:
            raise HTTPException(500, "Session references a missing job")
        return session, job

    @staticmethod
    def _apply_decision(session: InterviewSession, decision, *, latency_ms: int | None = None) -> Turn:
        turn = Turn(
            speaker=Speaker.INTERVIEWER,
            text=decision.text,
            parent_turn_id=decision.parent_turn_id,
            competency_tags=decision.competency_tags,
            response_latency_ms=latency_ms,
            metadata={"decision_reason": decision.reason, "latency_scope": "brain_only"},
        )
        session.turns.append(turn)
        session.asked_questions += 1
        return turn
