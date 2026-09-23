import asyncio

import pytest

from nora_interviewer.provider_health import (
    ProviderCircuitOpenError,
    ProviderHealthRegistry,
    ProviderHealthState,
)
from nora_interviewer.providers.guarded_voice import (
    GuardedStreamingSpeechProvider,
    GuardedStreamingTtsProvider,
)
from nora_interviewer.providers.streaming_tts import (
    TtsAudioChunk,
    TtsAudioConfig,
)
from nora_interviewer.voice_stream import (
    AudioStreamConfig,
    SpeechRecognitionEvent,
)


def run(coro):
    return asyncio.run(coro)


class FailingSpeechSession:
    async def push_audio(self, audio: bytes) -> None:
        return None

    async def events(self):
        raise RuntimeError("stream failed")
        yield

    async def commit(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def cancel(self) -> None:
        return None


class FailingSpeechProvider:
    provider_id = "failing-stt"

    async def open(self, *, locale, config):
        return FailingSpeechSession()


class HealthySpeechSession:
    async def push_audio(self, audio: bytes) -> None:
        return None

    async def events(self):
        yield SpeechRecognitionEvent(
            text="hello",
            is_final=False,
            confidence=0.9,
        )

    async def commit(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def cancel(self) -> None:
        return None


class HealthySpeechProvider:
    provider_id = "healthy-stt"

    async def open(self, *, locale, config):
        return HealthySpeechSession()


class HealthyTtsSession:
    def __init__(self, generation: int) -> None:
        self.generation = generation

    async def chunks(self):
        yield TtsAudioChunk(
            sequence=0,
            generation=self.generation,
            audio=b"\x00\x01",
        )

    async def cancel(self) -> None:
        return None

    async def close(self) -> None:
        return None


class HealthyTtsProvider:
    provider_id = "healthy-tts"

    async def synthesize(
        self,
        *,
        text,
        locale,
        generation,
        config,
    ):
        return HealthyTtsSession(generation)


def test_stream_failure_opens_circuit_even_when_provider_connects():
    async def scenario():
        registry = ProviderHealthRegistry(
            failure_threshold=2,
            cooldown_seconds=30,
        )
        await registry.register(
            key="streaming_stt",
            provider_id="failing-stt",
        )
        provider = GuardedStreamingSpeechProvider(
            inner=FailingSpeechProvider(),
            registry=registry,
        )

        for _ in range(2):
            session = await provider.open(
                locale="en",
                config=AudioStreamConfig(),
            )
            with pytest.raises(RuntimeError, match="stream failed"):
                async for _ in session.events():
                    pass

        snapshot = await registry.snapshot(
            "streaming_stt"
        )
        assert snapshot.state is ProviderHealthState.OPEN
        assert snapshot.consecutive_failures == 2

        with pytest.raises(ProviderCircuitOpenError):
            await provider.open(
                locale="en",
                config=AudioStreamConfig(),
            )

    run(scenario())


def test_first_valid_stt_event_marks_provider_healthy():
    async def scenario():
        registry = ProviderHealthRegistry()
        await registry.register(
            key="streaming_stt",
            provider_id="healthy-stt",
        )
        await registry.record_failure(
            "streaming_stt",
            RuntimeError("previous failure"),
        )

        provider = GuardedStreamingSpeechProvider(
            inner=HealthySpeechProvider(),
            registry=registry,
        )
        session = await provider.open(
            locale="en",
            config=AudioStreamConfig(),
        )
        events = [
            event
            async for event in session.events()
        ]

        assert events[0].text == "hello"
        snapshot = await registry.snapshot(
            "streaming_stt"
        )
        assert snapshot.state is ProviderHealthState.HEALTHY
        assert snapshot.consecutive_failures == 0
        assert snapshot.total_successes == 1

    run(scenario())


def test_first_valid_tts_chunk_marks_provider_healthy():
    async def scenario():
        registry = ProviderHealthRegistry()
        await registry.register(
            key="streaming_tts",
            provider_id="healthy-tts",
        )
        await registry.record_failure(
            "streaming_tts",
            RuntimeError("previous failure"),
        )

        provider = GuardedStreamingTtsProvider(
            inner=HealthyTtsProvider(),
            registry=registry,
        )
        session = await provider.synthesize(
            text="Hello",
            locale="en",
            generation=3,
            config=TtsAudioConfig(),
        )
        chunks = [
            chunk
            async for chunk in session.chunks()
        ]

        assert chunks[0].generation == 3
        snapshot = await registry.snapshot(
            "streaming_tts"
        )
        assert snapshot.state is ProviderHealthState.HEALTHY
        assert snapshot.consecutive_failures == 0
        assert snapshot.total_successes == 1

    run(scenario())
