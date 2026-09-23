import asyncio
import json

import pytest

from nora_interviewer.providers.streaming_tts import (
    TtsAudioConfig,
)
from nora_interviewer.providers.websocket_tts import (
    JsonWebSocketTtsProvider,
    StreamingTtsProtocolError,
)


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


def test_websocket_tts_handshake_and_binary_chunks():
    connection = FakeConnection([
        json.dumps({"type": "ready"}),
        b"chunk-a",
        b"chunk-b",
        json.dumps({"type": "done"}),
    ])
    calls = []

    async def connect_factory(url, **kwargs):
        calls.append((url, kwargs))
        return connection

    async def scenario():
        provider = JsonWebSocketTtsProvider(
            url="wss://tts.example/stream",
            token="secret",
            voice="nora-neutral",
            connect_factory=connect_factory,
        )
        session = await provider.synthesize(
            text="Hello candidate",
            locale="en-US",
            generation=3,
            config=TtsAudioConfig(
                sample_rate_hz=24_000,
                channels=1,
            ),
        )

        start = json.loads(connection.sent[0])
        assert start["type"] == "start"
        assert start["schema"] == "nora.tts.v1"
        assert start["text"] == "Hello candidate"
        assert start["locale"] == "en-US"
        assert start["generation"] == 3
        assert start["voice"] == "nora-neutral"
        assert start["audio"] == {
            "encoding": "pcm16",
            "sample_rate_hz": 24000,
            "channels": 1,
        }

        chunks = [
            chunk
            async for chunk in session.chunks()
        ]
        assert [chunk.audio for chunk in chunks] == [
            b"chunk-a",
            b"chunk-b",
        ]
        assert [chunk.sequence for chunk in chunks] == [
            0,
            1,
        ]
        assert all(
            chunk.generation == 3
            for chunk in chunks
        )

    run(scenario())

    assert calls[0][0] == "wss://tts.example/stream"
    assert calls[0][1]["additional_headers"] == {
        "Authorization": "Bearer secret"
    }


def test_websocket_tts_cancel_sends_generation():
    connection = FakeConnection([
        json.dumps({"type": "ready"}),
    ])

    async def connect_factory(url, **kwargs):
        return connection

    async def scenario():
        session = await JsonWebSocketTtsProvider(
            url="wss://tts.example/stream",
            connect_factory=connect_factory,
        ).synthesize(
            text="Question",
            locale="en",
            generation=7,
            config=TtsAudioConfig(),
        )
        await session.cancel()

    run(scenario())

    assert json.loads(connection.sent[-1]) == {
        "type": "cancel",
        "generation": 7,
    }
    assert connection.closed is True


def test_websocket_tts_rejects_bad_ready_ack():
    connection = FakeConnection([
        json.dumps({"type": "metadata"}),
    ])

    async def connect_factory(url, **kwargs):
        return connection

    async def scenario():
        provider = JsonWebSocketTtsProvider(
            url="wss://tts.example/stream",
            connect_factory=connect_factory,
        )
        with pytest.raises(
            StreamingTtsProtocolError,
            match="type=ready",
        ):
            await provider.synthesize(
                text="Question",
                locale="en",
                generation=0,
                config=TtsAudioConfig(),
            )

    run(scenario())
    assert connection.closed is True


def test_websocket_tts_provider_error_is_explicit():
    connection = FakeConnection([
        json.dumps({"type": "ready"}),
        json.dumps({
            "type": "error",
            "message": "voice unavailable",
        }),
    ])

    async def connect_factory(url, **kwargs):
        return connection

    async def scenario():
        session = await JsonWebSocketTtsProvider(
            url="wss://tts.example/stream",
            connect_factory=connect_factory,
        ).synthesize(
            text="Question",
            locale="en",
            generation=0,
            config=TtsAudioConfig(),
        )

        with pytest.raises(
            StreamingTtsProtocolError,
            match="voice unavailable",
        ):
            async for _ in session.chunks():
                pass

    run(scenario())
