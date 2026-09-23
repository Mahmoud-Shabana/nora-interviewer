from __future__ import annotations

from collections.abc import AsyncIterator

from ..provider_health import ProviderHealthRegistry
from ..voice_stream import (
    AudioStreamConfig,
    SpeechRecognitionEvent,
    StreamingSpeechProvider,
    StreamingSpeechSession,
)
from .streaming_tts import (
    StreamingTtsProvider,
    StreamingTtsSession,
    TtsAudioChunk,
    TtsAudioConfig,
)


class _GuardedSpeechSession:
    def __init__(
        self,
        *,
        inner: StreamingSpeechSession,
        registry: ProviderHealthRegistry,
        key: str,
    ) -> None:
        self.inner = inner
        self.registry = registry
        self.key = key
        self._healthy = False

    async def _mark_healthy(self) -> None:
        if self._healthy:
            return
        self._healthy = True
        await self.registry.record_success(self.key)

    async def push_audio(
        self,
        audio: bytes,
    ) -> None:
        try:
            await self.inner.push_audio(audio)
        except Exception as exc:
            await self.registry.record_failure(
                self.key,
                exc,
            )
            raise

    async def events(
        self,
    ) -> AsyncIterator[SpeechRecognitionEvent]:
        try:
            async for event in self.inner.events():
                await self._mark_healthy()
                yield event
        except Exception as exc:
            await self.registry.record_failure(
                self.key,
                exc,
            )
            raise

    async def commit(self) -> None:
        try:
            await self.inner.commit()
        except Exception as exc:
            await self.registry.record_failure(
                self.key,
                exc,
            )
            raise

    async def close(self) -> None:
        await self.inner.close()

    async def cancel(self) -> None:
        await self.inner.cancel()


class GuardedStreamingSpeechProvider:
    """Circuit-breaker wrapper for streaming STT providers."""

    def __init__(
        self,
        *,
        inner: StreamingSpeechProvider,
        registry: ProviderHealthRegistry,
        key: str = "streaming_stt",
    ) -> None:
        self.inner = inner
        self.registry = registry
        self.key = key
        self.provider_id = getattr(
            inner,
            "provider_id",
            type(inner).__name__,
        )

    async def open(
        self,
        *,
        locale: str,
        config: AudioStreamConfig,
    ) -> StreamingSpeechSession:
        await self.registry.before_call(self.key)
        try:
            session = await self.inner.open(
                locale=locale,
                config=config,
            )
        except Exception as exc:
            await self.registry.record_failure(
                self.key,
                exc,
            )
            raise

        return _GuardedSpeechSession(
            inner=session,
            registry=self.registry,
            key=self.key,
        )


class _GuardedTtsSession:
    def __init__(
        self,
        *,
        inner: StreamingTtsSession,
        registry: ProviderHealthRegistry,
        key: str,
    ) -> None:
        self.inner = inner
        self.registry = registry
        self.key = key
        self._healthy = False

    async def _mark_healthy(self) -> None:
        if self._healthy:
            return
        self._healthy = True
        await self.registry.record_success(self.key)

    async def chunks(
        self,
    ) -> AsyncIterator[TtsAudioChunk]:
        try:
            async for chunk in self.inner.chunks():
                await self._mark_healthy()
                yield chunk
        except Exception as exc:
            await self.registry.record_failure(
                self.key,
                exc,
            )
            raise

    async def cancel(self) -> None:
        await self.inner.cancel()

    async def close(self) -> None:
        await self.inner.close()


class GuardedStreamingTtsProvider:
    """Circuit-breaker wrapper for streaming TTS providers."""

    def __init__(
        self,
        *,
        inner: StreamingTtsProvider,
        registry: ProviderHealthRegistry,
        key: str = "streaming_tts",
    ) -> None:
        self.inner = inner
        self.registry = registry
        self.key = key
        self.provider_id = getattr(
            inner,
            "provider_id",
            type(inner).__name__,
        )

    async def synthesize(
        self,
        *,
        text: str,
        locale: str,
        generation: int,
        config: TtsAudioConfig,
    ) -> StreamingTtsSession:
        await self.registry.before_call(self.key)
        try:
            session = await self.inner.synthesize(
                text=text,
                locale=locale,
                generation=generation,
                config=config,
            )
        except Exception as exc:
            await self.registry.record_failure(
                self.key,
                exc,
            )
            raise

        return _GuardedTtsSession(
            inner=session,
            registry=self.registry,
            key=self.key,
        )
