import asyncio
from uuid import uuid4

from fastapi.testclient import TestClient

import nora_interviewer.api as api
from nora_interviewer.audio_stream_manager import AudioStreamManager
from nora_interviewer.voice_stream import (
    AudioChunkMessage,
    SpeechRecognitionEvent,
)
from nora_interviewer.voice_stream_bridge import VoiceStreamBridge


class QueueSpeechSession:
    def __init__(self, *, emit_transcript: bool):
        self.emit_transcript = emit_transcript
        self.queue = asyncio.Queue()
        self.closed = False
        self.cancelled = False
        self.committed = False
        self.pushed = 0

    async def push_audio(self, audio: bytes) -> None:
        self.pushed += 1
        if self.emit_transcript and self.pushed == 1:
            await self.queue.put(
                SpeechRecognitionEvent(
                    text="I reproduced the incident",
                    is_final=False,
                    confidence=0.7,
                )
            )
            await self.queue.put(
                SpeechRecognitionEvent(
                    text=(
                        "I reproduced the incident under the same load, "
                        "compared traces and metrics, and changed one variable."
                    ),
                    is_final=True,
                    confidence=0.94,
                )
            )
            await self.queue.put(None)

    async def events(self):
        while True:
            item = await self.queue.get()
            if item is None:
                return
            yield item

    async def commit(self) -> None:
        self.committed = True

    async def close(self) -> None:
        self.closed = True
        await self.queue.put(None)

    async def cancel(self) -> None:
        self.cancelled = True
        await self.queue.put(None)


class QueueSpeechProvider:
    provider_id = "test-queue"

    def __init__(self, *, emit_transcript: bool):
        self.emit_transcript = emit_transcript
        self.sessions = []

    async def open(self, *, locale, config):
        session = QueueSpeechSession(
            emit_transcript=self.emit_transcript
        )
        self.sessions.append(session)
        return session


