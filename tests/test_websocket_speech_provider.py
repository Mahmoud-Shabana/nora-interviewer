import asyncio
import json

import pytest

from nora_interviewer.providers.websocket_speech import (
    JsonWebSocketSpeechProvider,
    StreamingSpeechProtocolError,
)
from nora_interviewer.voice_stream import AudioStreamConfig


def run(coro):
    return asyncio.run(coro)


class FakeConnection:
    def __init__(self, incoming):
        self.incoming = list(incoming)
        self.sent = []
        self.closed = False

    async def send(self, payload):
        self.sent.append(payload)

    async def recv(self):
        if not self.incoming:
            raise RuntimeError("no incoming frames")
        return self.incoming.pop(0)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.incoming:
            raise StopAsyncIteration
        return self.incoming.pop(0)

    async def close(self):
        self.closed = True


def test_websocket_stt_handshake_audio_and_transcript_events():
    connection = FakeConnection([
        json.dumps({"type": "ready"}),
        json.dumps({
            "type": "partial",
            "text": "hello wor",
            "confidence": 0.7,
        }),
        json.dumps({
            "type": "final",
            "text": "hello world",
            "confidence": 0.94,
        }),
        json.dumps({"type": "closed"}),
    ])
    connect_calls = []

    async def connect_factory(url, **kwargs):
        connect_calls.append((url, kwargs))
        return connection

    async def scenario():
        provider = JsonWebSocketSpeechProvider(
            url="wss://stt.example/stream",
            token="secret",
            connect_factory=connect_factory,
        )
        session = await provider.open(
            locale="en-US",
            config=AudioStreamConfig(
                sample_rate_hz=16_000,
                channels=1,
            ),
        )

        start = json.loads(connection.sent[0])
        assert start == {
            "type": "start",
            "schema": "nora.stt.v1",
            "locale": "en-US",
            "audio": {
                "encoding": "pcm16",
                "sample_rate_hz": 16000,
                "channels": 1,
            },
        }

        await session.push_audio(b"\x01\x02\x03")
        await session.commit()

        events = [event async for event in session.events()]
        assert [event.text for event in events] == [
            "hello wor",
            "hello world",
        ]
        assert [event.is_final for event in events] == [
            False,
            True,
        ]
        assert events[-1].confidence == 0.94

        assert connection.sent[1] == b"\x01\x02\x03"
        assert json.loads(connection.sent[2]) == {
            "type": "commit"
        }

    run(scenario())

    assert len(connect_calls) == 1
    url, kwargs = connect_calls[0]
    assert url == "wss://stt.example/stream"
    assert kwargs["additional_headers"] == {
        "Authorization": "Bearer secret"
    }
    assert kwargs["open_timeout"] == 10.0
    assert kwargs["max_size"] == 1_048_576


def test_websocket_stt_rejects_invalid_ready_frame_and_closes_connection():
    connection = FakeConnection([
        json.dumps({"type": "partial", "text": "too early"}),
    ])

    async def connect_factory(url, **kwargs):
        return connection

    async def scenario():
        provider = JsonWebSocketSpeechProvider(
            url="wss://stt.example/stream",
            connect_factory=connect_factory,
        )
        with pytest.raises(
            StreamingSpeechProtocolError,
            match="type=ready",
        ):
            await provider.open(
                locale="en",
                config=AudioStreamConfig(),
            )

    run(scenario())
    assert connection.closed is True


def test_websocket_stt_provider_error_becomes_protocol_error():
    connection = FakeConnection([
        json.dumps({"type": "ready"}),
        json.dumps({
            "type": "error",
            "message": "decoder unavailable",
        }),
    ])

    async def connect_factory(url, **kwargs):
        return connection

    async def scenario():
        session = await JsonWebSocketSpeechProvider(
            url="wss://stt.example/stream",
            connect_factory=connect_factory,
        ).open(
            locale="en",
            config=AudioStreamConfig(),
        )

        with pytest.raises(
            StreamingSpeechProtocolError,
            match="decoder unavailable",
        ):
            async for _ in session.events():
                pass

    run(scenario())


def test_cancel_sends_control_and_closes_connection():
    connection = FakeConnection([
        json.dumps({"type": "ready"}),
    ])

    async def connect_factory(url, **kwargs):
        return connection

    async def scenario():
        session = await JsonWebSocketSpeechProvider(
            url="wss://stt.example/stream",
            connect_factory=connect_factory,
        ).open(
            locale="ar-SA",
            config=AudioStreamConfig(),
        )
        await session.cancel()

    run(scenario())
    assert json.loads(connection.sent[-1]) == {
        "type": "cancel"
    }
    assert connection.closed is True
