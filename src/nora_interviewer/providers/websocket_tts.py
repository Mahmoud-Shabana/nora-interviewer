from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from .streaming_tts import (
    StreamingTtsSession,
    StreamingTtsUnavailableError,
    TtsAudioChunk,
    TtsAudioConfig,
)


class StreamingTtsProtocolError(RuntimeError):
    pass


ConnectFactory = Callable[..., Awaitable[Any]]


class JsonWebSocketTtsSession:
    def __init__(
        self,
        connection: Any,
        *,
        generation: int,
    ) -> None:
        self.connection = connection
        self.generation = generation
        self._closed = False
        self._send_lock = asyncio.Lock()

    async def chunks(
        self,
    ) -> AsyncIterator[TtsAudioChunk]:
        sequence = 0
        try:
            async for message in self.connection:
                if isinstance(message, bytes):
                    if not message:
                        continue
                    yield TtsAudioChunk(
                        sequence=sequence,
                        generation=self.generation,
                        audio=message,
                    )
                    sequence += 1
                    continue

                try:
                    payload = json.loads(message)
                except json.JSONDecodeError as exc:
                    raise StreamingTtsProtocolError(
                        "TTS provider sent invalid JSON"
                    ) from exc

                if not isinstance(payload, dict):
                    raise StreamingTtsProtocolError(
                        "TTS provider event must be a JSON object"
                    )

                event_type = payload.get("type")
                if event_type in {
                    "keepalive",
                    "metadata",
                }:
                    continue
                if event_type in {
                    "done",
                    "closed",
                }:
                    return
                if event_type == "error":
                    raise StreamingTtsProtocolError(
                        str(
                            payload.get(
                                "message",
                                "TTS provider returned an error",
                            )
                        )
                    )
                raise StreamingTtsProtocolError(
                    f"unsupported TTS provider event: {event_type!r}"
                )
        finally:
            self._closed = True

    async def cancel(self) -> None:
        if self._closed:
            return
        try:
            await self._send_control(
                {
                    "type": "cancel",
                    "generation": self.generation,
                }
            )
        finally:
            self._closed = True
            await self.connection.close()

    async def close(self) -> None:
        if self._closed:
            return
        try:
            await self._send_control(
                {
                    "type": "close",
                    "generation": self.generation,
                }
            )
        finally:
            self._closed = True
            await self.connection.close()

    async def _send_control(
        self,
        payload: dict[str, Any],
    ) -> None:
        if self._closed:
            raise StreamingTtsProtocolError(
                "cannot send control event after TTS session is closed"
            )
        async with self._send_lock:
            await self.connection.send(
                json.dumps(
                    payload,
                    separators=(",", ":"),
                    ensure_ascii=False,
                )
            )


class JsonWebSocketTtsProvider:
    """Vendor-neutral WebSocket JSON streaming TTS adapter.

    Provider protocol:
    - Nora sends one JSON start frame.
    - Provider acknowledges with a JSON ready event.
    - Provider streams encoded audio as binary WebSocket frames.
    - Provider ends with a JSON done event.
    - Nora can send cancel when a candidate barges in.
    """

    provider_id = "websocket-json"

    def __init__(
        self,
        *,
        url: str,
        token: str | None = None,
        voice: str | None = None,
        open_timeout_seconds: float = 10.0,
        max_message_bytes: int = 2_097_152,
        connect_factory: ConnectFactory | None = None,
    ) -> None:
        if not url.startswith(("wss://", "ws://")):
            raise ValueError(
                "streaming TTS URL must start with wss:// or ws://"
            )
        if open_timeout_seconds <= 0:
            raise ValueError(
                "open_timeout_seconds must be > 0"
            )
        if max_message_bytes < 1024:
            raise ValueError(
                "max_message_bytes must be >= 1024"
            )

        self.url = url
        self.token = token
        self.voice = voice
        self.open_timeout_seconds = open_timeout_seconds
        self.max_message_bytes = max_message_bytes
        self._connect_factory = connect_factory

    async def _connect(self):
        factory = self._connect_factory
        if factory is None:
            try:
                from websockets.asyncio.client import connect
            except ImportError as exc:
                raise StreamingTtsUnavailableError(
                    "websocket-json TTS requires the optional 'voice' dependency"
                ) from exc
            factory = connect

        headers = None
        if self.token:
            headers = {
                "Authorization": f"Bearer {self.token}",
            }

        return await factory(
            self.url,
            additional_headers=headers,
            open_timeout=self.open_timeout_seconds,
            max_size=self.max_message_bytes,
        )

    async def synthesize(
        self,
        *,
        text: str,
        locale: str,
        generation: int,
        config: TtsAudioConfig,
    ) -> StreamingTtsSession:
        clean_text = text.strip()
        if not clean_text:
            raise ValueError("TTS text cannot be empty")

        connection = await self._connect()
        payload = {
            "type": "start",
            "schema": "nora.tts.v1",
            "text": clean_text,
            "locale": locale,
            "generation": generation,
            "audio": {
                "encoding": config.encoding.value,
                "sample_rate_hz": config.sample_rate_hz,
                "channels": config.channels,
            },
        }
        if self.voice:
            payload["voice"] = self.voice

        try:
            await connection.send(
                json.dumps(
                    payload,
                    separators=(",", ":"),
                    ensure_ascii=False,
                )
            )
            raw_ready = await asyncio.wait_for(
                connection.recv(),
                timeout=self.open_timeout_seconds,
            )
            if isinstance(raw_ready, bytes):
                raise StreamingTtsProtocolError(
                    "TTS provider ready frame must be JSON text"
                )
            try:
                ready = json.loads(raw_ready)
            except json.JSONDecodeError as exc:
                raise StreamingTtsProtocolError(
                    "TTS provider returned invalid ready JSON"
                ) from exc
            if (
                not isinstance(ready, dict)
                or ready.get("type") != "ready"
            ):
                raise StreamingTtsProtocolError(
                    "TTS provider did not acknowledge start with type=ready"
                )
        except Exception:
            await connection.close()
            raise

        return JsonWebSocketTtsSession(
            connection,
            generation=generation,
        )