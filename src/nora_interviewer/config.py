from __future__ import annotations

import os

from .authn import (
    DisabledPrincipalResolver,
    DevHeaderPrincipalResolver,
    JwtJwksPrincipalResolver,
)
from .evidence_ensemble import EvidenceJudgeEnsemble
from .evidence_judge import DisabledEvidenceJudge, LLMEvidenceJudge
from .providers.completion import OpenAICompatibleChatProvider
from .providers.fallback import FallbackBrain
from .providers.llm_brain import LLMInterviewBrain
from .providers.rule_based import RuleBasedBrain
from .rubric_drafting import (
    DisabledRubricDrafter,
    LLMRubricDrafter,
)
from .providers.streaming_speech import DisabledStreamingSpeechProvider
from .providers.streaming_tts import DisabledStreamingTtsProvider
from .providers.websocket_speech import JsonWebSocketSpeechProvider
from .providers.websocket_tts import JsonWebSocketTtsProvider
from .postgres_store import PostgresStore
from .provider_health import ProviderHealthRegistry
from .sqlite_store import SqliteStore
from .storage import InMemoryStore


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

    if mode == "ensemble":
        base_url = os.getenv(
            "NORA_EVIDENCE_JUDGE_BASE_URL",
            "",
        ).strip()
        raw_models = os.getenv(
            "NORA_EVIDENCE_JUDGE_MODELS",
            "",
        )
        api_key = os.getenv("NORA_EVIDENCE_JUDGE_API_KEY")
        raw_threshold = os.getenv(
            "NORA_EVIDENCE_JUDGE_AGREEMENT_THRESHOLD",
            str(2 / 3),
        ).strip()

        models = [
            item.strip()
            for item in raw_models.split(",")
            if item.strip()
        ]
        if not base_url or len(models) < 2:
            raise RuntimeError(
                "NORA_EVIDENCE_JUDGE_BASE_URL and at least two comma-separated "
                "NORA_EVIDENCE_JUDGE_MODELS are required when "
                "NORA_EVIDENCE_JUDGE_MODE=ensemble"
            )
        if len(models) != len(set(models)):
            raise RuntimeError(
                "NORA_EVIDENCE_JUDGE_MODELS must contain unique model ids"
            )
        try:
            threshold = float(raw_threshold)
        except ValueError as exc:
            raise RuntimeError(
                "NORA_EVIDENCE_JUDGE_AGREEMENT_THRESHOLD must be a number"
            ) from exc
        if not 0.5 < threshold <= 1.0:
            raise RuntimeError(
                "NORA_EVIDENCE_JUDGE_AGREEMENT_THRESHOLD must be in (0.5, 1.0]"
            )

        judges = [
            LLMEvidenceJudge(
                OpenAICompatibleChatProvider(
                    base_url=base_url,
                    model=model,
                    api_key=api_key,
                ),
                judge_id=f"openai-compatible:{model}",
            )
            for model in models
        ]
        return EvidenceJudgeEnsemble(
            judges,
            agreement_threshold=threshold,
        )

    raise RuntimeError(
        f"Unsupported NORA_EVIDENCE_JUDGE_MODE: {mode}"
    )


def build_rubric_drafter():
    """Build the optional recruiter-facing rubric drafting assistant."""

    mode = os.getenv(
        "NORA_RUBRIC_DRAFTER_MODE",
        "disabled",
    ).strip().lower()

    if mode == "disabled":
        return DisabledRubricDrafter()

    if mode == "openai-compatible":
        base_url = os.getenv(
            "NORA_RUBRIC_DRAFTER_BASE_URL",
            "",
        ).strip()
        model = os.getenv(
            "NORA_RUBRIC_DRAFTER_MODEL",
            "",
        ).strip()
        api_key = os.getenv(
            "NORA_RUBRIC_DRAFTER_API_KEY"
        )

        if not base_url or not model:
            raise RuntimeError(
                "NORA_RUBRIC_DRAFTER_BASE_URL and "
                "NORA_RUBRIC_DRAFTER_MODEL are required when "
                "NORA_RUBRIC_DRAFTER_MODE=openai-compatible"
            )

        provider = OpenAICompatibleChatProvider(
            base_url=base_url,
            model=model,
            api_key=api_key,
        )
        return LLMRubricDrafter(
            provider,
            drafter_id=f"openai-compatible:{model}",
        )

    raise RuntimeError(
        f"Unsupported NORA_RUBRIC_DRAFTER_MODE: {mode}"
    )


