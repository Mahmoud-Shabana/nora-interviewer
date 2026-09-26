from __future__ import annotations

import base64
import json
import os

from .artifact_service import ArtifactService
from .artifact_storage import (
    DisabledArtifactObjectStore,
    EncryptedLocalArtifactObjectStore,
)
from .authorization import ActorRole
from .authn import (
    DisabledPrincipalResolver,
    DevHeaderPrincipalResolver,
    CompositePrincipalResolver,
    JwtJwksPrincipalResolver,
    OrganizationOidcPrincipalResolver,
    WorkloadJwtPrincipalResolver,
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
from .s3_artifact_storage import S3ArtifactObjectStore
from .slo import OperationalSloPolicy
from .sqlite_store import SqliteStore
from .storage import InMemoryStore
from .vad import VadConfig



def build_artifact_store():
    """Build the configured candidate artifact/audio object store."""

    mode = os.getenv(
        "NORA_ARTIFACT_STORE_MODE",
        "disabled",
    ).strip().lower()

    if mode == "disabled":
        return DisabledArtifactObjectStore()

    if mode == "s3":
        bucket = os.getenv(
            "NORA_ARTIFACT_S3_BUCKET",
            "",
        ).strip()
        prefix = os.getenv(
            "NORA_ARTIFACT_S3_PREFIX",
            "",
        ).strip()
        region = os.getenv(
            "NORA_ARTIFACT_S3_REGION"
        )
        endpoint_url = os.getenv(
            "NORA_ARTIFACT_S3_ENDPOINT_URL"
        )
        sse_mode = os.getenv(
            "NORA_ARTIFACT_S3_SSE_MODE",
            "AES256",
        ).strip()
        kms_key_id = os.getenv(
            "NORA_ARTIFACT_S3_KMS_KEY_ID"
        )

        if not bucket:
            raise RuntimeError(
                "NORA_ARTIFACT_S3_BUCKET is required in s3 artifact mode"
            )
        if (
            endpoint_url
            and endpoint_url.strip().startswith("http://")
            and not os.getenv(
                "NORA_ARTIFACT_S3_ALLOW_INSECURE",
                "false",
            ).strip().lower()
            in {"1", "true", "yes", "on"}
        ):
            raise RuntimeError(
                "NORA_ARTIFACT_S3_ENDPOINT_URL must use https:// unless "
                "NORA_ARTIFACT_S3_ALLOW_INSECURE=true"
            )

        try:
            return S3ArtifactObjectStore(
                bucket=bucket,
                prefix=prefix,
                region=region,
                endpoint_url=endpoint_url,
                sse_mode=sse_mode,
                kms_key_id=kms_key_id,
            )
        except ValueError as exc:
            raise RuntimeError(
                f"Invalid S3 artifact storage configuration: {exc}"
            ) from exc

    if mode == "encrypted-local":
        root = os.getenv(
            "NORA_ARTIFACT_LOCAL_PATH",
            ".nora/artifacts",
        ).strip()
        raw_key = os.getenv(
            "NORA_ARTIFACT_ENCRYPTION_KEY_B64",
            "",
        ).strip()
        key_id = os.getenv(
            "NORA_ARTIFACT_ENCRYPTION_KEY_ID",
            "primary",
        ).strip()

        if not root or not raw_key:
            raise RuntimeError(
                "NORA_ARTIFACT_LOCAL_PATH and "
                "NORA_ARTIFACT_ENCRYPTION_KEY_B64 are required "
                "in encrypted-local artifact mode"
            )

        try:
            padding = "=" * ((-len(raw_key)) % 4)
            encryption_key = base64.urlsafe_b64decode(
                raw_key + padding
            )
        except Exception as exc:
            raise RuntimeError(
                "NORA_ARTIFACT_ENCRYPTION_KEY_B64 must be valid base64"
            ) from exc

        try:
            return EncryptedLocalArtifactObjectStore(
                root,
                encryption_key=encryption_key,
                key_id=key_id,
            )
        except ValueError as exc:
            raise RuntimeError(
                f"Invalid encrypted artifact storage configuration: {exc}"
            ) from exc

    raise RuntimeError(
        f"Unsupported NORA_ARTIFACT_STORE_MODE: {mode}"
    )


def build_artifact_service(
    *,
    store,
    object_store,
) -> ArtifactService:
    if object_store.provider_id == "disabled":
        signing_secret = None
    else:
        raw_secret = os.getenv(
            "NORA_ARTIFACT_SIGNING_SECRET",
            "",
        )
        if len(raw_secret.encode("utf-8")) < 32:
            raise RuntimeError(
                "NORA_ARTIFACT_SIGNING_SECRET must be at least 32 bytes "
                "when artifact storage is enabled"
            )
        signing_secret = raw_secret.encode("utf-8")

    try:
        max_bytes = int(
            os.getenv(
                "NORA_ARTIFACT_MAX_BYTES",
                str(50 * 1024 * 1024),
            )
        )
        access_ttl = int(
            os.getenv(
                "NORA_ARTIFACT_ACCESS_TTL_SECONDS",
                "300",
            )
        )
    except ValueError as exc:
        raise RuntimeError(
            "Artifact size and access TTL settings must be integers"
        ) from exc

    try:
        return ArtifactService(
            store=store,
            object_store=object_store,
            signing_secret=signing_secret,
            max_artifact_bytes=max_bytes,
            access_ttl_seconds=access_ttl,
        )
    except ValueError as exc:
        raise RuntimeError(
            f"Invalid artifact service configuration: {exc}"
        ) from exc

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



def _build_workload_principal_resolver():
    jwks_url = os.getenv(
        "NORA_WORKLOAD_JWKS_URL",
        "",
    ).strip()
    issuer = os.getenv(
        "NORA_WORKLOAD_ISSUER",
        "",
    ).strip()
    audience = os.getenv(
        "NORA_WORKLOAD_AUDIENCE",
        "",
    ).strip()
    algorithms = tuple(
        item.strip()
        for item in os.getenv(
            "NORA_WORKLOAD_ALGORITHMS",
            "RS256",
        ).split(",")
        if item.strip()
    )
    allow_insecure = os.getenv(
        "NORA_WORKLOAD_ALLOW_INSECURE_JWKS",
        "false",
    ).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if not jwks_url or not issuer or not audience:
        raise RuntimeError(
            "NORA_WORKLOAD_JWKS_URL, NORA_WORKLOAD_ISSUER, and "
            "NORA_WORKLOAD_AUDIENCE are required for workload JWT auth"
        )
    if (
        not jwks_url.startswith("https://")
        and not allow_insecure
    ):
        raise RuntimeError(
            "NORA_WORKLOAD_JWKS_URL must use https:// unless "
            "NORA_WORKLOAD_ALLOW_INSECURE_JWKS=true"
        )
    try:
        leeway_seconds = float(
            os.getenv(
                "NORA_WORKLOAD_LEEWAY_SECONDS",
                "30",
            )
        )
    except ValueError as exc:
        raise RuntimeError(
            "NORA_WORKLOAD_LEEWAY_SECONDS must be numeric"
        ) from exc
    if leeway_seconds < 0 or leeway_seconds > 300:
        raise RuntimeError(
            "NORA_WORKLOAD_LEEWAY_SECONDS must be between 0 and 300"
        )

    organization_claim = os.getenv(
        "NORA_WORKLOAD_ORGANIZATION_CLAIM"
    )
    try:
        return WorkloadJwtPrincipalResolver(
            jwks_url=jwks_url,
            issuer=issuer,
            audience=audience,
            algorithms=algorithms,
            principal_claim=os.getenv(
                "NORA_WORKLOAD_PRINCIPAL_CLAIM",
                "sub",
            ).strip() or "sub",
            organization_claim=(
                organization_claim.strip()
                if organization_claim
                and organization_claim.strip()
                else None
            ),
            leeway_seconds=leeway_seconds,
        )
    except ValueError as exc:
        raise RuntimeError(
            f"Invalid workload JWT configuration: {exc}"
        ) from exc


def _build_oidc_principal_resolver():
    jwks_url = os.getenv(
        "NORA_OIDC_JWKS_URL",
        "",
    ).strip()
    issuer = os.getenv(
        "NORA_OIDC_ISSUER",
        "",
    ).strip()
    audience = os.getenv(
        "NORA_OIDC_AUDIENCE",
        "",
    ).strip()
    organization_id = os.getenv(
        "NORA_OIDC_ORGANIZATION_ID",
        "",
    ).strip()
    raw_role_mapping = os.getenv(
        "NORA_OIDC_ROLE_MAPPING",
        "",
    ).strip()
    algorithms = tuple(
        item.strip()
        for item in os.getenv(
            "NORA_OIDC_ALGORITHMS",
            "RS256",
        ).split(",")
        if item.strip()
    )
    allow_insecure = os.getenv(
        "NORA_OIDC_ALLOW_INSECURE_JWKS",
        "false",
    ).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if (
        not jwks_url
        or not issuer
        or not audience
        or not organization_id
        or not raw_role_mapping
    ):
        raise RuntimeError(
            "NORA_OIDC_JWKS_URL, NORA_OIDC_ISSUER, "
            "NORA_OIDC_AUDIENCE, NORA_OIDC_ORGANIZATION_ID, and "
            "NORA_OIDC_ROLE_MAPPING are required for OIDC auth"
        )
    if (
        not jwks_url.startswith("https://")
        and not allow_insecure
    ):
        raise RuntimeError(
            "NORA_OIDC_JWKS_URL must use https:// unless "
            "NORA_OIDC_ALLOW_INSECURE_JWKS=true"
        )
    try:
        raw_mapping = json.loads(
            raw_role_mapping
        )
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "NORA_OIDC_ROLE_MAPPING must be a JSON object"
        ) from exc
    if not isinstance(
        raw_mapping,
        dict,
    ):
        raise RuntimeError(
            "NORA_OIDC_ROLE_MAPPING must be a JSON object"
        )
    role_mapping = {}
    for external, role_name in raw_mapping.items():
        if not isinstance(
            external,
            str,
        ) or not isinstance(
            role_name,
            str,
        ):
            raise RuntimeError(
                "NORA_OIDC_ROLE_MAPPING keys and values must be strings"
            )
        try:
            role_mapping[
                external
            ] = ActorRole(
                role_name.strip().lower()
            )
        except ValueError as exc:
            raise RuntimeError(
                "NORA_OIDC_ROLE_MAPPING contains an unknown Nora role"
            ) from exc

    try:
        leeway_seconds = float(
            os.getenv(
                "NORA_OIDC_LEEWAY_SECONDS",
                "30",
            )
        )
    except ValueError as exc:
        raise RuntimeError(
            "NORA_OIDC_LEEWAY_SECONDS must be numeric"
        ) from exc
    if leeway_seconds < 0 or leeway_seconds > 300:
        raise RuntimeError(
            "NORA_OIDC_LEEWAY_SECONDS must be between 0 and 300"
        )

    try:
        return OrganizationOidcPrincipalResolver(
            jwks_url=jwks_url,
            issuer=issuer,
            audience=audience,
            organization_id=organization_id,
            organization_claim=os.getenv(
                "NORA_OIDC_ORGANIZATION_CLAIM",
                "org_id",
            ).strip() or "org_id",
            groups_claim=os.getenv(
                "NORA_OIDC_GROUPS_CLAIM",
                "groups",
            ).strip() or "groups",
            role_mapping=role_mapping,
            algorithms=algorithms,
            principal_claim=os.getenv(
                "NORA_OIDC_PRINCIPAL_CLAIM",
                "sub",
            ).strip() or "sub",
            candidate_ref_claim=os.getenv(
                "NORA_OIDC_CANDIDATE_REF_CLAIM",
                "candidate_ref",
            ).strip() or "candidate_ref",
            candidate_ref_from_subject=os.getenv(
                "NORA_OIDC_CANDIDATE_REF_FROM_SUBJECT",
                "true",
            ).strip().lower() in {
                "1",
                "true",
                "yes",
                "on",
            },
            leeway_seconds=leeway_seconds,
        )
    except ValueError as exc:
        raise RuntimeError(
            f"Invalid OIDC configuration: {exc}"
        ) from exc

