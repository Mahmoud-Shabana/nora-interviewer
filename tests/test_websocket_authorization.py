from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import nora_interviewer.api as api
from nora_interviewer.authn import DevHeaderPrincipalResolver


RECRUITER = {
    "X-Nora-Principal": "recruiter-ws",
    "X-Nora-Role": "recruiter",
}


def candidate_headers(candidate_ref: str):
    return {
        "X-Nora-Principal": f"user-{candidate_ref}",
        "X-Nora-Role": "candidate",
        "X-Nora-Candidate-Ref": candidate_ref,
    }


def setup_session(client: TestClient) -> str:
    client.post(
        "/v1/jobs",
        headers=RECRUITER,
        json={
            "id": "ws-authz-job",
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
    response = client.post(
        "/v1/sessions",
        headers=RECRUITER,
        json={
            "job_id": "ws-authz-job",
            "candidate_ref": "candidate-ws",
            "locale": "en",
            "consent_to_ai_interview": True,
            "consent_to_transcript": True,
            "integrity_level": "none",
        },
    )
    return response.json()["id"]


def test_websocket_rejects_wrong_candidate_session(monkeypatch):
    monkeypatch.setattr(
        api,
        "principal_resolver",
        DevHeaderPrincipalResolver(),
    )
    client = TestClient(api.app)
    session_id = setup_session(client)

    try:
        with client.websocket_connect(
            f"/v1/ws/interviews/{session_id}",
            headers=candidate_headers("someone-else"),
        ):
            assert False, "connection should have been denied"
    except WebSocketDisconnect as exc:
        assert exc.code == 1008


def test_websocket_accepts_own_candidate_session(monkeypatch):
    monkeypatch.setattr(
        api,
        "principal_resolver",
        DevHeaderPrincipalResolver(),
    )
    client = TestClient(api.app)
    session_id = setup_session(client)

    with client.websocket_connect(
        f"/v1/ws/interviews/{session_id}",
        headers=candidate_headers("candidate-ws"),
    ) as websocket:
        packet = websocket.receive_json()
        assert packet["type"] == "interviewer_turn"
        assert packet["data"]["speaker"] == "interviewer"
