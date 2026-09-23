import asyncio
import struct
from uuid import uuid4

from fastapi.testclient import TestClient

import nora_interviewer.api as api
from nora_interviewer.audio_stream_manager import AudioStreamManager
from nora_interviewer.voice_stream import (
    AudioChunkMessage,
    SpeechRecognitionEvent,
)
from nora_interviewer.vad import VadConfig
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


def install_bridge(
    monkeypatch,
    *,
    emit_transcript: bool,
    vad_config: VadConfig | None = None,
):
    manager = AudioStreamManager()
    provider = QueueSpeechProvider(
        emit_transcript=emit_transcript
    )
    bridge = VoiceStreamBridge(
        manager=manager,
        provider=provider,
        voice=api.voice,
        vad_config=vad_config,
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



def test_audio_socket_reconnect_accepts_last_acknowledged_cursor(monkeypatch):
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
                    audio=b"accepted-before-disconnect",
                ).model_dump(mode="json"),
            })

            # Simulate a connection loss before the client processes the ACK.
            # The server has already accepted sequence 0.
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
                    "next_sequence": 0,
                },
            })
            reconnected = second.receive_json()
            assert reconnected["type"] == "stream_reconnected"
            assert reconnected["data"]["next_sequence"] == 1

            # Replaying sequence 0 is harmless and never reaches the provider
            # twice because the transport manager treats it as a duplicate.
            second.send_json({
                "type": "chunk",
                "data": AudioChunkMessage.from_bytes(
                    sequence=0,
                    generation=generation,
                    audio=b"replayed",
                ).model_dump(mode="json"),
            })
            duplicate = second.receive_json()
            assert duplicate["type"] == "chunk_ack"
            assert duplicate["data"]["duplicate"] is True
            assert duplicate["data"]["next_sequence"] == 1

            second.send_json({
                "type": "chunk",
                "data": AudioChunkMessage.from_bytes(
                    sequence=1,
                    generation=generation,
                    audio=b"next-frame",
                ).model_dump(mode="json"),
            })
            next_ack = second.receive_json()
            assert next_ack["type"] == "chunk_ack"
            assert next_ack["data"]["next_sequence"] == 2

            second.send_json({
                "type": "commit",
                "data": {},
            })
            assert second.receive_json()["type"] == "stream_committed"

            # A commit retry after reconnect is safe.
            second.send_json({
                "type": "commit",
                "data": {},
            })
            assert second.receive_json()["type"] == "stream_committed"

            second.send_json({
                "type": "close",
                "data": {"stream_id": stream_id},
            })
            assert second.receive_json()["type"] == "stream_closed"

        assert provider.sessions[0].pushed == 2
        assert provider.sessions[0].committed is True
        assert manager.state(stream_id).next_sequence == 2



def pcm16_frame(
    value: int,
    *,
    samples: int = 160,
) -> bytes:
    return struct.pack(
        "<" + "h" * samples,
        *([value] * samples),
    )


def test_audio_socket_vad_auto_commits_and_discards_late_frames(
    monkeypatch,
):
    _, provider, _ = install_bridge(
        monkeypatch,
        emit_transcript=False,
        vad_config=VadConfig(
            speech_threshold=0.02,
            release_threshold=0.01,
            speech_start_ms=20,
            speech_end_silence_ms=100,
            max_utterance_ms=10_000,
        ),
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
                        "sample_rate_hz": 8000,
                        "channels": 1,
                    },
                },
            })
            opened = socket.receive_json()
            stream_id = opened["data"]["state"]["stream_id"]
            generation = opened["data"]["state"]["generation"]

            frames = [
                pcm16_frame(12_000),
                *[
                    pcm16_frame(0)
                    for _ in range(5)
                ],
            ]

            committed = None
            for sequence, audio in enumerate(frames):
                socket.send_json({
                    "type": "chunk",
                    "data": AudioChunkMessage.from_bytes(
                        sequence=sequence,
                        generation=generation,
                        audio=audio,
                    ).model_dump(mode="json"),
                })
                ack = socket.receive_json()
                assert ack["type"] == "chunk_ack"

                if (
                    ack["data"].get("vad", {})
                    .get("auto_commit_recommended")
                ):
                    committed = socket.receive_json()
                    assert (
                        committed["type"]
                        == "stream_committed"
                    )
                    break

            assert committed is not None
            assert committed["data"]["reason"] == "vad_silence"
            assert provider.sessions[0].committed is True
            pushed_before_late = provider.sessions[0].pushed

            late_sequence = (
                committed["data"]["vad"]
                and ack["data"]["next_sequence"]
            )
            socket.send_json({
                "type": "chunk",
                "data": AudioChunkMessage.from_bytes(
                    sequence=late_sequence,
                    generation=generation,
                    audio=pcm16_frame(8_000),
                ).model_dump(mode="json"),
            })
            late_ack = socket.receive_json()
            assert late_ack["type"] == "chunk_ack"
            assert (
                provider.sessions[0].pushed
                == pushed_before_late
            )

            socket.send_json({
                "type": "close",
                "data": {
                    "stream_id": stream_id,
                },
            })
            assert socket.receive_json()["type"] == "stream_closed"
