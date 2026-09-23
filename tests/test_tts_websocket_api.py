from uuid import uuid4

from fastapi.testclient import TestClient

import nora_interviewer.api as api
from nora_interviewer.providers.streaming_tts import (
    TtsAudioChunk,
)
from nora_interviewer.voice_output import (
    TtsStreamOpenResult,
    TtsStreamState,
)


class FakeOutputBridge:
    def __init__(self):
        self.open_calls = []
        self.closed = []

    async def open(
        self,
        *,
        session_id,
        turn_id,
        locale,
        config,
    ):
        self.open_calls.append({
            "session_id": session_id,
            "turn_id": turn_id,
            "locale": locale,
            "config": config,
        })
        return TtsStreamOpenResult(
            state=TtsStreamState(
                stream_id="tts-stream",
                session_id=session_id,
                turn_id=turn_id,
                generation=0,
                config=config,
            )
        )

    async def chunks(self, *, stream_id):
        yield TtsAudioChunk(
            sequence=0,
            generation=0,
            audio=b"audio-one",
        )
        yield TtsAudioChunk(
            sequence=1,
            generation=0,
            audio=b"audio-two",
        )

    async def close(
        self,
        *,
        stream_id,
        reason="client_disconnect",
    ):
        self.closed.append(
            (stream_id, reason)
        )

    async def close_all(self):
        return None


def test_tts_websocket_streams_metadata_and_binary_audio(monkeypatch):
    fake = FakeOutputBridge()
    monkeypatch.setattr(
        api,
        "tts_bridge",
        fake,
    )

    client = TestClient(api.app)
    suffix = uuid4().hex[:8]
    job_id = f"tts-api-job-{suffix}"

    job = client.post(
        "/v1/jobs",
        json={
            "id": job_id,
            "title": "Engineer",
            "description": "Build reliable systems",
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
            "job_id": job_id,
            "candidate_ref": f"candidate-{suffix}",
            "consent_to_ai_interview": True,
            "consent_to_transcript": True,
        },
    )
    assert created.status_code == 201
    session_id = created.json()["id"]

    started = client.post(
        f"/v1/sessions/{session_id}/start"
    )
    assert started.status_code == 200
    turn_id = started.json()[
        "interviewer_turn"
    ]["id"]

    with client.websocket_connect(
        f"/v1/ws/tts/{session_id}"
    ) as socket:
        socket.send_json({
            "type": "open",
            "data": {
                "turn_id": turn_id,
                "locale": "en-US",
            },
        })

        opened = socket.receive_json()
        assert opened["type"] == "stream_opened"
        assert (
            opened["data"]["state"]["stream_id"]
            == "tts-stream"
        )

        meta_one = socket.receive_json()
        assert meta_one["type"] == "audio_chunk"
        assert meta_one["data"]["sequence"] == 0
        assert meta_one["data"]["bytes"] == len(
            b"audio-one"
        )
        assert socket.receive_bytes() == b"audio-one"

        meta_two = socket.receive_json()
        assert meta_two["data"]["sequence"] == 1
        assert socket.receive_bytes() == b"audio-two"

        completed = socket.receive_json()
        assert completed["type"] == "stream_completed"
        assert completed["data"]["stream_id"] == "tts-stream"

    assert fake.open_calls[0]["turn_id"] == turn_id
    assert fake.open_calls[0]["locale"] == "en-US"


def test_tts_websocket_supports_client_cancel(monkeypatch):
    fake = FakeOutputBridge()
    monkeypatch.setattr(
        api,
        "tts_bridge",
        fake,
    )

    async def no_chunks(*, stream_id):
        if False:
            yield None

    fake.chunks = no_chunks

    client = TestClient(api.app)
    suffix = uuid4().hex[:8]
    job_id = f"tts-cancel-job-{suffix}"
    assert client.post(
        "/v1/jobs",
        json={
            "id": job_id,
            "title": "Engineer",
            "description": "Build systems",
            "competencies": [
                {
                    "id": "systems",
                    "description": "systems",
                }
            ],
        },
    ).status_code == 201
    created = client.post(
        "/v1/sessions",
        json={
            "job_id": job_id,
            "candidate_ref": f"candidate-{suffix}",
            "consent_to_ai_interview": True,
            "consent_to_transcript": True,
        },
    )
    session_id = created.json()["id"]
    started = client.post(
        f"/v1/sessions/{session_id}/start"
    ).json()
    turn_id = started["interviewer_turn"]["id"]

    with client.websocket_connect(
        f"/v1/ws/tts/{session_id}"
    ) as socket:
        socket.send_json({
            "type": "open",
            "data": {"turn_id": turn_id},
        })
        assert (
            socket.receive_json()["type"]
            == "stream_opened"
        )

        socket.send_json({"type": "cancel"})
        cancelled = socket.receive_json()
        assert cancelled["type"] == "stream_cancelled"

    assert fake.closed == [
        ("tts-stream", "client_cancelled")
    ]
