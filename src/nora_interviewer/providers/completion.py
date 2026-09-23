from __future__ import annotations

from typing import Protocol

import httpx


class CompletionProvider(Protocol):
    async def complete(self, *, system_prompt: str, user_prompt: str) -> str: ...


class OpenAICompatibleChatProvider:
    """Small adapter for servers exposing an OpenAI-compatible chat completions API."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    async def complete(self, *, system_prompt: str, user_prompt: str) -> str:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "model": self.model,
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

        try:
            result = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("Completion provider returned an unsupported response shape") from exc
        if not isinstance(result, str) or not result.strip():
            raise RuntimeError("Completion provider returned an empty response")
        return result
