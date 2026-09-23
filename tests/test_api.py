from fastapi.testclient import TestClient

from nora_interviewer.api import app


def test_api_happy_path():
    client = TestClient(app)
    job = client.post("/v1/jobs", json={
        "id": "api-job",
        "title": "ML Engineer",
        "description": "Build and evaluate ML systems",
        "competencies": [{"id": "ml", "description": "ML evaluation"}],
        "max_questions": 4
    })
    assert job.status_code == 201

    session = client.post("/v1/sessions", json={
        "job_id": "api-job",
        "candidate_ref": "anon-42",
        "locale": "en",
        "consent_to_ai_interview": True,
        "consent_to_transcript": True
    })
    assert session.status_code == 201
    sid = session.json()["id"]

    start = client.post(f"/v1/sessions/{sid}/start")
    assert start.status_code == 200
    assert start.json()["interviewer_turn"]["speaker"] == "interviewer"

    exported = client.get(f"/v1/sessions/{sid}/voxrubric")
    assert exported.status_code == 200
    assert exported.json()["session_id"] == sid


def test_session_requires_consent():
    client = TestClient(app)
    client.post("/v1/jobs", json={
        "id": "consent-job",
        "title": "Analyst",
        "description": "Analyze systems",
        "competencies": [{"id": "analysis", "description": "structured analysis"}]
    })
    response = client.post("/v1/sessions", json={
        "job_id": "consent-job",
        "candidate_ref": "anon",
        "locale": "en",
        "consent_to_ai_interview": False,
        "consent_to_transcript": True
    })
    assert response.status_code == 400
