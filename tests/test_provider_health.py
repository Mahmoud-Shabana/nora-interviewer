import asyncio

import pytest

from nora_interviewer.provider_health import (
    ProviderCircuitOpenError,
    ProviderHealthRegistry,
    ProviderHealthState,
)


class FakeClock:
    def __init__(self) -> None:
        self.value = 100.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def run(coro):
    return asyncio.run(coro)


def test_provider_circuit_opens_and_recovers_after_cooldown():
    async def scenario():
        clock = FakeClock()
        registry = ProviderHealthRegistry(
            failure_threshold=2,
            cooldown_seconds=10,
            clock=clock,
        )
        await registry.register(
            key="streaming_stt",
            provider_id="test-stt",
        )

        await registry.record_failure(
            "streaming_stt",
            RuntimeError("first"),
        )
        degraded = await registry.snapshot(
            "streaming_stt"
        )
        assert degraded.state is ProviderHealthState.DEGRADED
        assert degraded.consecutive_failures == 1

        await registry.record_failure(
            "streaming_stt",
            RuntimeError("second"),
        )
        opened = await registry.snapshot(
            "streaming_stt"
        )
        assert opened.state is ProviderHealthState.OPEN
        assert opened.circuit_open_seconds_remaining == 10

        with pytest.raises(ProviderCircuitOpenError):
            await registry.before_call(
                "streaming_stt"
            )

        clock.advance(10.1)
        await registry.before_call(
            "streaming_stt"
        )
        probe = await registry.snapshot(
            "streaming_stt"
        )
        assert probe.state is ProviderHealthState.DEGRADED

        await registry.record_success(
            "streaming_stt"
        )
        healthy = await registry.snapshot(
            "streaming_stt"
        )
        assert healthy.state is ProviderHealthState.HEALTHY
        assert healthy.consecutive_failures == 0
        assert healthy.total_failures == 2
        assert healthy.total_successes == 1

    run(scenario())


def test_disabled_provider_stays_disabled_and_does_not_open_circuit():
    async def scenario():
        registry = ProviderHealthRegistry(
            failure_threshold=1,
            cooldown_seconds=10,
        )
        await registry.register(
            key="streaming_tts",
            provider_id="disabled",
            disabled=True,
        )

        await registry.record_failure(
            "streaming_tts",
            RuntimeError("disabled provider"),
        )
        await registry.before_call(
            "streaming_tts"
        )

        snapshot = await registry.snapshot(
            "streaming_tts"
        )
        assert snapshot.state is ProviderHealthState.DISABLED
        assert snapshot.total_failures == 0
        assert snapshot.consecutive_failures == 0

    run(scenario())


def test_provider_health_rejects_invalid_configuration():
    with pytest.raises(ValueError):
        ProviderHealthRegistry(
            failure_threshold=0,
        )

    with pytest.raises(ValueError):
        ProviderHealthRegistry(
            cooldown_seconds=0,
        )
