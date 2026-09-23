from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from ..voice_stream import (
    AudioStreamConfig,
    SpeechRecognitionEvent,
    StreamingSpeechSession,
)
from .streaming_speech import StreamingSpeechUnavailableError


class StreamingSpeechProtocolError(RuntimeError):
    pass


ConnectFactory = Callable[..., Awaitable[Any]]


class JsonWebSocketSpeechSession:
    """One provider-side streaming transcription session."""

    def __init__(
        self,
        connection: Any,
    ) -> None:
        self.connection = connection
        self._send_lock = asyncio.Lock()
        self._closed = False

    async def push_audio(
        self,
        audio: bytes,
    ) -> None:
        if self._closed:
            raise StreamingSpeechProtocolError(
                "cannot push audio after STT session is closed"
            )
        if not audio:
            return
        async with self._send_lock:
            await self.connection.send(audio)

    async def events(
        self,
    ) -> AsyncIterator[SpeechRecognitionEvent]:
        try:
            async for message in self.connection:
                if isinstance(message, bytes):
                    raise StreamingSpeechProtocolError(
                        "STT provider sent unexpected binary response"
                    )

                try:
                    payload = json.loads(message)
                except json.JSONDecodeError as exc:
                    raise StreamingSpeechProtocolError(
                        "STT provider sent invalid JSON"
                    ) from exc

                if not isinstance(payload, dict):
                    raise StreamingSpeechProtocolError(
                        "STT provider event must be a JSON object"
                    )

                event_type = payload.get("type")
                if event_type == "partial":
                    yield SpeechRecognitionEvent(
                        text=str(payload.get("text", "")),
                        is_final=False,
                        confidence=payload.get("confidence"),
                    )
                elif event_type == "final":
                    yield SpeechRecognitionEvent(
                        text=str(payload.get("text", "")),
                        is_final=True,
                        confidence=payload.get("confidence"),
                    )
                elif event_type in {
                    "committed",
                    "keepalive",
                }:
                    continue
                elif event_type == "error":
                    raise StreamingSpeechProtocolError(
                        str(
                            payload.get(
                                "message",
                                "STT provider returned an error",
                            )
                        )
                    )
                elif event_type == "closed":
                    return
                else:
                    raise StreamingSpeechProtocolError(
                        f"unsupported STT provider event: {event_type!r}"
                    )
        finally:
            self._closed = True

    async def commit(self) -> None:
        await self._send_control({"type": "commit"})

    async def close(self) -> None:
        if self._closed:
            return
        try:
            await self._send_control({"type": "close"})
        finally:
            self._closed = True
            await self.connection.close()

    async def cancel(self) -> None:
        if self._closed:
            return
        try:
            await self._send_control({"type": "cancel"})
        finally:
            self._closed = True
            await self.connection.close()

    async def _send_control(
        self,
        payload: dict[str, Any],
    ) -> None:
        if self._closed:
            raise StreamingSpeechProtocolError(
                "cannot send control event after STT session is closed"
            )
        async with self._send_lock:
            await self.connection.send(
                json.dumps(
                    payload,
                    separators=(",", ":"),
                    ensure_ascii=False,
                )
            )


class JsonWebSocketSpeechProvider:
    """Vendor-neutral WebSocket JSON streaming STT adapter.

    Provider protocol:
    - Nora sends a JSON start frame and waits for {"type":"ready"}.
    - Audio is sent as binary WebSocket frames.
    - Nora sends commit / close / cancel JSON control frames.
    - Provider emits partial / final JSON transcript frames.
    """

    provider_id = "websocket-json"

    def __init__(
        self,
        *,
        url: str,
        token: str | None = None,
        open_timeout_seconds: float = 10.0,
        max_message_bytes: int = 1_048_576,
        connect_factory: ConnectFactory | None = None,
    ) -> None:
        if not url.startswith(("wss://", "ws://")):
            raise ValueError(
                "streaming STT URL must start with wss:// or ws://"
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
        self.open_timeout_seconds = open_timeout_seconds
        self.max_message_bytes = max_message_bytes
        self._connect_factory = connect_factory

    async def _connect(self):
        factory = self._connect_factory
        if factory is None:
            try:
                from websockets.asyncio.client import connect
            except ImportError as exc:
                raise StreamingSpeechUnavailableError(
                    "websocket-json STT requires the optional 'voice' dependency"
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

    async def open(
        self,
        *,
        locale: str,
        config: AudioStreamConfig,
    ) -> StreamingSpeechSession:
        connection = await self._connect()
        start_payload = {
            "type": "start",
            "schema": "nora.stt.v1",
            "locale": locale,
            "audio": {
                "encoding": config.encoding.value,
                "sample_rate_hz": config.sample_rate_hz,
                "channels": config.channels,
            },
        }

        try:
            await connection.send(
                json.dumps(
                    start_payload,
                    separators=(",", ":"),
                    ensure_ascii=False,
                )
            )
            raw_ready = await asyncio.wait_for(
                connection.recv(),
                timeout=self.open_timeout_seconds,
            )
            if isinstance(raw_ready, bytes):
                raise StreamingSpeechProtocolError(
                    "STT provider ready frame must be JSON text"
                )
            try:
                ready = json.loads(raw_ready)
            except json.JSONDecodeError as exc:
                raise StreamingSpeechProtocolError(
                    "STT provider returned invalid ready JSON"
                ) from exc
            if (
                not isinstance(ready, dict)
                or ready.get("type") != "ready"
            ):
                raise StreamingSpeechProtocolError(
                    "STT provider did not acknowledge start with type=ready"
                )
        except Exception:
            await connection.close()
            raise

        return JsonWebSocketSpeechSession(
            connection,
        )
