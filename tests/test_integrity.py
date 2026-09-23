from fastapi.testclient import TestClient

from nora_interviewer.api import app


def test_integrity_signal_never_becomes_automatic_rejection():
    client = TestClient(app)
    client.post("/v1/jobs", json={
        "id": "integrity-job",
        "title": "Analyst",
        "description": "Analyze evidence",
        "competencies": [{"id": "analysis", "description": "analysis"}]
    })
    session = client.post("/v1/sessions", json={
        "job_id": "integrity-job",
        "candidate_ref": "candidate",
        "locale": "en",
        "consent_to_ai_interview": True,
        "consent_to_transcript": True,
        "integrity_level": "passive_signals"
    }).json()

    signal = client.post(
        f"/v1/sessions/{session['id']}/integrity-signals",
        json={
            "kind": "possible_external_assistance",
            "confidence": 0.67,
            "note": "Timing pattern warrants review; it is not proof of misconduct.",
            "evidence": {"answer_gap_ms": 120}
        }
    )
    assert signal.status_code == 201
    payload = signal.json()
    assert payload["requires_human_review"] is True
    assert "rejected" not in payload
    assert payload["confidence"] == 0.67
