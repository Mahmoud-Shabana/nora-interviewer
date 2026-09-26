from __future__ import annotations

import asyncio
from typing import Protocol

import httpx

from ..resilience import (
    CircuitBreaker,
    ProviderCircuitOpenError,
    ProviderResilienceSnapshot,
    retryable_http_status,
)


class CompletionProvider(Protocol):
    async def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
    ) -> str: ...


class OpenAICompatibleChatProvider:
    """OpenAI-compatible provider with bounded retry and circuit protection."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str | None = None,
        timeout_seconds: float = 30.0,
        max_attempts: int = 2,
        retry_base_seconds: float = 0.25,
        failure_threshold: int = 3,
        cooldown_seconds: float = 20.0,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError(
                "timeout_seconds must be positive"
            )
        if not 1 <= max_attempts <= 5:
            raise ValueError(
                "max_attempts must be between 1 and 5"
            )
        if (
            retry_base_seconds < 0
            or retry_base_seconds > 5
        ):
            raise ValueError(
                "retry_base_seconds must be between 0 and 5"
            )

        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max_attempts
        self.retry_base_seconds = (
            retry_base_seconds
        )
        self.provider_id = (
            f"openai-compatible:{model}"
        )
        self.circuit = CircuitBreaker(
            provider_id=self.provider_id,
            failure_threshold=failure_threshold,
            cooldown_seconds=cooldown_seconds,
        )

    def resilience_snapshot(
        self,
    ) -> ProviderResilienceSnapshot:
        return self.circuit.snapshot()

    async def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        headers = {
            "Content-Type": "application/json"
        }
        if self.api_key:
            headers[
                "Authorization"
            ] = f"Bearer {self.api_key}"

        payload = {
            "model": self.model,
            "temperature": 0.2,
            "messages": [
                {
                    "role": "system",
                    "content": system_prompt,
                },
                {
                    "role": "user",
                    "content": user_prompt,
                },
            ],
        }

        last_error: Exception | None = None

        for attempt in range(
            1,
            self.max_attempts + 1,
        ):
            self.circuit.before_call()

            try:
                async with httpx.AsyncClient(
                    timeout=self.timeout_seconds
                ) as client:
                    response = await client.post(
                        (
                            f"{self.base_url}"
                            "/chat/completions"
                        ),
                        headers=headers,
                        json=payload,
                    )
            except ProviderCircuitOpenError:
                raise
            except (
                httpx.TimeoutException,
                httpx.RequestError,
            ) as exc:
                self.circuit.record_failure()
                last_error = exc
                if attempt >= self.max_attempts:
                    raise
                await asyncio.sleep(
                    self.retry_base_seconds
                    * (2 ** (attempt - 1))
                )
                continue

            if (
                response.status_code < 200
                or response.status_code >= 300
            ):
                error = httpx.HTTPStatusError(
                    (
                        "Completion provider returned "
                        f"HTTP {response.status_code}"
                    ),
                    request=response.request,
                    response=response,
                )
                self.circuit.record_failure()
                last_error = error
                if (
                    not retryable_http_status(
                        response.status_code
                    )
                    or attempt
                    >= self.max_attempts
                ):
                    raise error
                await asyncio.sleep(
                    self.retry_base_seconds
                    * (2 ** (attempt - 1))
                )
                continue

            try:
                data = response.json()
                result = (
                    data["choices"][0]
                    ["message"]["content"]
                )
            except (
                KeyError,
                IndexError,
                TypeError,
                ValueError,
            ) as exc:
                self.circuit.record_failure()
                raise RuntimeError(
                    "Completion provider returned an "
                    "unsupported response shape"
                ) from exc

            if (
                not isinstance(result, str)
                or not result.strip()
            ):
                self.circuit.record_failure()
                raise RuntimeError(
                    "Completion provider returned an "
                    "empty response"
                )

            self.circuit.record_success()
            return result

        assert last_error is not None
        raise last_error
