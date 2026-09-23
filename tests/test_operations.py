from fastapi.testclient import TestClient

import nora_interviewer.api as api
from nora_interviewer.authn import DevHeaderPrincipalResolver
from nora_interviewer.operations import (
    OperationalSnapshot,
    render_prometheus,
)
from nora_interviewer.provider_health import (
    ProviderHealthSnapshot,
    ProviderHealthState,
)
from nora_interviewer.review import ReviewDashboardSummary


def sample_snapshot() -> OperationalSnapshot:
    return OperationalSnapshot(
        sessions_total=7,
        session_statuses={
            "created": 1,
            "running": 2,
            "completed": 4,
        },
        review=ReviewDashboardSummary(
            total_sessions=7,
            review_required=2,
            pending_appeals=1,
            pending_integrity_signals=1,
            unresolved_tools=3,
            stale_evidence_runs=2,
            failed_evidence_runs=1,
            completed_sessions=4,
        ),
        voice_providers=[
            ProviderHealthSnapshot(
                key="streaming_stt",
                provider_id="websocket-json",
                state=ProviderHealthState.DEGRADED,
                consecutive_failures=1,
                total_failures=4,
                total_successes=12,
                circuit_open_seconds_remaining=0,
                last_error_type="TimeoutError",
                last_error="upstream timed out",
            ),
            ProviderHealthSnapshot(
                key="streaming_tts",
                provider_id="disabled",
                state=ProviderHealthState.DISABLED,
            ),
        ],
        active_audio_streams=2,
        tracked_audio_streams=9,
        active_tts_streams=1,
        session_events_current=120,
        voice_events_current=44,
        tool_invocations_current=8,
        evidence_judge_runs_current=16,
    )


def test_prometheus_renderer_exposes_bounded_operational_metrics_only():
    metrics = render_prometheus(
        sample_snapshot()
    )

    assert "nora_sessions_current 7" in metrics
    assert (
        'nora_sessions_by_status{status="running"} 2'
        in metrics
    )
    assert "nora_review_required_sessions 2" in metrics
    assert "nora_stale_evidence_runs 2" in metrics
    assert "nora_failed_evidence_runs 1" in metrics
    assert "nora_active_audio_streams 2" in metrics
    assert "nora_active_tts_streams 1" in metrics
    assert (
        'nora_voice_provider_info{key="streaming_stt",'
        'provider_id="websocket-json",state="degraded"} 1'
        in metrics
    )

    forbidden = [
        "candidate_ref",
        "session_id",
        "job_id",
        "turn_id",
        "transcript",
        "answer_text",
    ]
    for token in forbidden:
        assert token not in metrics


def test_operational_endpoints_are_system_scoped_and_privacy_minimized(
    monkeypatch,
):
    monkeypatch.setattr(
        api,
        "principal_resolver",
        DevHeaderPrincipalResolver(),
    )

    candidate_headers = {
        "X-Nora-Principal": "candidate-user",
        "X-Nora-Role": "candidate",
        "X-Nora-Candidate-Ref": "private-candidate-ref",
    }
    recruiter_headers = {
        "X-Nora-Principal": "recruiter-user",
        "X-Nora-Role": "recruiter",
    }

    with TestClient(api.app) as client:
        denied_snapshot = client.get(
            "/v1/system/operations",
            headers=candidate_headers,
        )
        denied_metrics = client.get(
            "/v1/system/metrics",
            headers=candidate_headers,
        )
        assert denied_snapshot.status_code == 403
        assert denied_metrics.status_code == 403

        snapshot = client.get(
            "/v1/system/operations",
            headers=recruiter_headers,
        )
        assert snapshot.status_code == 200
        payload = snapshot.json()
        assert "sessions_total" in payload
        assert "voice_providers" in payload
        assert "candidate_ref" not in snapshot.text
        assert "session_id" not in snapshot.text

        metrics = client.get(
            "/v1/system/metrics",
            headers=recruiter_headers,
        )
        assert metrics.status_code == 200
        assert metrics.headers["cache-control"] == "no-store"
        assert metrics.headers["content-type"].startswith(
            "text/plain"
        )
        assert "nora_sessions_current" in metrics.text
        assert "candidate_ref" not in metrics.text
        assert "session_id" not in metrics.text
        assert "turn_id" not in metrics.text