def build_principal_resolver():
    """Build the HTTP principal resolver.

    disabled:
        Backward-compatible local/demo mode. All requests are treated as the
        trusted service principal.

    dev-header:
        Development-only role simulation through X-Nora-* headers.
        Do not use this mode as a production authentication mechanism.

    oidc:
        Organization-scoped OpenID Connect bearer tokens with trusted
        issuer/audience validation and group-to-role mapping.
    """

    mode = os.getenv(
        "NORA_AUTH_MODE",
        "disabled",
    ).strip().lower()

    if mode == "disabled":
        return DisabledPrincipalResolver()

    if mode == "dev-header":
        return DevHeaderPrincipalResolver()

    if mode == "workload-jwt":
        return _build_workload_principal_resolver()

    if mode == "oidc+workload":
        return CompositePrincipalResolver((
            _build_oidc_principal_resolver(),
            _build_workload_principal_resolver(),
        ))

    if mode == "oidc":
        jwks_url = os.getenv(
            "NORA_OIDC_JWKS_URL",
            "",
        ).strip()
        issuer = os.getenv(
            "NORA_OIDC_ISSUER",
            "",
        ).strip()
        audience = os.getenv(
            "NORA_OIDC_AUDIENCE",
            "",
        ).strip()
        organization_id = os.getenv(
            "NORA_OIDC_ORGANIZATION_ID",
            "",
        ).strip()
        raw_role_mapping = os.getenv(
            "NORA_OIDC_ROLE_MAPPING",
            "",
        ).strip()
        algorithms = tuple(
            item.strip()
            for item in os.getenv(
                "NORA_OIDC_ALGORITHMS",
                "RS256",
            ).split(",")
            if item.strip()
        )
        allow_insecure_jwks = os.getenv(
            "NORA_OIDC_ALLOW_INSECURE_JWKS",
            "false",
        ).strip().lower() in {"1", "true", "yes", "on"}
        candidate_ref_from_subject = os.getenv(
            "NORA_OIDC_CANDIDATE_REF_FROM_SUBJECT",
            "true",
        ).strip().lower() in {"1", "true", "yes", "on"}

        if (
            not jwks_url
            or not issuer
            or not audience
            or not organization_id
            or not raw_role_mapping
        ):
            raise RuntimeError(
                "NORA_OIDC_JWKS_URL, NORA_OIDC_ISSUER, "
                "NORA_OIDC_AUDIENCE, NORA_OIDC_ORGANIZATION_ID, and "
                "NORA_OIDC_ROLE_MAPPING are required in oidc mode"
            )
        if (
            not jwks_url.startswith("https://")
            and not allow_insecure_jwks
        ):
            raise RuntimeError(
                "NORA_OIDC_JWKS_URL must use https:// unless "
                "NORA_OIDC_ALLOW_INSECURE_JWKS=true"
            )

        try:
            raw_mapping = json.loads(raw_role_mapping)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "NORA_OIDC_ROLE_MAPPING must be a JSON object"
            ) from exc
        if not isinstance(raw_mapping, dict):
            raise RuntimeError(
                "NORA_OIDC_ROLE_MAPPING must be a JSON object"
            )

        role_mapping = {}
        for external, role_name in raw_mapping.items():
            if not isinstance(external, str) or not isinstance(
                role_name,
                str,
            ):
                raise RuntimeError(
                    "NORA_OIDC_ROLE_MAPPING keys and values must be strings"
                )
            try:
                role_mapping[external] = ActorRole(
                    role_name.strip().lower()
                )
            except ValueError as exc:
                raise RuntimeError(
                    "NORA_OIDC_ROLE_MAPPING contains an unknown Nora role"
                ) from exc

        try:
            leeway_seconds = float(
                os.getenv(
                    "NORA_OIDC_LEEWAY_SECONDS",
                    "30",
                )
            )
        except ValueError as exc:
            raise RuntimeError(
                "NORA_OIDC_LEEWAY_SECONDS must be numeric"
            ) from exc
        if leeway_seconds < 0 or leeway_seconds > 300:
            raise RuntimeError(
                "NORA_OIDC_LEEWAY_SECONDS must be between 0 and 300"
            )

        try:
            return OrganizationOidcPrincipalResolver(
                jwks_url=jwks_url,
                issuer=issuer,
                audience=audience,
                organization_id=organization_id,
                organization_claim=os.getenv(
                    "NORA_OIDC_ORGANIZATION_CLAIM",
                    "org_id",
                ).strip() or "org_id",
                groups_claim=os.getenv(
                    "NORA_OIDC_GROUPS_CLAIM",
                    "groups",
                ).strip() or "groups",
                role_mapping=role_mapping,
                algorithms=algorithms,
                principal_claim=os.getenv(
                    "NORA_OIDC_PRINCIPAL_CLAIM",
                    "sub",
                ).strip() or "sub",
                candidate_ref_claim=os.getenv(
                    "NORA_OIDC_CANDIDATE_REF_CLAIM",
                    "candidate_ref",
                ).strip() or "candidate_ref",
                candidate_ref_from_subject=(
                    candidate_ref_from_subject
                ),
                leeway_seconds=leeway_seconds,
            )
        except ValueError as exc:
            raise RuntimeError(
                f"Invalid OIDC configuration: {exc}"
            ) from exc

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


