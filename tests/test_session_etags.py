from uuid import uuid4

from fastapi.testclient import TestClient

from nora_interviewer.api import app


def _create_session(client: TestClient) -> str:
    job_id = f"etag-job-{uuid4()}"
    job = client.post(
        "/v1/jobs",
        json={
            "id": job_id,
            "title": "Backend Engineer",
            "description": "Build reliable backend systems.",
            "competencies": [
                {
                    "id": "debugging",
                    "description": "Production debugging",
                    "anchor_question": "Describe a production incident.",
                }
            ],
        },
    )
    assert job.status_code == 201

    session = client.post(
        "/v1/sessions",
        json={
            "job_id": job_id,
            "candidate_ref": f"candidate-{uuid4()}",
            "locale": "en",
            "consent_to_ai_interview": True,
            "consent_to_transcript": True,
        },
    )
    assert session.status_code == 201
    return session.json()["id"]


def test_session_get_returns_strong_etag_and_version_header():
    client = TestClient(app)
    session_id = _create_session(client)

    response = client.get(f"/v1/sessions/{session_id}")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-nora-session-version"] == "1"
    assert response.headers["etag"] == (
        f'"nora-session-{session_id}-v1"'
    )
    assert response.json()["version"] == 1


def test_stale_if_match_is_rejected_after_session_changes():
    client = TestClient(app)
    session_id = _create_session(client)

    initial = client.get(f"/v1/sessions/{session_id}")
    stale_etag = initial.headers["etag"]

    started = client.post(
        f"/v1/sessions/{session_id}/start",
        headers={"If-Match": stale_etag},
    )
    assert started.status_code == 200

    current = client.get(f"/v1/sessions/{session_id}")
    current_etag = current.headers["etag"]
    assert current_etag != stale_etag
    assert current.json()["version"] > initial.json()["version"]

    stale_write = client.post(
        f"/v1/sessions/{session_id}/responses",
        headers={"If-Match": stale_etag},
        json={"text": "I reproduced the issue and compared traces."},
    )
    assert stale_write.status_code == 412
    detail = stale_write.json()["detail"]
    assert detail["current_etag"] == current_etag
    assert detail["current_version"] == current.json()["version"]

    accepted = client.post(
        f"/v1/sessions/{session_id}/responses",
        headers={"If-Match": current_etag},
        json={
            "text": (
                "I reproduced the issue under the same load, compared traces "
                "and metrics, and changed one variable at a time."
            )
        },
    )
    assert accepted.status_code == 200


def test_if_match_remains_optional_for_backward_compatibility():
    client = TestClient(app)
    session_id = _create_session(client)

    response = client.post(
        f"/v1/sessions/{session_id}/start",
    )
    assert response.status_code == 200
