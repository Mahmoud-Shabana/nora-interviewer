from uuid import uuid4

from fastapi.testclient import TestClient

import nora_interviewer.api as api


def test_interview_websocket_correlation_reaches_audit_events():
    suffix = uuid4().hex

    with TestClient(api.app) as client:
        job = client.post(
            "/v1/jobs",
            json={
                "id": f"correlation-job-{suffix}",
                "title": "Engineer",
                "description": "Build reliable systems.",
                "competencies": [
                    {
                        "id": "debugging",
                        "description": "production debugging",
                        "anchor_question": (
                            "Describe a production incident."
                        ),
                    }
                ],
            },
        )
        assert job.status_code == 201

        created = client.post(
            "/v1/sessions",
            json={
                "job_id": job.json()["id"],
                "candidate_ref": f"candidate-{suffix}",
                "locale": "en",
                "consent_to_ai_interview": True,
                "consent_to_transcript": True,
            },
        )
        assert created.status_code == 201
        session_id = created.json()["id"]

        trace_id = "ws-interview-trace-4242"
        with client.websocket_connect(
            f"/v1/ws/interviews/{session_id}",
            headers={
                "X-Request-ID": trace_id,
            },
        ) as websocket:
            opening = websocket.receive_json()
            assert opening["type"] == "interviewer_turn"

        events = client.get(
            f"/v1/sessions/{session_id}/events"
        )
        assert events.status_code == 200

        traced = [
            event
            for event in events.json()
            if (
                event["type"] in {
                    "interview_started",
                    "interviewer_turn",
                }
                and event["payload"].get(
                    "_trace",
                    {},
                ).get("correlation_id")
                == trace_id
            )
        ]
        assert traced
