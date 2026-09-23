from uuid import uuid4

from fastapi.testclient import TestClient

from nora_interviewer.api import app


def test_cancel_endpoint_honors_etag_and_returns_terminal_session():
    client = TestClient(app)
    job_id = f"cancel-api-job-{uuid4()}"

    assert client.post(
        "/v1/jobs",
        json={
            "id": job_id,
            "title": "Engineer",
            "description": "Build reliable systems.",
            "competencies": [
                {
                    "id": "x",
                    "description": "systems",
                    "anchor_question": "Describe a system you built.",
                }
            ],
        },
    ).status_code == 201

    created = client.post(
        "/v1/sessions",
        json={
            "job_id": job_id,
            "candidate_ref": f"candidate-{uuid4()}",
            "locale": "en",
            "consent_to_ai_interview": True,
            "consent_to_transcript": True,
        },
    )
    assert created.status_code == 201
    session_id = created.json()["id"]

    current = client.get(f"/v1/sessions/{session_id}")
    etag = current.headers["etag"]

    cancelled = client.post(
        f"/v1/sessions/{session_id}/cancel",
        headers={"If-Match": etag},
        json={"reason": "Candidate requested cancellation."},
    )
    assert cancelled.status_code == 200
    body = cancelled.json()
    assert body["status"] == "cancelled"
    assert body["cancellation_reason"] == "Candidate requested cancellation."
    assert body["cancelled_at"] is not None
    assert body["version"] > current.json()["version"]

    stale = client.post(
        f"/v1/sessions/{session_id}/cancel",
        headers={"If-Match": etag},
        json={"reason": "Stale retry."},
    )
    assert stale.status_code == 412
