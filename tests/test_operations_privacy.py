from fastapi.testclient import TestClient

import nora_interviewer.api as api


def test_metrics_never_export_candidate_job_or_transcript_values():
    secret_candidate = "CANDIDATE-DO-NOT-EXPORT-92471"
    secret_job = "JOB-DO-NOT-EXPORT-51823"
    secret_text = "TRANSCRIPT-DO-NOT-EXPORT-77102"

    with TestClient(api.app) as client:
        job = client.post(
            "/v1/jobs",
            json={
                "id": secret_job,
                "title": "Private Role",
                "description": secret_text,
                "competencies": [
                    {
                        "id": "private-skill",
                        "description": secret_text,
                    }
                ],
            },
        )
        assert job.status_code == 201

        session = client.post(
            "/v1/sessions",
            json={
                "job_id": secret_job,
                "candidate_ref": secret_candidate,
                "locale": "en",
                "consent_to_ai_interview": True,
                "consent_to_transcript": True,
            },
        )
        assert session.status_code == 201

        metrics = client.get(
            "/v1/system/metrics"
        )
        assert metrics.status_code == 200

        for secret in (
            secret_candidate,
            secret_job,
            secret_text,
            "private-skill",
        ):
            assert secret not in metrics.text

        snapshot = client.get(
            "/v1/system/operations"
        )
        assert snapshot.status_code == 200
        serialized = snapshot.text
        for secret in (
            secret_candidate,
            secret_job,
            secret_text,
            "private-skill",
        ):
            assert secret not in serialized



def test_http_metrics_export_route_templates_not_concrete_session_ids():
    secret_session_marker = "SESSION-ID-MUST-NOT-BECOME-A-LABEL"

    with TestClient(api.app) as client:
        response = client.get(
            f"/v1/sessions/{secret_session_marker}"
        )
        assert response.status_code == 404

        metrics = client.get(
            "/v1/system/metrics"
        )
        assert metrics.status_code == 200
        assert secret_session_marker not in metrics.text
        assert (
            'route="/v1/sessions/{session_id}"'
            in metrics.text
        )

        snapshot = client.get(
            "/v1/system/operations"
        )
        assert snapshot.status_code == 200
        assert secret_session_marker not in snapshot.text
        http = snapshot.json()["http"]
        assert any(
            item["route"]
            == "/v1/sessions/{session_id}"
            for item in http["series"]
        )
