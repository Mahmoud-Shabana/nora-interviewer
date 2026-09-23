from fastapi.testclient import TestClient

import nora_interviewer.api as api
from nora_interviewer.authn import DevHeaderPrincipalResolver


RECRUITER = {
    "X-Nora-Principal": "recruiter-1",
    "X-Nora-Role": "recruiter",
}
REVIEWER = {
    "X-Nora-Principal": "reviewer-1",
    "X-Nora-Role": "reviewer",
}


def candidate_headers(candidate_ref: str):
    return {
        "X-Nora-Principal": f"user-{candidate_ref}",
        "X-Nora-Role": "candidate",
        "X-Nora-Candidate-Ref": candidate_ref,
    }


def test_dev_auth_separates_recruiter_candidate_and_reviewer_routes(monkeypatch):
    monkeypatch.setattr(
        api,
        "principal_resolver",
        DevHeaderPrincipalResolver(),
    )
    client = TestClient(api.app)

    denied_job = client.post(
        "/v1/jobs",
        headers=candidate_headers("candidate-a"),
        json={
            "id": "authz-denied-job",
            "title": "Engineer",
            "description": "Build reliable systems",
            "competencies": [
                {
                    "id": "debugging",
                    "description": "production debugging",
                }
            ],
        },
    )
    assert denied_job.status_code == 403

    job = client.post(
        "/v1/jobs",
        headers=RECRUITER,
        json={
            "id": "authz-job",
            "title": "Engineer",
            "description": "Build reliable systems",
            "competencies": [
                {
                    "id": "debugging",
                    "description": "production debugging",
                    "anchor_question": "Describe a production incident.",
                }
            ],
        },
    )
    assert job.status_code == 201

    session = client.post(
        "/v1/sessions",
        headers=RECRUITER,
        json={
            "job_id": "authz-job",
            "candidate_ref": "candidate-a",
            "locale": "en",
            "consent_to_ai_interview": True,
            "consent_to_transcript": True,
            "integrity_level": "none",
        },
    )
    assert session.status_code == 201
    session_id = session.json()["id"]

    own = client.get(
        f"/v1/sessions/{session_id}",
        headers=candidate_headers("candidate-a"),
    )
    assert own.status_code == 200

    other = client.get(
        f"/v1/sessions/{session_id}",
        headers=candidate_headers("candidate-b"),
    )
    assert other.status_code == 403

    reviewer_start = client.post(
        f"/v1/sessions/{session_id}/start",
        headers=REVIEWER,
    )
    assert reviewer_start.status_code == 403

    candidate_start = client.post(
        f"/v1/sessions/{session_id}/start",
        headers=candidate_headers("candidate-a"),
    )
    assert candidate_start.status_code == 200

    recruiter_answer = client.post(
        f"/v1/sessions/{session_id}/responses",
        headers=RECRUITER,
        json={"text": "This should not be accepted as candidate input."},
    )
    assert recruiter_answer.status_code == 403

    candidate_events = client.get(
        f"/v1/sessions/{session_id}/events",
        headers=candidate_headers("candidate-a"),
    )
    assert candidate_events.status_code == 403

    reviewer_events = client.get(
        f"/v1/sessions/{session_id}/events",
        headers=REVIEWER,
    )
    assert reviewer_events.status_code == 200


def test_candidate_voice_access_is_bound_to_candidate_ref(monkeypatch):
    monkeypatch.setattr(
        api,
        "principal_resolver",
        DevHeaderPrincipalResolver(),
    )
    client = TestClient(api.app)

    client.post(
        "/v1/jobs",
        headers=RECRUITER,
        json={
            "id": "voice-authz-job",
            "title": "Engineer",
            "description": "Build reliable systems",
            "competencies": [
                {
                    "id": "systems",
                    "description": "systems reasoning",
                }
            ],
        },
    )
    session = client.post(
        "/v1/sessions",
        headers=RECRUITER,
        json={
            "job_id": "voice-authz-job",
            "candidate_ref": "voice-candidate",
            "locale": "en",
            "consent_to_ai_interview": True,
            "consent_to_transcript": True,
            "integrity_level": "none",
        },
    )
    session_id = session.json()["id"]

    allowed = client.get(
        f"/v1/sessions/{session_id}/voice",
        headers=candidate_headers("voice-candidate"),
    )
    assert allowed.status_code == 200

    denied = client.get(
        f"/v1/sessions/{session_id}/voice",
        headers=candidate_headers("someone-else"),
    )
    assert denied.status_code == 403
