import asyncio
from uuid import uuid4

from fastapi.testclient import TestClient

import nora_interviewer.api as api
from nora_interviewer.websocket_metrics import (
    WebSocketMetrics,
    classify_websocket_channel,
)


def run(coro):
    return asyncio.run(coro)


def test_websocket_channel_classification_is_bounded():
    assert (
        classify_websocket_channel(
            "/v1/ws/interviews/private-session"
        )
        == "interview"
    )
    assert (
        classify_websocket_channel(
            "/v1/ws/audio/private-session"
        )
        == "audio"
    )
    assert (
        classify_websocket_channel(
            "/v1/ws/tts/private-session"
        )
        == "tts"
    )
    assert (
        classify_websocket_channel(
            "/anything/private-session"
        )
        == "other"
    )


def test_websocket_metrics_track_active_open_close_and_errors():
    class FakeClock:
        def __init__(self) -> None:
            self.value = 20.0

        def __call__(self) -> float:
            return self.value

    async def scenario():
        clock = FakeClock()
        registry = WebSocketMetrics(
            clock=clock,
        )

        started = await registry.opened(
            "audio"
        )
        snapshot = await registry.snapshot()
        audio = snapshot.channels[0]
        assert audio.channel == "audio"
        assert audio.active == 1
        assert audio.opened_total == 1

        clock.value += 2.5
        await registry.closed(
            "audio",
            started_at=started,
            error=True,
        )

        snapshot = await registry.snapshot()
        audio = snapshot.channels[0]
        assert audio.active == 0
        assert audio.closed_total == 1
        assert audio.errors_total == 1
        assert audio.duration_seconds_sum == 2.5

    run(scenario())


def test_prometheus_websocket_metrics_never_export_session_ids():
    suffix = uuid4().hex
    job_id = f"ws-metrics-job-{suffix}"
    candidate_ref = f"ws-metrics-candidate-{suffix}"

    with TestClient(api.app) as client:
        created_job = client.post(
            "/v1/jobs",
            json={
                "id": job_id,
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
        assert created_job.status_code == 201

        created_session = client.post(
            "/v1/sessions",
            json={
                "job_id": job_id,
                "candidate_ref": candidate_ref,
                "locale": "en",
                "consent_to_ai_interview": True,
                "consent_to_transcript": True,
            },
        )
        assert created_session.status_code == 201
        session_id = created_session.json()["id"]

        with client.websocket_connect(
            f"/v1/ws/interviews/{session_id}"
        ) as socket:
            first = socket.receive_json()
            assert first["type"] == "interviewer_turn"

            live = client.get(
                "/v1/system/metrics"
            )
            assert live.status_code == 200
            assert (
                'nora_websocket_connections_active'
                '{channel="interview"} 1'
                in live.text
            )
            assert session_id not in live.text
            assert candidate_ref not in live.text

        closed = client.get(
            "/v1/system/metrics"
        )
        assert closed.status_code == 200
        assert (
            'nora_websocket_connections_closed_total'
            '{channel="interview"}'
            in closed.text
        )
        assert session_id not in closed.text
        assert candidate_ref not in closed.text