def setup_session(client: TestClient) -> str:
    suffix = str(uuid4())
    job = client.post(
        "/v1/jobs",
        json={
            "id": f"audio-job-{suffix}",
            "title": "Engineer",
            "description": "Build reliable systems.",
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
    assert client.post(
        f"/v1/sessions/{session_id}/start"
    ).status_code == 200
    return session_id


def install_bridge(monkeypatch, *, emit_transcript: bool):
    manager = AudioStreamManager()
    provider = QueueSpeechProvider(
        emit_transcript=emit_transcript
    )
    bridge = VoiceStreamBridge(
        manager=manager,
        provider=provider,
        voice=api.voice,
    )
    monkeypatch.setattr(
        api,
        "audio_stream_manager",
        manager,
    )
    monkeypatch.setattr(
        api,
        "audio_bridge",
        bridge,
    )
    return manager, provider, bridge


def receive_until(socket, wanted: set[str], limit: int = 10):
    found = {}
    for _ in range(limit):
        message = socket.receive_json()
        found[message["type"]] = message
        if wanted <= set(found):
            return found
    raise AssertionError(
        f"did not receive message types {wanted}; got {set(found)}"
    )


def test_audio_socket_streams_chunks_and_transcripts(monkeypatch):
    install_bridge(
        monkeypatch,
        emit_transcript=True,
    )

    with TestClient(api.app) as client:
        session_id = setup_session(client)

        with client.websocket_connect(
            f"/v1/ws/audio/{session_id}"
        ) as socket:
            socket.send_json({
                "type": "open",
                "data": {
                    "locale": "en",
                    "config": {
                        "encoding": "pcm16",
                        "sample_rate_hz": 16000,
                        "channels": 1,
                        "max_chunk_bytes": 32768,
                        "max_buffered_bytes": 524288,
                    },
                },
            })
            opened = socket.receive_json()
            assert opened["type"] == "stream_opened"
            stream_id = opened["data"]["state"]["stream_id"]
            generation = opened["data"]["state"]["generation"]

            chunk = AudioChunkMessage.from_bytes(
                sequence=0,
                generation=generation,
                audio=b"fake-pcm-frame",
            )
            socket.send_json({
                "type": "chunk",
                "data": chunk.model_dump(mode="json"),
            })

            messages = receive_until(
                socket,
                {
                    "chunk_ack",
                    "transcript_partial",
                    "transcript_final",
                },
            )
            assert messages["chunk_ack"]["data"]["next_sequence"] == 1
            assert (
                messages["transcript_partial"]["data"]["text"]
                == "I reproduced the incident"
            )
            final = messages["transcript_final"]["data"]
            assert final["interviewer_turn"] is not None

            socket.send_json({
                "type": "close",
                "data": {
                    "stream_id": stream_id,
                },
            })
            assert (
                socket.receive_json()["type"]
                == "stream_closed"
            )


def test_audio_socket_can_reconnect_without_replaying_chunks(monkeypatch):
    manager, provider, _ = install_bridge(
        monkeypatch,
        emit_transcript=False,
    )

    with TestClient(api.app) as client:
        session_id = setup_session(client)

        with client.websocket_connect(
            f"/v1/ws/audio/{session_id}"
        ) as first:
            first.send_json({
                "type": "open",
                "data": {"locale": "en"},
            })
            opened = first.receive_json()
            stream_id = opened["data"]["state"]["stream_id"]
            token = opened["data"]["reconnect_token"]
            generation = opened["data"]["state"]["generation"]

            first.send_json({
                "type": "chunk",
                "data": AudioChunkMessage.from_bytes(
                    sequence=0,
                    generation=generation,
                    audio=b"one",
                ).model_dump(mode="json"),
            })
            ack = first.receive_json()
            assert ack["type"] == "chunk_ack"
            assert ack["data"]["next_sequence"] == 1

        with client.websocket_connect(
            f"/v1/ws/audio/{session_id}"
        ) as second:
            second.send_json({
                "type": "reconnect",
                "data": {
                    "stream_id": stream_id,
                    "reconnect_token": token,
                    "generation": generation,
                    "next_sequence": 1,
                },
            })
            reconnect = second.receive_json()
            assert reconnect["type"] == "stream_reconnected"
            assert reconnect["data"]["reconnect_count"] == 1

            second.send_json({
                "type": "chunk",
                "data": AudioChunkMessage.from_bytes(
                    sequence=1,
                    generation=generation,
                    audio=b"two",
                ).model_dump(mode="json"),
            })
            ack = second.receive_json()
            assert ack["type"] == "chunk_ack"
            assert ack["data"]["next_sequence"] == 2

            second.send_json({
                "type": "close",
                "data": {
                    "stream_id": stream_id,
                },
            })
            assert second.receive_json()["type"] == "stream_closed"

        assert provider.sessions[0].pushed == 2
        assert manager.state(stream_id).closed is True



def test_audio_socket_commits_provider_stream(monkeypatch):
    _, provider, _ = install_bridge(
        monkeypatch,
        emit_transcript=False,
    )

    with TestClient(api.app) as client:
        session_id = setup_session(client)

        with client.websocket_connect(
            f"/v1/ws/audio/{session_id}"
        ) as socket:
            socket.send_json({
                "type": "open",
                "data": {"locale": "en"},
            })
            opened = socket.receive_json()
            assert opened["type"] == "stream_opened"
            stream_id = opened["data"]["state"]["stream_id"]

            socket.send_json({
                "type": "commit",
                "data": {},
            })
            committed = socket.receive_json()
            assert committed["type"] == "stream_committed"
            assert committed["data"]["stream_id"] == stream_id
            assert provider.sessions[0].committed is True

            socket.send_json({
                "type": "close",
                "data": {
                    "stream_id": stream_id,
                },
            })
            assert socket.receive_json()["type"] == "stream_closed"
