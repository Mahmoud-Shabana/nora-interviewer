from fastapi.testclient import TestClient

import nora_interviewer.api as api
from nora_interviewer.authn import (
    DevHeaderPrincipalResolver,
    DisabledPrincipalResolver,
)
from nora_interviewer.capabilities import describe_capabilities
from nora_interviewer.evidence_judge import DisabledEvidenceJudge
from nora_interviewer.providers import RuleBasedBrain
from nora_interviewer.service import InterviewService
from nora_interviewer.storage import InMemoryStore


def test_capability_description_contains_backends_not_secrets(monkeypatch):
    monkeypatch.setenv(
        "NORA_SANDBOX_MODE",
        "disabled",
    )
    store = InMemoryStore()
    service = InterviewService(
        store,
        RuleBasedBrain(),
        evidence_judge=DisabledEvidenceJudge(),
    )

    capabilities = describe_capabilities(
        api_version="test",
        store=store,
        principal_resolver=DisabledPrincipalResolver(),
        service=service,
    )

    assert capabilities.api_version == "test"
    assert capabilities.storage_backend == "InMemoryStore"
    assert capabilities.auth_resolver == "DisabledPrincipalResolver"
    assert capabilities.interview_brain == "RuleBasedBrain"
    assert capabilities.evidence_judge_enabled is False
    assert capabilities.sandbox_mode == "disabled"
    assert capabilities.optimistic_concurrency is True
    assert capabilities.recruiter_review_queue is True
    assert capabilities.recruiter_review_bundle is True
    assert capabilities.recruiter_review_console is True
    assert capabilities.voice_provider_health is True
    assert capabilities.operational_metrics is True
    assert capabilities.correlation_ids is True
    assert capabilities.streaming_stt_enabled is False
    assert (
        capabilities.streaming_stt_backend
        == "DisabledStreamingSpeechProvider"
    )
    assert capabilities.streaming_tts_enabled is False
    assert (
        capabilities.streaming_tts_backend
        == "DisabledStreamingTtsProvider"
    )
    assert capabilities.rubric_drafter_enabled is False
    assert (
        capabilities.rubric_drafter_backend
        == "DisabledRubricDrafter"
    )
    assert capabilities.rubric_draft_persistence is True
    assert capabilities.rubric_human_approval is True
    assert capabilities.job_rubric_provenance is True

    serialized = capabilities.model_dump_json()
    assert "API_KEY" not in serialized
    assert "secret" not in serialized.lower()


def test_capabilities_endpoint_is_not_candidate_visible(monkeypatch):
    monkeypatch.setattr(
        api,
        "principal_resolver",
        DevHeaderPrincipalResolver(),
    )
    client = TestClient(api.app)

    candidate = client.get(
        "/v1/system/capabilities",
        headers={
            "X-Nora-Principal": "candidate",
            "X-Nora-Role": "candidate",
            "X-Nora-Candidate-Ref": "candidate-1",
        },
    )
    assert candidate.status_code == 403

    recruiter = client.get(
        "/v1/system/capabilities",
        headers={
            "X-Nora-Principal": "recruiter",
            "X-Nora-Role": "recruiter",
        },
    )
    assert recruiter.status_code == 200
    assert "storage_backend" in recruiter.json()


def test_capabilities_advertise_session_safety_features():
    from nora_interviewer.capabilities import describe_capabilities
    from nora_interviewer.authn import DisabledPrincipalResolver
    from nora_interviewer.evidence_judge import DisabledEvidenceJudge
    from nora_interviewer.providers import RuleBasedBrain
    from nora_interviewer.service import InterviewService
    from nora_interviewer.storage import InMemoryStore

    store = InMemoryStore()
    service = InterviewService(
        store,
        RuleBasedBrain(),
        evidence_judge=DisabledEvidenceJudge(),
    )
    result = describe_capabilities(
        api_version="test",
        store=store,
        principal_resolver=DisabledPrincipalResolver(),
        service=service,
    )

    assert result.optimistic_concurrency is True
    assert result.session_etags is True
    assert result.session_cancellation is True



def test_voice_provider_health_endpoint_is_system_scoped(monkeypatch):
    monkeypatch.setattr(
        api,
        "principal_resolver",
        DevHeaderPrincipalResolver(),
    )

    with TestClient(api.app) as client:
        candidate = client.get(
            "/v1/system/voice-health",
            headers={
                "X-Nora-Principal": "candidate",
                "X-Nora-Role": "candidate",
                "X-Nora-Candidate-Ref": "candidate-1",
            },
        )
        assert candidate.status_code == 403

        recruiter = client.get(
            "/v1/system/voice-health",
            headers={
                "X-Nora-Principal": "recruiter",
                "X-Nora-Role": "recruiter",
            },
        )
        assert recruiter.status_code == 200
        snapshots = {
            item["key"]: item
            for item in recruiter.json()
        }
        assert set(snapshots) == {
            "streaming_stt",
            "streaming_tts",
        }
        assert snapshots["streaming_stt"]["state"] in {
            "healthy",
            "degraded",
            "open",
            "disabled",
        }


def test_session_voice_capabilities_include_health_and_preferred_stt():
    with TestClient(api.app) as client:
        job = client.post(
            "/v1/jobs",
            json={
                "id": "voice-cap-job",
                "title": "Engineer",
                "description": "Build reliable systems.",
                "competencies": [
                    {
                        "id": "debugging",
                        "description": "production debugging",
                    }
                ],
            },
        )
        assert job.status_code == 201

        session = client.post(
            "/v1/sessions",
            json={
                "job_id": "voice-cap-job",
                "candidate_ref": "candidate",
                "locale": "en",
                "consent_to_ai_interview": True,
                "consent_to_transcript": True,
            },
        )
        assert session.status_code == 201
        session_id = session.json()["id"]

        response = client.get(
            f"/v1/sessions/{session_id}/voice/capabilities"
        )
        assert response.status_code == 200
        payload = response.json()

        assert "streaming_stt_available" in payload
        assert "streaming_tts_available" in payload
        assert payload["stt_health"] in {
            "healthy",
            "degraded",
            "open",
            "disabled",
        }
        assert payload["tts_health"] in {
            "healthy",
            "degraded",
            "open",
            "disabled",
        }
        assert payload["preferred_stt_config"]["encoding"] == "pcm16"
        assert payload["preferred_stt_config"]["sample_rate_hz"] == 16000
