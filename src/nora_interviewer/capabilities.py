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
    evidence_judge_ensemble: bool = False
    voxrubric_export: bool = True


def describe_capabilities(
    *,
    api_version: str,
    store: Store,
    principal_resolver,
    service: InterviewService,
) -> SystemCapabilities:
    judge = service.evidence_judge
    judge_backend = type(judge).__name__

    return SystemCapabilities(
        api_version=api_version,
        storage_backend=type(store).__name__,
        auth_resolver=type(principal_resolver).__name__,
        interview_brain=type(service.brain).__name__,
        evidence_judge_enabled=(
            judge.judge_id != "disabled"
        ),
        evidence_judge_backend=judge_backend,
        evidence_judge_ensemble=(
            judge_backend == "EvidenceJudgeEnsemble"
        ),
        sandbox_mode=os.getenv(
            "NORA_SANDBOX_MODE",
            "disabled",
        ).strip().lower(),
    )