def build_principal_resolver():
    """Build the HTTP principal resolver.

    disabled:
        Backward-compatible local/demo mode. All requests are treated as the
        trusted service principal.

    dev-header:
        Development-only role simulation through X-Nora-* headers.
        Do not use this mode as a production authentication mechanism.
    """

    mode = os.getenv(
        "NORA_AUTH_MODE",
        "disabled",
    ).strip().lower()

    if mode == "disabled":
        return DisabledPrincipalResolver()

    if mode == "dev-header":
        return DevHeaderPrincipalResolver()

    if mode == "jwt-jwks":
        jwks_url = os.getenv(
            "NORA_AUTH_JWKS_URL",
            "",
        ).strip()
        issuer = os.getenv(
            "NORA_AUTH_ISSUER",
            "",
        ).strip()
        audience = os.getenv(
            "NORA_AUTH_AUDIENCE",
            "",
        ).strip()
        algorithms = tuple(
            item.strip()
            for item in os.getenv(
                "NORA_AUTH_ALGORITHMS",
                "RS256",
            ).split(",")
            if item.strip()
        )
        allow_insecure_jwks = os.getenv(
            "NORA_AUTH_ALLOW_INSECURE_JWKS",
            "false",
        ).strip().lower() in {"1", "true", "yes", "on"}
        allow_service_role = os.getenv(
            "NORA_AUTH_ALLOW_SERVICE_ROLE",
            "false",
        ).strip().lower() in {"1", "true", "yes", "on"}

        if not jwks_url or not issuer or not audience:
            raise RuntimeError(
                "NORA_AUTH_JWKS_URL, NORA_AUTH_ISSUER, and "
                "NORA_AUTH_AUDIENCE are required in jwt-jwks mode"
            )
        if (
            not jwks_url.startswith("https://")
            and not allow_insecure_jwks
        ):
            raise RuntimeError(
                "NORA_AUTH_JWKS_URL must use https:// unless "
                "NORA_AUTH_ALLOW_INSECURE_JWKS=true"
            )

        try:
            leeway_seconds = float(
                os.getenv(
                    "NORA_AUTH_LEEWAY_SECONDS",
                    "30",
                )
            )
        except ValueError as exc:
            raise RuntimeError(
                "NORA_AUTH_LEEWAY_SECONDS must be numeric"
            ) from exc
        if leeway_seconds < 0 or leeway_seconds > 300:
            raise RuntimeError(
                "NORA_AUTH_LEEWAY_SECONDS must be between 0 and 300"
            )

        try:
            return JwtJwksPrincipalResolver(
                jwks_url=jwks_url,
                issuer=issuer,
                audience=audience,
                algorithms=algorithms,
                principal_claim=os.getenv(
                    "NORA_AUTH_PRINCIPAL_CLAIM",
                    "sub",
                ).strip() or "sub",
                role_claim=os.getenv(
                    "NORA_AUTH_ROLE_CLAIM",
                    "nora_role",
                ).strip() or "nora_role",
                candidate_ref_claim=os.getenv(
                    "NORA_AUTH_CANDIDATE_REF_CLAIM",
                    "candidate_ref",
                ).strip() or "candidate_ref",
                leeway_seconds=leeway_seconds,
                allow_service_role=allow_service_role,
            )
        except ValueError as exc:
            raise RuntimeError(
                f"Invalid jwt-jwks configuration: {exc}"
            ) from exc

    raise RuntimeError(
        f"Unsupported NORA_AUTH_MODE: {mode}"
    )


def build_streaming_speech_provider():
    """Build the realtime streaming STT provider.

    disabled:
        Explicitly disables production streaming transcription.

    websocket-json:
        Connects to any STT service implementing the versioned
        nora.stt.v1 WebSocket protocol.
    """

    mode = os.getenv(
        "NORA_STREAMING_STT_MODE",
        "disabled",
    ).strip().lower()

    if mode == "disabled":
        return DisabledStreamingSpeechProvider()

    if mode == "websocket-json":
        url = os.getenv(
            "NORA_STREAMING_STT_URL",
            "",
        ).strip()
        token = os.getenv(
            "NORA_STREAMING_STT_TOKEN"
        )
        allow_insecure = os.getenv(
            "NORA_STREAMING_STT_ALLOW_INSECURE",
            "false",
        ).strip().lower() in {"1", "true", "yes", "on"}

        if not url:
            raise RuntimeError(
                "NORA_STREAMING_STT_URL is required in websocket-json mode"
            )
        if (
            url.startswith("ws://")
            and not allow_insecure
        ):
            raise RuntimeError(
                "NORA_STREAMING_STT_URL must use wss:// unless "
                "NORA_STREAMING_STT_ALLOW_INSECURE=true"
            )
        if not url.startswith(("wss://", "ws://")):
            raise RuntimeError(
                "NORA_STREAMING_STT_URL must start with wss:// or ws://"
            )

        try:
            open_timeout_seconds = float(
                os.getenv(
                    "NORA_STREAMING_STT_OPEN_TIMEOUT_SECONDS",
                    "10",
                )
            )
            max_message_bytes = int(
                os.getenv(
                    "NORA_STREAMING_STT_MAX_MESSAGE_BYTES",
                    "1048576",
                )
            )
        except ValueError as exc:
            raise RuntimeError(
                "Streaming STT timeout must be numeric and max message size "
                "must be an integer"
            ) from exc

        try:
            return JsonWebSocketSpeechProvider(
                url=url,
                token=token,
                open_timeout_seconds=open_timeout_seconds,
                max_message_bytes=max_message_bytes,
            )
        except ValueError as exc:
            raise RuntimeError(
                f"Invalid websocket-json STT configuration: {exc}"
            ) from exc

    raise RuntimeError(
        f"Unsupported NORA_STREAMING_STT_MODE: {mode}"
    )

