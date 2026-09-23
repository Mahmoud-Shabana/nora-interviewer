import asyncio

from nora_interviewer.models import (
    Competency,
    CreateSession,
    JobSpec,
)
from nora_interviewer.providers import RuleBasedBrain
from nora_interviewer.service import InterviewService
from nora_interviewer.storage import InMemoryStore
from nora_interviewer.voice import (
    RealtimeVoiceCoordinator,
    VoiceTransportFallbackEvent,
    VoiceTransportSelectionEvent,
)


def run(coro):
    return asyncio.run(coro)


def test_voice_transport_telemetry_is_audited_and_exported():
    async def scenario():
        store = InMemoryStore()
        service = InterviewService(
            store,
            RuleBasedBrain(),
        )
        voice = RealtimeVoiceCoordinator(
            service=service,
            store=store,
        )

        job = await service.create_job(
            JobSpec(
                id="job",
                title="Engineer",
                description="Build reliable systems",
                competencies=[
                    Competency(
                        id="debugging",
                        description="production debugging",
                    )
                ],
            )
        )
        session = await service.create_session(
            CreateSession(
                job_id=job.id,
                candidate_ref="candidate",
                consent_to_ai_interview=True,
                consent_to_transcript=True,
            )
        )

        await voice.transport_selected(
            session.id,
            VoiceTransportSelectionEvent(
                direction="stt",
                transport="server",
                provider_id="stt-a",
            ),
        )
        await voice.provider_failed(
            session.id,
            direction="stt",
            provider_id="stt-a",
            error_type="TimeoutError",
            message="upstream timeout",
        )
        await voice.transport_fallback(
            session.id,
            VoiceTransportFallbackEvent(
                direction="stt",
                from_transport="server",
                to_transport="browser",
                reason="upstream timeout",
            ),
        )
        await voice.transport_selected(
            session.id,
            VoiceTransportSelectionEvent(
                direction="stt",
                transport="browser",
                reason="browser speech recognition",
            ),
        )

        current = await store.get_session(
            session.id
        )
        event_types = [
            event.type.value
            for event in current.events
        ]
        assert event_types[-4:] == [
            "voice_transport_selected",
            "voice_provider_failed",
            "voice_transport_fallback",
            "voice_transport_selected",
        ]

        trace = await service.export_voxrubric(
            session.id
        )
        voice_events = trace.metadata["voice_events"]
        telemetry = [
            event["type"]
            for event in voice_events
            if event["type"].startswith(
                "voice_transport_"
            )
            or event["type"]
            == "voice_provider_failed"
        ]
        assert telemetry == [
            "voice_transport_selected",
            "voice_provider_failed",
            "voice_transport_fallback",
            "voice_transport_selected",
        ]

    run(scenario())


def test_voice_transport_fallback_validation_rejects_same_transport():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(
        ValidationError,
        match="must change transport",
    ):
        VoiceTransportFallbackEvent(
            direction="tts",
            from_transport="server",
            to_transport="server",
            reason="invalid",
        )
