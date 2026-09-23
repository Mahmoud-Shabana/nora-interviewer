import pytest

from nora_interviewer.config import build_streaming_speech_provider
from nora_interviewer.providers.streaming_speech import (
    DisabledStreamingSpeechProvider,
)
from nora_interviewer.providers.websocket_speech import (
    JsonWebSocketSpeechProvider,
)


def clear_stt_env(monkeypatch):
    for key in (
        "NORA_STREAMING_STT_MODE",
        "NORA_STREAMING_STT_URL",
        "NORA_STREAMING_STT_TOKEN",
        "NORA_STREAMING_STT_OPEN_TIMEOUT_SECONDS",
        "NORA_STREAMING_STT_MAX_MESSAGE_BYTES",
        "NORA_STREAMING_STT_ALLOW_INSECURE",
    ):
        monkeypatch.delenv(key, raising=False)


def test_streaming_stt_is_disabled_by_default(monkeypatch):
    clear_stt_env(monkeypatch)
    provider = build_streaming_speech_provider()
    assert isinstance(
        provider,
        DisabledStreamingSpeechProvider,
    )


def test_websocket_json_stt_config(monkeypatch):
    clear_stt_env(monkeypatch)
    monkeypatch.setenv(
        "NORA_STREAMING_STT_MODE",
        "websocket-json",
    )
    monkeypatch.setenv(
        "NORA_STREAMING_STT_URL",
        "wss://stt.example/stream",
    )
    monkeypatch.setenv(
        "NORA_STREAMING_STT_TOKEN",
        "token",
    )
    monkeypatch.setenv(
        "NORA_STREAMING_STT_OPEN_TIMEOUT_SECONDS",
        "7.5",
    )
    monkeypatch.setenv(
        "NORA_STREAMING_STT_MAX_MESSAGE_BYTES",
        "2097152",
    )

    provider = build_streaming_speech_provider()

    assert isinstance(
        provider,
        JsonWebSocketSpeechProvider,
    )
    assert provider.url == "wss://stt.example/stream"
    assert provider.token == "token"
    assert provider.open_timeout_seconds == 7.5
    assert provider.max_message_bytes == 2_097_152


def test_websocket_json_requires_tls_by_default(monkeypatch):
    clear_stt_env(monkeypatch)
    monkeypatch.setenv(
        "NORA_STREAMING_STT_MODE",
        "websocket-json",
    )
    monkeypatch.setenv(
        "NORA_STREAMING_STT_URL",
        "ws://127.0.0.1:9000/stream",
    )

    with pytest.raises(
        RuntimeError,
        match="must use wss://",
    ):
        build_streaming_speech_provider()


def test_websocket_json_allows_insecure_local_dev_opt_in(monkeypatch):
    clear_stt_env(monkeypatch)
    monkeypatch.setenv(
        "NORA_STREAMING_STT_MODE",
        "websocket-json",
    )
    monkeypatch.setenv(
        "NORA_STREAMING_STT_URL",
        "ws://127.0.0.1:9000/stream",
    )
    monkeypatch.setenv(
        "NORA_STREAMING_STT_ALLOW_INSECURE",
        "true",
    )

    provider = build_streaming_speech_provider()
    assert provider.url.startswith("ws://")


def test_websocket_json_rejects_invalid_numeric_limits(monkeypatch):
    clear_stt_env(monkeypatch)
    monkeypatch.setenv(
        "NORA_STREAMING_STT_MODE",
        "websocket-json",
    )
    monkeypatch.setenv(
        "NORA_STREAMING_STT_URL",
        "wss://stt.example/stream",
    )
    monkeypatch.setenv(
        "NORA_STREAMING_STT_OPEN_TIMEOUT_SECONDS",
        "not-a-number",
    )

    with pytest.raises(
        RuntimeError,
        match="timeout must be numeric",
    ):
        build_streaming_speech_provider()
