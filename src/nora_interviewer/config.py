from __future__ import annotations

import os

from .evidence_judge import DisabledEvidenceJudge, LLMEvidenceJudge
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


def build_evidence_judge():
    """Build a judge independently from the interviewer brain.

    Evidence judging is disabled by default. A semantic judge must be configured
    explicitly so production deployments do not accidentally reuse interviewer
    credentials or silently turn model failures into unsupported evidence.
    """

    mode = os.getenv(
        "NORA_EVIDENCE_JUDGE_MODE",
        "disabled",
    ).strip().lower()

    if mode == "disabled":
        return DisabledEvidenceJudge()

    if mode == "openai-compatible":
        base_url = os.getenv(
            "NORA_EVIDENCE_JUDGE_BASE_URL",
            "",
        ).strip()
        model = os.getenv(
            "NORA_EVIDENCE_JUDGE_MODEL",
            "",
        ).strip()
        api_key = os.getenv("NORA_EVIDENCE_JUDGE_API_KEY")
        if not base_url or not model:
            raise RuntimeError(
                "NORA_EVIDENCE_JUDGE_BASE_URL and "
                "NORA_EVIDENCE_JUDGE_MODEL are required when "
                "NORA_EVIDENCE_JUDGE_MODE=openai-compatible"
            )

        provider = OpenAICompatibleChatProvider(
            base_url=base_url,
            model=model,
            api_key=api_key,
        )
        return LLMEvidenceJudge(
            provider,
            judge_id=f"openai-compatible:{model}",
        )

    raise RuntimeError(
        f"Unsupported NORA_EVIDENCE_JUDGE_MODE: {mode}"
    )
