from __future__ import annotations

import os

from .providers.completion import OpenAICompatibleChatProvider
from .providers.fallback import FallbackBrain
from .providers.llm_brain import LLMInterviewBrain
from .providers.rule_based import RuleBasedBrain


def build_brain():
    mode = os.getenv("NORA_BRAIN_MODE", "rule").strip().lower()
    fallback = RuleBasedBrain()

    if mode == "rule":
        return fallback

    if mode == "openai-compatible":
        base_url = os.getenv("NORA_LLM_BASE_URL", "").strip()
        model = os.getenv("NORA_LLM_MODEL", "").strip()
        api_key = os.getenv("NORA_LLM_API_KEY")
        if not base_url or not model:
            raise RuntimeError(
                "NORA_LLM_BASE_URL and NORA_LLM_MODEL are required for openai-compatible mode"
            )
        primary = LLMInterviewBrain(
            OpenAICompatibleChatProvider(
                base_url=base_url,
                model=model,
                api_key=api_key,
            )
        )
        return FallbackBrain(primary=primary, fallback=fallback)

    raise RuntimeError(f"Unsupported NORA_BRAIN_MODE: {mode}")