def build_streaming_tts_provider():
    """Build the realtime streaming text-to-speech provider."""

    mode = os.getenv(
        "NORA_STREAMING_TTS_MODE",
        "disabled",
    ).strip().lower()

    if mode == "disabled":
        return DisabledStreamingTtsProvider()

    if mode == "websocket-json":
        url = os.getenv(
            "NORA_STREAMING_TTS_URL",
            "",
        ).strip()
        token = os.getenv(
            "NORA_STREAMING_TTS_TOKEN"
        )
        voice = os.getenv(
            "NORA_STREAMING_TTS_VOICE"
        )
        allow_insecure = os.getenv(
            "NORA_STREAMING_TTS_ALLOW_INSECURE",
            "false",
        ).strip().lower() in {"1", "true", "yes", "on"}

        if not url:
            raise RuntimeError(
                "NORA_STREAMING_TTS_URL is required in websocket-json mode"
            )
        if (
            url.startswith("ws://")
            and not allow_insecure
        ):
            raise RuntimeError(
                "NORA_STREAMING_TTS_URL must use wss:// unless "
                "NORA_STREAMING_TTS_ALLOW_INSECURE=true"
            )
        if not url.startswith(("wss://", "ws://")):
            raise RuntimeError(
                "NORA_STREAMING_TTS_URL must start with wss:// or ws://"
            )

        try:
            open_timeout_seconds = float(
                os.getenv(
                    "NORA_STREAMING_TTS_OPEN_TIMEOUT_SECONDS",
                    "10",
                )
            )
            max_message_bytes = int(
                os.getenv(
                    "NORA_STREAMING_TTS_MAX_MESSAGE_BYTES",
                    "2097152",
                )
            )
        except ValueError as exc:
            raise RuntimeError(
                "Streaming TTS timeout must be numeric and max message size "
                "must be an integer"
            ) from exc

        try:
            return JsonWebSocketTtsProvider(
                url=url,
                token=token,
                voice=voice,
                open_timeout_seconds=open_timeout_seconds,
                max_message_bytes=max_message_bytes,
            )
        except ValueError as exc:
            raise RuntimeError(
                f"Invalid websocket-json TTS configuration: {exc}"
            ) from exc

    raise RuntimeError(
        f"Unsupported NORA_STREAMING_TTS_MODE: {mode}"
    )


def build_voice_provider_health_registry() -> ProviderHealthRegistry:
    try:
        failure_threshold = int(
            os.getenv(
                "NORA_VOICE_PROVIDER_FAILURE_THRESHOLD",
                "3",
            )
        )
        cooldown_seconds = float(
            os.getenv(
                "NORA_VOICE_PROVIDER_COOLDOWN_SECONDS",
                "20",
            )
        )
    except ValueError as exc:
        raise RuntimeError(
            "Voice provider failure threshold must be an integer and "
            "cooldown must be numeric"
        ) from exc

    try:
        return ProviderHealthRegistry(
            failure_threshold=failure_threshold,
            cooldown_seconds=cooldown_seconds,
        )
    except ValueError as exc:
        raise RuntimeError(
            f"Invalid voice provider health configuration: {exc}"
        ) from exc


def build_store():
    """Build the configured Nora persistence backend.

    memory:
        Process-local zero-config mode.

    sqlite:
        Durable local SQLite database for development and single-process
        deployments.

    postgres:
        Async PostgreSQL storage for multi-instance deployments.
    """

    mode = os.getenv(
        "NORA_STORE_MODE",
        "memory",
    ).strip().lower()

    if mode == "memory":
        return InMemoryStore()

    if mode == "sqlite":
        path = os.getenv(
            "NORA_SQLITE_PATH",
            ".nora/nora.db",
        ).strip()
        if not path:
            raise RuntimeError(
                "NORA_SQLITE_PATH cannot be empty in sqlite mode"
            )
        return SqliteStore(path)

    if mode == "postgres":
        dsn = os.getenv(
            "NORA_POSTGRES_DSN",
            "",
        ).strip()
        if not dsn:
            raise RuntimeError(
                "NORA_POSTGRES_DSN is required in postgres mode"
            )

        try:
            min_size = int(
                os.getenv(
                    "NORA_POSTGRES_MIN_SIZE",
                    "1",
                )
            )
            max_size = int(
                os.getenv(
                    "NORA_POSTGRES_MAX_SIZE",
                    "10",
                )
            )
            timeout_seconds = float(
                os.getenv(
                    "NORA_POSTGRES_TIMEOUT_SECONDS",
                    "30",
                )
            )
        except ValueError as exc:
            raise RuntimeError(
                "PostgreSQL pool sizes must be integers and timeout must be numeric"
            ) from exc

        try:
            return PostgresStore(
                dsn,
                min_size=min_size,
                max_size=max_size,
                timeout_seconds=timeout_seconds,
            )
        except ValueError as exc:
            raise RuntimeError(
                f"Invalid postgres storage configuration: {exc}"
            ) from exc

    raise RuntimeError(
        f"Unsupported NORA_STORE_MODE: {mode}"
    )