def build_vad_config() -> VadConfig | None:
    mode = os.getenv(
        "NORA_VAD_MODE",
        "disabled",
    ).strip().lower()

    if mode == "disabled":
        return None
    if mode != "energy":
        raise RuntimeError(
            f"Unsupported NORA_VAD_MODE: {mode}"
        )

    try:
        return VadConfig(
            speech_threshold=float(
                os.getenv(
                    "NORA_VAD_SPEECH_THRESHOLD",
                    "0.02",
                )
            ),
            release_threshold=float(
                os.getenv(
                    "NORA_VAD_RELEASE_THRESHOLD",
                    "0.012",
                )
            ),
            speech_start_ms=int(
                os.getenv(
                    "NORA_VAD_SPEECH_START_MS",
                    "120",
                )
            ),
            speech_end_silence_ms=int(
                os.getenv(
                    "NORA_VAD_END_SILENCE_MS",
                    "700",
                )
            ),
            max_utterance_ms=int(
                os.getenv(
                    "NORA_VAD_MAX_UTTERANCE_MS",
                    "120000",
                )
            ),
        )
    except ValueError as exc:
        raise RuntimeError(
            f"Invalid energy VAD configuration: {exc}"
        ) from exc


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


def build_operational_slo_policy() -> OperationalSloPolicy:
    try:
        return OperationalSloPolicy(
            max_http_5xx_ratio=float(
                os.getenv(
                    "NORA_SLO_MAX_HTTP_5XX_RATIO",
                    "0.05",
                )
            ),
            min_http_requests_for_error_ratio=int(
                os.getenv(
                    "NORA_SLO_MIN_HTTP_REQUESTS",
                    "20",
                )
            ),
            max_unassigned_review_required=int(
                os.getenv(
                    "NORA_SLO_MAX_UNASSIGNED_REVIEWS",
                    "20",
                )
            ),
            max_failed_evidence_runs=int(
                os.getenv(
                    "NORA_SLO_MAX_FAILED_EVIDENCE_RUNS",
                    "5",
                )
            ),
        )
    except ValueError as exc:
        raise RuntimeError(
            f"Invalid operational SLO configuration: {exc}"
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
