from fastapi.testclient import TestClient

from nora_interviewer.api import app


def _session(client: TestClient):
    job = client.post("/v1/jobs", json={
        "id": "rights-job",
        "title": "Engineer",
        "description": "Build systems",
        "competencies": [{
            "id": "debugging",
            "description": "debugging",
            "anchor_question": "Describe a production incident you debugged."
        }],
        "max_questions": 4,
        "anchor_ratio": 0.5
    })
    assert job.status_code == 201
    session = client.post("/v1/sessions", json={
        "job_id": "rights-job",
        "candidate_ref": "candidate",
        "locale": "en",
        "consent_to_ai_interview": True,
        "consent_to_transcript": True,
        "integrity_level": "none"
    })
    assert session.status_code == 201
    return session.json()["id"]


def test_candidate_can_correct_own_transcript_and_appeal():
    client = TestClient(app)
    sid = _session(client)
    client.post(f"/v1/sessions/{sid}/start")
    client.post(f"/v1/sessions/{sid}/responses", json={"text": "I debugged a cache stampede."})

    session = client.get(f"/v1/sessions/{sid}").json()
    candidate_turn = next(t for t in session["turns"] if t["speaker"] == "candidate")

    revision = client.post(f"/v1/sessions/{sid}/corrections", json={
        "turn_id": candidate_turn["id"],
        "corrected_text": "I debugged a cache stampede in production.",
        "reason": "Speech recognition omitted the last words."
    })
    assert revision.status_code == 201
    assert revision.json()["original_text"] == "I debugged a cache stampede."

    appeal = client.post(f"/v1/sessions/{sid}/appeals", json={
        "message": "Please review this answer using the corrected transcript.",
        "turn_ids": [candidate_turn["id"]]
    })
    assert appeal.status_code == 201
    assert appeal.json()["status"] == "pending"

    events = client.get(f"/v1/sessions/{sid}/events").json()
    types = [event["type"] for event in events]
    assert "transcript_corrected" in types
    assert "appeal_submitted" in types

    replay = client.get(f"/v1/sessions/{sid}/replay")
    assert replay.status_code == 200
    assert candidate_turn["id"] in replay.json()["corrected_turn_ids"]
