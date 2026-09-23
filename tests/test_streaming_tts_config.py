import pytest

from nora_interviewer.config import (
    build_streaming_tts_provider,
)
from nora_interviewer.providers.streaming_tts import (
    DisabledStreamingTtsProvider,
)
from nora_interviewer.providers.websocket_tts import (
    JsonWebSocketTtsProvider,
)


def clear_tts_env(monkeypatch):
    for key in (
        "NORA_STREAMING_TTS_MODE",
        "NORA_STREAMING_TTS_URL",
        "NORA_STREAMING_TTS_TOKEN",
        "NORA_STREAMING_TTS_VOICE",
        "NORA_STREAMING_TTS_OPEN_TIMEOUT_SECONDS",
        "NORA_STREAMING_TTS_MAX_MESSAGE_BYTES",
        "NORA_STREAMING_TTS_ALLOW_INSECURE",
    ):
        monkeypatch.delenv(key, raising=False)


def test_streaming_tts_is_disabled_by_default(monkeypatch):
    clear_tts_env(monkeypatch)
    provider = build_streaming_tts_provider()
    assert isinstance(
        provider,
        DisabledStreamingTtsProvider,
    )


def test_websocket_json_tts_config(monkeypatch):
    clear_tts_env(monkeypatch)
    monkeypatch.setenv(
        "NORA_STREAMING_TTS_MODE",
        "websocket-json",
    )
    monkeypatch.setenv(
        "NORA_STREAMING_TTS_URL",
        "wss://tts.example/stream",
    )
    monkeypatch.setenv(
        "NORA_STREAMING_TTS_TOKEN",
        "token",
    )
    monkeypatch.setenv(
        "NORA_STREAMING_TTS_VOICE",
        "nora-neutral",
    )

    provider = build_streaming_tts_provider()

    assert isinstance(
        provider,
        JsonWebSocketTtsProvider,
    )
    assert provider.url == "wss://tts.example/stream"
    assert provider.token == "token"
    assert provider.voice == "nora-neutral"


def test_websocket_json_tts_requires_tls_by_default(monkeypatch):
    clear_tts_env(monkeypatch)
    monkeypatch.setenv(
        "NORA_STREAMING_TTS_MODE",
        "websocket-json",
    )
    monkeypatch.setenv(
        "NORA_STREAMING_TTS_URL",
        "ws://127.0.0.1:9100/stream",
    )

    with pytest.raises(
        RuntimeError,
        match="must use wss://",
    ):
        build_streaming_tts_provider()


def test_websocket_json_tts_allows_explicit_dev_ws(monkeypatch):
    clear_tts_env(monkeypatch)
    monkeypatch.setenv(
        "NORA_STREAMING_TTS_MODE",
        "websocket-json",
    )
    monkeypatch.setenv(
        "NORA_STREAMING_TTS_URL",
        "ws://127.0.0.1:9100/stream",
    )
    monkeypatch.setenv(
        "NORA_STREAMING_TTS_ALLOW_INSECURE",
        "true",
    )

    provider = build_streaming_tts_provider()
    assert provider.url.startswith("ws://")
