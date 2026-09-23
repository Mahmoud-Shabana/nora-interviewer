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
