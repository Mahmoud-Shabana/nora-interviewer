import asyncio

from nora_interviewer.audit import AuditChainError
from nora_interviewer.models import (
    Competency,
    CreateSession,
    JobSpec,
)
from nora_interviewer.providers import RuleBasedBrain
from nora_interviewer.service import InterviewService
from nora_interviewer.storage import InMemoryStore


def run(coro):
    return asyncio.run(coro)


def test_voxrubric_export_contains_verifiable_audit_chain():
    async def scenario():
        store = InMemoryStore()
        service = InterviewService(
            store,
            RuleBasedBrain(),
        )
        job = await service.create_job(JobSpec(
            id="audit-export-job",
            title="Engineer",
            description="System audit fixture",
            competencies=[
                Competency(
                    id="debugging",
                    description="debugging",
                    anchor_question="Describe an incident.",
                )
            ],
        ))
        session = await service.create_session(CreateSession(
            job_id=job.id,
            candidate_ref="fixture",
            consent_to_ai_interview=True,
            consent_to_transcript=True,
        ))
        await service.start(session.id)

        trace = await service.export_voxrubric(
            session.id
        )
        chain = trace.metadata["audit_chain"]
        events = trace.metadata["audit_events"]

        assert chain["verified"] is True
        assert chain["event_count"] == len(events)
        assert chain["head_hash"] == events[-1]["event_hash"]
        assert all(
            event["hash_version"] == 1
            for event in events
        )

    run(scenario())


def test_export_refuses_tampered_internal_audit_history():
    async def scenario():
        store = InMemoryStore()
        service = InterviewService(
            store,
            RuleBasedBrain(),
        )
        job = await service.create_job(JobSpec(
            id="tamper-export-job",
            title="Engineer",
            description="System audit fixture",
            competencies=[
                Competency(
                    id="debugging",
                    description="debugging",
                )
            ],
        ))
        session = await service.create_session(CreateSession(
            job_id=job.id,
            candidate_ref="fixture",
            consent_to_ai_interview=True,
            consent_to_transcript=True,
        ))

        current = await store.get_session(session.id)
        current.events[0].payload["job_id"] = "tampered"
        await store.put_session(current)

        try:
            await service.export_voxrubric(
                session.id
            )
            assert False, "expected AuditChainError"
        except AuditChainError:
            pass

    run(scenario())
