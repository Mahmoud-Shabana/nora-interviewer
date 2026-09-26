from __future__ import annotations

import os

from .models import StrictModel
from .service import InterviewService
from .storage import Store


class SystemCapabilities(StrictModel):
    api_version: str
    storage_backend: str
    auth_resolver: str
    interview_brain: str
    evidence_judge_enabled: bool
    evidence_judge_backend: str
    sandbox_mode: str
    realtime_voice: bool = True
    candidate_controls: bool = True
    practical_tools: bool = True
    event_replay: bool = True
    counterfactual_replay: bool = True
    retention_manager: bool = True
    optimistic_concurrency: bool = True
    recruiter_review_queue: bool = True
    recruiter_review_bundle: bool = True
    recruiter_review_console: bool = True
    session_etags: bool = True
    session_cancellation: bool = True
    storage_readiness: bool = True
    jwt_jwks_auth: bool = False
    organization_oidc_auth: bool = False
    evidence_judge_ensemble: bool = False
    streaming_stt_enabled: bool = False
    streaming_stt_backend: str = "DisabledStreamingSpeechProvider"
    streaming_tts_enabled: bool = False
    streaming_tts_backend: str = "DisabledStreamingTtsProvider"
    voice_provider_health: bool = True
    operational_metrics: bool = True
    correlation_ids: bool = True
    rubric_drafter_enabled: bool = False
    rubric_drafter_backend: str = "DisabledRubricDrafter"
    rubric_draft_persistence: bool = True
    rubric_human_approval: bool = True
    job_rubric_provenance: bool = True
    artifact_storage_enabled: bool = False
    artifact_storage_backend: str = "disabled"
    artifact_encrypted_at_rest: bool = False
    artifact_signed_access: bool = False
    voxrubric_export: bool = True


def describe_capabilities(
    *,
    api_version: str,
    store: Store,
    principal_resolver,
    service: InterviewService,
    streaming_speech_provider=None,
    streaming_tts_provider=None,
    rubric_drafter=None,
    artifact_store=None,
) -> SystemCapabilities:
    judge = service.evidence_judge
    judge_backend = type(judge).__name__
    speech_object = (
        getattr(streaming_speech_provider, "inner", streaming_speech_provider)
        if streaming_speech_provider is not None
        else None
    )
    tts_object = (
        getattr(streaming_tts_provider, "inner", streaming_tts_provider)
        if streaming_tts_provider is not None
        else None
    )
    speech_backend = (
        type(speech_object).__name__
        if speech_object is not None
        else "DisabledStreamingSpeechProvider"
    )
    tts_backend = (
        type(tts_object).__name__
        if tts_object is not None
        else "DisabledStreamingTtsProvider"
    )
    rubric_drafter_backend = (
        type(rubric_drafter).__name__
        if rubric_drafter is not None
        else "DisabledRubricDrafter"
    )

    return SystemCapabilities(
        api_version=api_version,
        storage_backend=type(store).__name__,
        auth_resolver=type(principal_resolver).__name__,
        jwt_jwks_auth=(
            type(principal_resolver).__name__
            == "JwtJwksPrincipalResolver"
        ),
        organization_oidc_auth=(
            type(principal_resolver).__name__
            == "OrganizationOidcPrincipalResolver"
        ),
        interview_brain=type(service.brain).__name__,
        evidence_judge_enabled=(
            judge.judge_id != "disabled"
        ),
        evidence_judge_backend=judge_backend,
        evidence_judge_ensemble=(
            judge_backend == "EvidenceJudgeEnsemble"
        ),
        streaming_stt_enabled=(
            speech_backend != "DisabledStreamingSpeechProvider"
        ),
        streaming_stt_backend=speech_backend,
        streaming_tts_enabled=(
            tts_backend != "DisabledStreamingTtsProvider"
        ),
        streaming_tts_backend=tts_backend,
        rubric_drafter_enabled=(
            rubric_drafter_backend != "DisabledRubricDrafter"
        ),
        rubric_drafter_backend=rubric_drafter_backend,
        artifact_storage_enabled=(
            artifact_store is not None
            and getattr(
                artifact_store,
                "provider_id",
                "disabled",
            ) != "disabled"
        ),
        artifact_storage_backend=(
            getattr(
                artifact_store,
                "provider_id",
                "disabled",
            )
            if artifact_store is not None
            else "disabled"
        ),
        artifact_encrypted_at_rest=bool(
            getattr(
                artifact_store,
                "encrypted_at_rest",
                False,
            )
        ),
        artifact_signed_access=(
            artifact_store is not None
            and getattr(
                artifact_store,
                "provider_id",
                "disabled",
            ) != "disabled"
        ),
        sandbox_mode=os.getenv(
            "NORA_SANDBOX_MODE",
            "disabled",
        ).strip().lower(),
    )
