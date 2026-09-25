import asyncio

import pytest

from nora_interviewer.models import InterviewSession
from nora_interviewer.operations import (
    OperationalSnapshot,
    render_prometheus,
)
from nora_interviewer.provider_health import (
    ProviderHealthSnapshot,
    ProviderHealthState,
)
from nora_interviewer.review import ReviewDashboardSummary
from nora_interviewer.slo import (
    OperationalSloPolicy,
    SloStatus,
    assess_operational_slo,
)
from nora_interviewer.storage import (
    InMemoryStore,
    StoreConflictError,
)


def run(coro):
    return asyncio.run(coro)


def test_release_failure_regression_rejects_stale_writer_and_preserves_winner():
    async def scenario():
        store = InMemoryStore()
        session = InterviewSession(
            id="release-conflict-session",
            job_id="release-job",
            candidate_ref="private-candidate",
            locale="en",
        )
        await store.put_session(session)

        winner = await store.get_session(session.id)
        stale = await store.get_session(session.id)
        assert winner is not None
        assert stale is not None

        winner.paused = True
        await store.put_session(winner)

        stale.paused = False
        with pytest.raises(StoreConflictError):
            await store.put_session(stale)

        current = await store.get_session(session.id)
        assert current is not None
        assert current.version == winner.version
        assert current.paused is True

    run(scenario())


def test_release_failure_signals_are_slo_visible_and_privacy_bounded():
    snapshot = OperationalSnapshot(
        sessions_total=3,
        session_statuses={
            "running": 1,
            "completed": 1,
            "cancelled": 1,
        },
        review=ReviewDashboardSummary(
            total_sessions=3,
            review_required=2,
            pending_appeals=0,
            pending_integrity_signals=0,
            unresolved_tools=0,
            stale_evidence_runs=1,
            failed_evidence_runs=2,
            assigned_reviews=0,
            unassigned_review_required=2,
            completed_sessions=1,
        ),
        voice_providers=[
            ProviderHealthSnapshot(
                key="streaming_stt",
                provider_id="release-stt",
                state=ProviderHealthState.OPEN,
                consecutive_failures=2,
                total_failures=2,
                total_successes=4,
                circuit_open_seconds_remaining=15,
                last_error_type="TimeoutError",
                last_error=(
                    "session_id=secret-session "
                    "candidate_ref=secret-candidate"
                ),
            )
        ],
        active_audio_streams=0,
        tracked_audio_streams=2,
        active_tts_streams=0,
        session_events_current=14,
        voice_events_current=5,
        tool_invocations_current=1,
        evidence_judge_runs_current=3,
    )

    assessment = assess_operational_slo(
        snapshot,
        OperationalSloPolicy(
            max_unassigned_review_required=1,
            max_failed_evidence_runs=1,
        ),
    )

    assert assessment.status is SloStatus.BREACHED
    codes = {signal.code for signal in assessment.signals}
    assert "voice_provider_circuit_open:streaming_stt" in codes
    assert "unassigned_review_backlog" in codes
    assert "failed_evidence_runs" in codes

    metrics = render_prometheus(
        snapshot,
        assessment,
    )
    assert (
        'nora_voice_provider_info{key="streaming_stt",'
        'provider_id="release-stt",state="open"} 1'
    ) in metrics
    assert (
        'nora_operational_slo_status{status="breached"} 1'
        in metrics
    )

    forbidden = [
        "secret-session",
        "secret-candidate",
        "session_id",
        "candidate_ref",
        "job_id",
        "turn_id",
        "transcript",
        "answer_text",
    ]
    for token in forbidden:
        assert token not in metrics
