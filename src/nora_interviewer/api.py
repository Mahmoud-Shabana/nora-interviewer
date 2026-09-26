from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from pydantic import ValidationError
from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from .audio_stream_manager import AudioStreamManager
from .authorization import AccessPolicy, Permission, Principal
from .capabilities import SystemCapabilities, describe_capabilities
from .coding import CodingChallengeRequest
from .config import (
    build_artifact_service,
    build_artifact_store,
    build_brain,
    build_evidence_judge,
    build_operational_slo_policy,
    build_principal_resolver,
    build_rubric_drafter,
    build_store,
    build_streaming_speech_provider,
    build_streaming_tts_provider,
    build_vad_config,
    build_voice_provider_health_registry,
    build_webhook_store,
)
from .counterfactual import CounterfactualReplayReport
from .feedback import CandidateFeedbackReport
from .http_metrics import HttpRequestMetrics
from .operations import (
    OperationalSnapshot,
    OperationsService,
    render_prometheus,
)
from .models import (
    AppealReviewRequest,
    ArtifactAccessGrant,
    ArtifactRecord,
    AppealReviewSubmission,
    CandidateAppeal,
    CandidateAppealRequest,
    CandidateControlRequest,
    CandidateControlResult,
    CandidateResponse,
    CancelSessionRequest,
    CompetencyEvidence,
    CreateSession,
    EvidenceJudgeRun,
    EvidenceObservation,
    IntegrityReviewRequest,
    IntegrityReviewSubmission,
    IntegritySignal,
    IntegritySignalRequest,
    InterviewEvent,
    InterviewSession,
    JobSpec,
    ReviewAssignment,
    SessionStep,
    ToolInvocation,
    ToolStep,
    ToolSubmissionRequest,
    TranscriptCorrectionRequest,
    TranscriptRevision,
    VoxRubricTrace,
)
from .replay import ReplayState
from .review import (
    EvidenceReevaluationQueueItem,
    RecruiterSessionReport,
    ReviewAssignmentActionRequest,
    ReviewAssignmentCreateRequest,
    ReviewDashboardSummary,
    ReviewQueueItem,
)
from .review_bundle import ReviewBundle, build_review_bundle
from .review_service import ReviewService
from .provider_health import (
    ProviderCircuitOpenError,
    ProviderHealthSnapshot,
)
from .providers.guarded_voice import (
    GuardedStreamingSpeechProvider,
    GuardedStreamingTtsProvider,
)
from .providers.streaming_speech import StreamingSpeechUnavailableError
from .providers.streaming_tts import StreamingTtsUnavailableError
from .retention import RetentionManager, RetentionReport, RetentionRequest
from .rubric_drafting import (
    RubricApprovalRequest,
    RubricApprovalResult,
    RubricDraft,
    RubricDraftError,
    RubricDraftRequest,
)
from .rubric_service import RubricWorkflowService
from .slo import (
    OperationalSloAssessment,
    assess_operational_slo,
)
from .service import InterviewService
from .trace_context import (
    reset_correlation_id,
    resolve_correlation_id,
    set_correlation_id,
)
from .voice import (
    RealtimeVoiceCoordinator,
    TranscriptEvent,
    TtsLifecycleEvent,
    VoiceSessionState,
    VoiceTransportFallbackEvent,
    VoiceTransportSelectionEvent,
    VoiceTurnResult,
)
from .voice_stream import (
    AudioBackpressureError,
    AudioChunkMessage,
    AudioGenerationError,
    AudioReconnectError,
    AudioSequenceError,
    AudioStreamCloseRequest,
    AudioStreamError,
    AudioStreamOpenRequest,
    AudioStreamReconnectRequest,
)
from .voice_output import (
    TtsStreamConflictError,
    TtsStreamError,
    TtsStreamNotFoundError,
    TtsStreamOpenRequest,
    VoiceTransportCapabilities,
)
from .voice_output_bridge import VoiceOutputBridge
from .websocket_metrics import (
    WebSocketMetrics,
    WebSocketMetricsMiddleware,
)
from .voice_stream_bridge import (
    StreamingFinalTranscript,
    StreamingPartialTranscript,
    StreamingProviderFailure,
    VoiceStreamBridge,
)
from .web import (
    WEB_DIR,
    render_interview_room,
    render_job_studio,
    render_review_console,
)

API_VERSION = "0.6.0-dev"

store = build_webhook_store(
    build_store()
)
artifact_store = build_artifact_store()
artifact_service = build_artifact_service(
    store=store,
    object_store=artifact_store,
)
service = InterviewService(
    store=store,
    brain=build_brain(),
    evidence_judge=build_evidence_judge(),
)
voice = RealtimeVoiceCoordinator(service=service, store=store)
principal_resolver = build_principal_resolver()
rubric_drafter = build_rubric_drafter()
rubric_service = RubricWorkflowService(
    store=store,
    drafter=rubric_drafter,
)
retention = RetentionManager(
    store,
    artifact_service=artifact_service,
)
review_service = ReviewService(store=store)
raw_streaming_speech_provider = build_streaming_speech_provider()
raw_streaming_tts_provider = build_streaming_tts_provider()
voice_provider_health = build_voice_provider_health_registry()
vad_config = build_vad_config()
streaming_speech_provider = GuardedStreamingSpeechProvider(
    inner=raw_streaming_speech_provider,
    registry=voice_provider_health,
)
streaming_tts_provider = GuardedStreamingTtsProvider(
    inner=raw_streaming_tts_provider,
    registry=voice_provider_health,
)
audio_stream_manager = AudioStreamManager()
audio_bridge = VoiceStreamBridge(
    manager=audio_stream_manager,
    provider=streaming_speech_provider,
    voice=voice,
    vad_config=vad_config,
)
tts_bridge = VoiceOutputBridge(
    store=store,
    provider=streaming_tts_provider,
    voice=voice,
)
http_metrics = HttpRequestMetrics()
websocket_metrics = WebSocketMetrics()
slo_policy = build_operational_slo_policy()
operations = OperationsService(
    store=store,
    review_service=review_service,
    provider_health=voice_provider_health,
    audio_stream_manager=audio_stream_manager,
    tts_bridge=tts_bridge,
    http_metrics=http_metrics,
    websocket_metrics=websocket_metrics,
)
AUDIO_RECONNECT_GRACE_SECONDS = 30.0
_audio_expiry_tasks: dict[str, asyncio.Task] = {}


def current_principal(
    request: Request,
) -> Principal:
    return principal_resolver.resolve(request.headers)


async def require_session_permission(
    session_id: str,
    principal: Principal,
    permission: Permission,
) -> InterviewSession:
    session = await store.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    AccessPolicy.require(
        principal,
        permission,
        session=session,
    )
    return session


def require_global_permission(
    principal: Principal,
    permission: Permission,
) -> None:
    AccessPolicy.require(
        principal,
        permission,
    )


def session_etag(session: InterviewSession) -> str:
    return f'"nora-session-{session.id}-v{session.version}"'


def enforce_session_precondition(
    session: InterviewSession,
    if_match: str | None,
) -> None:
    if if_match is None or if_match == "*":
        return

    current = session_etag(session)
    if if_match.strip() != current:
        raise HTTPException(
            status_code=412,
            detail={
                "message": (
                    "Session version precondition failed. "
                    "Reload the session and retry with the current ETag."
                ),
                "current_etag": current,
                "current_version": session.version,
            },
        )


@asynccontextmanager
async def lifespan(_: FastAPI):
    await voice_provider_health.register(
        key="streaming_stt",
        provider_id=streaming_speech_provider.provider_id,
        disabled=(
            streaming_speech_provider.provider_id
            == "disabled"
        ),
    )
    await voice_provider_health.register(
        key="streaming_tts",
        provider_id=streaming_tts_provider.provider_id,
        disabled=(
            streaming_tts_provider.provider_id
            == "disabled"
        ),
    )
    try:
        yield
    finally:
        for task in list(_audio_expiry_tasks.values()):
            task.cancel()
        await audio_bridge.close_all()
        await tts_bridge.close_all()
        await store.close()


app = FastAPI(
    title="Nora Interviewer",
    version=API_VERSION,
    description="Provider-neutral orchestration API for auditable AI interviews.",
    lifespan=lifespan,
)
app.add_middleware(
    WebSocketMetricsMiddleware,
    registry=websocket_metrics,
)
app.mount("/assets", StaticFiles(directory=WEB_DIR), name="assets")


@app.middleware("http")
async def correlation_id_middleware(
    request: Request,
    call_next,
):
    correlation_id = resolve_correlation_id(
        request.headers.get("x-request-id"),
        prefix="req",
    )
    token = set_correlation_id(
        correlation_id
    )
    started_at = http_metrics.start_timer()
    await http_metrics.request_started()
    try:
        response = await call_next(request)
        route = request.scope.get("route")
        route_template = str(
            getattr(
                route,
                "path",
                "<unmatched>",
            )
        )
        await http_metrics.request_finished(
            method=request.method,
            route=route_template,
            status_code=response.status_code,
            started_at=started_at,
        )
        response.headers[
            "X-Request-ID"
        ] = correlation_id
        return response
    except Exception:
        await http_metrics.request_aborted(
            method=request.method,
            route="<exception>",
            started_at=started_at,
        )
        raise
    finally:
        reset_correlation_id(token)


@app.get("/", response_class=HTMLResponse)
async def home() -> HTMLResponse:
    return HTMLResponse(render_interview_room())


@app.get("/review", response_class=HTMLResponse)
async def review_console() -> HTMLResponse:
    return HTMLResponse(render_review_console())


@app.get("/studio", response_class=HTMLResponse)
async def job_studio() -> HTMLResponse:
    return HTMLResponse(render_job_studio())


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready")
async def readiness() -> dict[str, str]:
    try:
        await store.ping()
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="Storage backend is not ready",
        ) from exc

    return {
        "status": "ready",
        "storage": type(store).__name__,
        "api_version": API_VERSION,
    }


@app.get(
    "/v1/system/operations",
    response_model=OperationalSnapshot,
)
async def operational_snapshot(
    principal: Principal = Depends(current_principal),
) -> OperationalSnapshot:
    require_global_permission(
        principal,
        Permission.READ_SYSTEM,
    )
    return await operations.snapshot()


@app.get(
    "/v1/system/slo",
    response_model=OperationalSloAssessment,
)
async def operational_slo(
    principal: Principal = Depends(current_principal),
) -> OperationalSloAssessment:
    require_global_permission(
        principal,
        Permission.READ_SYSTEM,
    )
    snapshot = await operations.snapshot()
    return assess_operational_slo(
        snapshot,
        slo_policy,
    )


@app.get(
    "/v1/system/metrics",
    response_class=PlainTextResponse,
)
async def operational_metrics(
    principal: Principal = Depends(current_principal),
) -> PlainTextResponse:
    require_global_permission(
        principal,
        Permission.READ_SYSTEM,
    )
    snapshot = await operations.snapshot()
    slo = assess_operational_slo(
        snapshot,
        slo_policy,
    )
    return PlainTextResponse(
        render_prometheus(
            snapshot,
            slo,
        ),
        media_type="text/plain; version=0.0.4",
        headers={
            "Cache-Control": "no-store",
        },
    )


@app.get(
    "/v1/system/voice-health",
    response_model=list[ProviderHealthSnapshot],
)
async def voice_provider_health_status(
    principal: Principal = Depends(current_principal),
) -> list[ProviderHealthSnapshot]:
    require_global_permission(
        principal,
        Permission.READ_SYSTEM,
    )
    return await voice_provider_health.snapshots()


@app.get(
    "/v1/system/capabilities",
    response_model=SystemCapabilities,
)
async def system_capabilities(
    principal: Principal = Depends(current_principal),
) -> SystemCapabilities:
    require_global_permission(
        principal,
        Permission.READ_SYSTEM,
    )
    return describe_capabilities(
        api_version=API_VERSION,
        store=store,
        principal_resolver=principal_resolver,
        service=service,
        streaming_speech_provider=streaming_speech_provider,
        streaming_tts_provider=streaming_tts_provider,
        rubric_drafter=rubric_drafter,
        artifact_store=artifact_store,
    )


@app.post(
    "/v1/rubrics/draft",
    response_model=RubricDraft,
)
async def draft_rubric(
    request: RubricDraftRequest,
    principal: Principal = Depends(current_principal),
) -> RubricDraft:
    require_global_permission(
        principal,
        Permission.DRAFT_RUBRIC,
    )
    try:
        return await rubric_service.draft(
            request,
            organization_id=principal.organization_id,
        )
    except RubricDraftError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc


@app.get(
    "/v1/rubrics/drafts/{draft_id}",
    response_model=RubricDraft,
)
async def get_rubric_draft(
    draft_id: str,
    principal: Principal = Depends(current_principal),
) -> RubricDraft:
    require_global_permission(
        principal,
        Permission.READ_RUBRIC_DRAFT,
    )
    return await rubric_service.get(
        draft_id,
        organization_id=principal.organization_id,
    )


@app.post(
    "/v1/rubrics/drafts/{draft_id}/approve",
    response_model=RubricApprovalResult,
)
async def approve_rubric(
    draft_id: str,
    request: RubricApprovalRequest,
    principal: Principal = Depends(current_principal),
) -> RubricApprovalResult:
    require_global_permission(
        principal,
        Permission.APPROVE_RUBRIC,
    )
    return await rubric_service.approve(
        draft_id,
        request,
        approved_by=principal.id,
        organization_id=principal.organization_id,
    )


@app.post(
    "/v1/system/retention/run",
    response_model=RetentionReport,
)
async def run_retention(
    request: RetentionRequest,
    principal: Principal = Depends(current_principal),
) -> RetentionReport:
    require_global_permission(
        principal,
        Permission.RUN_RETENTION,
    )
    return await retention.run(request)


@app.get(
    "/v1/review/summary",
    response_model=ReviewDashboardSummary,
)
async def review_summary(
    principal: Principal = Depends(current_principal),
) -> ReviewDashboardSummary:
    require_global_permission(
        principal,
        Permission.READ_REVIEW_QUEUE,
    )
    return await review_service.summary(
        organization_id=principal.organization_id,
    )


@app.get(
    "/v1/review/evidence-reevaluation",
    response_model=list[EvidenceReevaluationQueueItem],
)
async def evidence_reevaluation_queue(
    job_id: str | None = None,
    principal: Principal = Depends(current_principal),
) -> list[EvidenceReevaluationQueueItem]:
    require_global_permission(
        principal,
        Permission.READ_REVIEW_QUEUE,
    )
    return await review_service.evidence_reevaluation_queue(
        job_id=job_id,
        organization_id=principal.organization_id,
    )


@app.get(
    "/v1/review/queue",
    response_model=list[ReviewQueueItem],
)
async def review_queue(
    requires_review_only: bool = True,
    job_id: str | None = None,
    principal: Principal = Depends(current_principal),
) -> list[ReviewQueueItem]:
    require_global_permission(
        principal,
        Permission.READ_REVIEW_QUEUE,
    )
    return await review_service.queue(
        requires_review_only=requires_review_only,
        job_id=job_id,
        organization_id=principal.organization_id,
    )


@app.post(
    "/v1/review/sessions/{session_id}/assignments",
    response_model=ReviewAssignment,
    status_code=201,
)
async def assign_review(
    session_id: str,
    request: ReviewAssignmentCreateRequest,
    if_match: str | None = Header(default=None, alias="If-Match"),
    principal: Principal = Depends(current_principal),
) -> ReviewAssignment:
    session = await require_session_permission(
        session_id,
        principal,
        Permission.ASSIGN_REVIEW,
    )
    enforce_session_precondition(
        session,
        if_match,
    )
    return await review_service.assign(
        session_id,
        request,
        assigned_by=principal.id,
    )


@app.post(
    "/v1/review/sessions/{session_id}/assignments/{assignment_id}/start",
    response_model=ReviewAssignment,
)
async def start_review_assignment(
    session_id: str,
    assignment_id: str,
    if_match: str | None = Header(default=None, alias="If-Match"),
    principal: Principal = Depends(current_principal),
) -> ReviewAssignment:
    session = await require_session_permission(
        session_id,
        principal,
        Permission.WORK_REVIEW_ASSIGNMENT,
    )
    enforce_session_precondition(
        session,
        if_match,
    )
    return await review_service.start_assignment(
        session_id,
        assignment_id,
        reviewer_id=principal.id,
    )


@app.post(
    "/v1/review/sessions/{session_id}/assignments/{assignment_id}/complete",
    response_model=ReviewAssignment,
)
async def complete_review_assignment(
    session_id: str,
    assignment_id: str,
    request: ReviewAssignmentActionRequest,
    if_match: str | None = Header(default=None, alias="If-Match"),
    principal: Principal = Depends(current_principal),
) -> ReviewAssignment:
    session = await require_session_permission(
        session_id,
        principal,
        Permission.WORK_REVIEW_ASSIGNMENT,
    )
    enforce_session_precondition(
        session,
        if_match,
    )
    return await review_service.complete_assignment(
        session_id,
        assignment_id,
        request,
        reviewer_id=principal.id,
    )


@app.post(
    "/v1/review/sessions/{session_id}/assignments/{assignment_id}/cancel",
    response_model=ReviewAssignment,
)
async def cancel_review_assignment(
    session_id: str,
    assignment_id: str,
    request: ReviewAssignmentActionRequest,
    if_match: str | None = Header(default=None, alias="If-Match"),
    principal: Principal = Depends(current_principal),
) -> ReviewAssignment:
    session = await require_session_permission(
        session_id,
        principal,
        Permission.CANCEL_REVIEW_ASSIGNMENT,
    )
    enforce_session_precondition(
        session,
        if_match,
    )
    return await review_service.cancel_assignment(
        session_id,
        assignment_id,
        request,
        cancelled_by=principal.id,
    )


@app.get(
    "/v1/review/sessions/{session_id}",
    response_model=RecruiterSessionReport,
)
async def recruiter_session_report(
    session_id: str,
    principal: Principal = Depends(current_principal),
) -> RecruiterSessionReport:
    await require_session_permission(
        session_id,
        principal,
        Permission.READ_RECRUITER_REPORT,
    )
    return await review_service.session_report(session_id)


@app.get(
    "/v1/review/sessions/{session_id}/bundle",
    response_model=ReviewBundle,
)
async def recruiter_review_bundle(
    session_id: str,
    principal: Principal = Depends(current_principal),
) -> ReviewBundle:
    await require_session_permission(
        session_id,
        principal,
        Permission.EXPORT_REVIEW_BUNDLE,
    )
    report = await review_service.session_report(session_id)
    trace = await service.export_voxrubric(session_id)
    return build_review_bundle(
        report=report,
        trace=trace,
    )


@app.post("/v1/jobs", response_model=JobSpec, status_code=201)
async def create_job(
    job: JobSpec,
    principal: Principal = Depends(current_principal),
) -> JobSpec:
    require_global_permission(
        principal,
        Permission.CREATE_JOB,
    )
    return await service.create_job(
        job,
        organization_id=principal.organization_id,
    )


@app.post("/v1/sessions", response_model=InterviewSession, status_code=201)
async def create_session(
    request: CreateSession,
    principal: Principal = Depends(current_principal),
) -> InterviewSession:
    require_global_permission(
        principal,
        Permission.CREATE_SESSION,
    )
    return await service.create_session(
        request,
        organization_id=principal.organization_id,
    )



@app.post(
    "/v1/sessions/{session_id}/artifacts",
    response_model=ArtifactRecord,
    status_code=201,
)
async def create_artifact(
    session_id: str,
    request: Request,
    kind: str,
    media_type: str = "application/octet-stream",
    principal: Principal = Depends(current_principal),
) -> ArtifactRecord:
    await require_session_permission(
        session_id,
        principal,
        Permission.CREATE_ARTIFACT,
    )
    chunks: list[bytes] = []
    total_bytes = 0
    async for chunk in request.stream():
        total_bytes += len(chunk)
        if total_bytes > artifact_service.max_artifact_bytes:
            raise HTTPException(
                status_code=413,
                detail="Artifact exceeds configured size limit",
            )
        chunks.append(chunk)
    data = b"".join(chunks)
    return await artifact_service.create(
        session_id,
        data=data,
        kind=kind,
        media_type=media_type,
        created_by=principal.id,
    )


@app.get(
    "/v1/sessions/{session_id}/artifacts",
    response_model=list[ArtifactRecord],
)
async def list_artifacts(
    session_id: str,
    principal: Principal = Depends(current_principal),
) -> list[ArtifactRecord]:
    await require_session_permission(
        session_id,
        principal,
        Permission.READ_ARTIFACT,
    )
    return await artifact_service.list(
        session_id
    )


@app.post(
    "/v1/sessions/{session_id}/artifacts/{artifact_id}/access",
    response_model=ArtifactAccessGrant,
)
async def issue_artifact_access(
    session_id: str,
    artifact_id: str,
    principal: Principal = Depends(current_principal),
) -> ArtifactAccessGrant:
    await require_session_permission(
        session_id,
        principal,
        Permission.READ_ARTIFACT,
    )
    return await artifact_service.issue_access(
        session_id,
        artifact_id,
    )


@app.get(
    "/v1/artifacts/content",
)
async def read_artifact_content(
    token: str,
) -> Response:
    artifact, data = await artifact_service.read_token(
        token
    )
    return Response(
        content=data,
        media_type=artifact.media_type,
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.delete(
    "/v1/sessions/{session_id}/artifacts/{artifact_id}",
    response_model=ArtifactRecord,
)
async def delete_artifact(
    session_id: str,
    artifact_id: str,
    reason: str | None = None,
    principal: Principal = Depends(current_principal),
) -> ArtifactRecord:
    await require_session_permission(
        session_id,
        principal,
        Permission.DELETE_ARTIFACT,
    )
    return await artifact_service.delete(
        session_id,
        artifact_id,
        deleted_by=principal.id,
        reason=reason,
    )

@app.post(
    "/v1/sessions/{session_id}/cancel",
    response_model=InterviewSession,
)
async def cancel_session(
    session_id: str,
    request: CancelSessionRequest,
    if_match: str | None = Header(default=None, alias="If-Match"),
    principal: Principal = Depends(current_principal),
) -> InterviewSession:
    session = await require_session_permission(
        session_id,
        principal,
        Permission.CANCEL_SESSION,
    )
    enforce_session_precondition(session, if_match)

    await service.cancel_session(
        session_id,
        request,
    )
    await voice.close_session(
        session_id,
        reason="session_cancelled",
    )
    current = await store.get_session(session_id)
    if current is None:
        raise HTTPException(404, "Session not found")
    return current


@app.post("/v1/sessions/{session_id}/start", response_model=SessionStep)
async def start_session(
    session_id: str,
    if_match: str | None = Header(default=None, alias="If-Match"),
    principal: Principal = Depends(current_principal),
) -> SessionStep:
    session = await require_session_permission(
        session_id,
        principal,
        Permission.RUN_INTERVIEW,
    )
    enforce_session_precondition(session, if_match)
    return await service.start(session_id)


@app.post("/v1/sessions/{session_id}/responses", response_model=SessionStep)
async def submit_response(
    session_id: str,
    response: CandidateResponse,
    if_match: str | None = Header(default=None, alias="If-Match"),
    principal: Principal = Depends(current_principal),
) -> SessionStep:
    session = await require_session_permission(
        session_id,
        principal,
        Permission.RUN_INTERVIEW,
    )
    enforce_session_precondition(session, if_match)
    return await service.answer(session_id, response.text)


@app.post(
    "/v1/sessions/{session_id}/controls",
    response_model=CandidateControlResult,
)
async def candidate_control(
    session_id: str,
    request: CandidateControlRequest,
    if_match: str | None = Header(default=None, alias="If-Match"),
    principal: Principal = Depends(current_principal),
) -> CandidateControlResult:
    session = await require_session_permission(
        session_id,
        principal,
        Permission.CANDIDATE_CONTROL,
    )
    enforce_session_precondition(session, if_match)
    return await service.candidate_control(session_id, request)


@app.post(
    "/v1/sessions/{session_id}/coding-challenges",
    response_model=ToolInvocation,
    status_code=201,
)
async def open_coding_challenge(
    session_id: str,
    request: CodingChallengeRequest,
    if_match: str | None = Header(default=None, alias="If-Match"),
    principal: Principal = Depends(current_principal),
) -> ToolInvocation:
    session = await require_session_permission(
        session_id,
        principal,
        Permission.OPEN_TOOL,
    )
    enforce_session_precondition(session, if_match)
    return await service.open_coding_challenge(session_id, request)


@app.post(
    "/v1/sessions/{session_id}/tools",
    response_model=ToolInvocation,
    status_code=201,
)
async def open_tool(
    session_id: str,
    invocation: ToolInvocation,
    if_match: str | None = Header(default=None, alias="If-Match"),
    principal: Principal = Depends(current_principal),
) -> ToolInvocation:
    session = await require_session_permission(
        session_id,
        principal,
        Permission.OPEN_TOOL,
    )
    enforce_session_precondition(session, if_match)
    return await service.open_tool(session_id, invocation)


@app.post(
    "/v1/sessions/{session_id}/tools/{tool_id}/submit",
    response_model=ToolStep,
)
async def submit_tool(
    session_id: str,
    tool_id: str,
    request: ToolSubmissionRequest,
    if_match: str | None = Header(default=None, alias="If-Match"),
    principal: Principal = Depends(current_principal),
) -> ToolStep:
    session = await require_session_permission(
        session_id,
        principal,
        Permission.SUBMIT_TOOL,
    )
    enforce_session_precondition(session, if_match)
    return await service.submit_tool(session_id, tool_id, request)


@app.get("/v1/sessions/{session_id}", response_model=InterviewSession)
async def get_session(
    session_id: str,
    response: Response,
    principal: Principal = Depends(current_principal),
) -> InterviewSession:
    session = await require_session_permission(
        session_id,
        principal,
        Permission.READ_SESSION,
    )
    response.headers["ETag"] = session_etag(session)
    response.headers["X-Nora-Session-Version"] = str(session.version)
    response.headers["Cache-Control"] = "no-store"
    return session


@app.post(
    "/v1/sessions/{session_id}/corrections",
    response_model=TranscriptRevision,
    status_code=201,
)
async def correct_transcript(
    session_id: str,
    request: TranscriptCorrectionRequest,
    if_match: str | None = Header(default=None, alias="If-Match"),
    principal: Principal = Depends(current_principal),
) -> TranscriptRevision:
    session = await require_session_permission(
        session_id,
        principal,
        Permission.CORRECT_TRANSCRIPT,
    )
    enforce_session_precondition(session, if_match)
    return await service.correct_transcript(session_id, request)


@app.post(
    "/v1/sessions/{session_id}/appeals",
    response_model=CandidateAppeal,
    status_code=201,
)
async def submit_appeal(
    session_id: str,
    request: CandidateAppealRequest,
    if_match: str | None = Header(default=None, alias="If-Match"),
    principal: Principal = Depends(current_principal),
) -> CandidateAppeal:
    session = await require_session_permission(
        session_id,
        principal,
        Permission.SUBMIT_APPEAL,
    )
    enforce_session_precondition(session, if_match)
    return await service.submit_appeal(session_id, request)


@app.post(
    "/v1/sessions/{session_id}/appeals/{appeal_id}/review",
    response_model=CandidateAppeal,
)
async def review_appeal(
    session_id: str,
    appeal_id: str,
    request: AppealReviewSubmission,
    if_match: str | None = Header(default=None, alias="If-Match"),
    principal: Principal = Depends(current_principal),
) -> CandidateAppeal:
    session = await require_session_permission(
        session_id,
        principal,
        Permission.REVIEW_APPEAL,
    )
    enforce_session_precondition(session, if_match)
    return await service.review_appeal(
        session_id,
        appeal_id,
        AppealReviewRequest(
            reviewer_id=principal.id,
            note=request.note,
        ),
    )


@app.post(
    "/v1/sessions/{session_id}/integrity-signals",
    response_model=IntegritySignal,
    status_code=201,
)
async def submit_integrity_signal(
    session_id: str,
    request: IntegritySignalRequest,
    if_match: str | None = Header(default=None, alias="If-Match"),
    principal: Principal = Depends(current_principal),
) -> IntegritySignal:
    session = await require_session_permission(
        session_id,
        principal,
        Permission.WRITE_INTEGRITY,
    )
    enforce_session_precondition(session, if_match)
    return await service.submit_integrity_signal(session_id, request)


@app.post(
    "/v1/sessions/{session_id}/integrity-signals/{signal_id}/review",
    response_model=IntegritySignal,
)
async def review_integrity_signal(
    session_id: str,
    signal_id: str,
    request: IntegrityReviewSubmission,
    if_match: str | None = Header(default=None, alias="If-Match"),
    principal: Principal = Depends(current_principal),
) -> IntegritySignal:
    session = await require_session_permission(
        session_id,
        principal,
        Permission.REVIEW_INTEGRITY,
    )
    enforce_session_precondition(session, if_match)
    return await service.review_integrity_signal(
        session_id,
        signal_id,
        IntegrityReviewRequest(
            reviewer_id=principal.id,
            note=request.note,
        ),
    )


@app.post(
    "/v1/sessions/{session_id}/evidence/{answer_turn_id}/reevaluate",
    response_model=EvidenceJudgeRun,
)
async def reevaluate_evidence(
    session_id: str,
    answer_turn_id: str,
    if_match: str | None = Header(default=None, alias="If-Match"),
    principal: Principal = Depends(current_principal),
) -> EvidenceJudgeRun:
    session = await require_session_permission(
        session_id,
        principal,
        Permission.REEVALUATE_EVIDENCE,
    )
    enforce_session_precondition(session, if_match)
    return await service.reevaluate_evidence(
        session_id,
        answer_turn_id,
    )


@app.post(
    "/v1/sessions/{session_id}/evidence",
    response_model=CompetencyEvidence,
)
async def observe_evidence(
    session_id: str,
    observation: EvidenceObservation,
    if_match: str | None = Header(default=None, alias="If-Match"),
    principal: Principal = Depends(current_principal),
) -> CompetencyEvidence:
    session = await require_session_permission(
        session_id,
        principal,
        Permission.WRITE_EVIDENCE,
    )
    enforce_session_precondition(session, if_match)
    return await service.observe_evidence(session_id, observation)


@app.get(
    "/v1/sessions/{session_id}/feedback",
    response_model=CandidateFeedbackReport,
)
async def candidate_feedback(
    session_id: str,
    principal: Principal = Depends(current_principal),
) -> CandidateFeedbackReport:
    await require_session_permission(
        session_id,
        principal,
        Permission.READ_FEEDBACK,
    )
    return await service.candidate_feedback(session_id)


@app.get(
    "/v1/sessions/{session_id}/events",
    response_model=list[InterviewEvent],
)
async def get_events(
    session_id: str,
    principal: Principal = Depends(current_principal),
) -> list[InterviewEvent]:
    await require_session_permission(
        session_id,
        principal,
        Permission.READ_EVENTS,
    )
    return await service.events(session_id)


@app.get(
    "/v1/sessions/{session_id}/replay",
    response_model=ReplayState,
)
async def replay_session(
    session_id: str,
    principal: Principal = Depends(current_principal),
) -> ReplayState:
    await require_session_permission(
        session_id,
        principal,
        Permission.READ_REPLAY,
    )
    return await service.replay(session_id)


@app.post(
    "/v1/sessions/{session_id}/decision-replay",
    response_model=CounterfactualReplayReport,
)
async def decision_replay(
    session_id: str,
    principal: Principal = Depends(current_principal),
) -> CounterfactualReplayReport:
    await require_session_permission(
        session_id,
        principal,
        Permission.RUN_DECISION_REPLAY,
    )
    return await service.decision_replay(session_id)


@app.get("/v1/sessions/{session_id}/voxrubric", response_model=VoxRubricTrace)
async def export_voxrubric(
    session_id: str,
    principal: Principal = Depends(current_principal),
) -> VoxRubricTrace:
    await require_session_permission(
        session_id,
        principal,
        Permission.EXPORT_TRACE,
    )
    return await service.export_voxrubric(session_id)


@app.get(
    "/v1/sessions/{session_id}/voice/capabilities",
    response_model=VoiceTransportCapabilities,
)
async def voice_transport_capabilities(
    session_id: str,
    principal: Principal = Depends(current_principal),
) -> VoiceTransportCapabilities:
    await require_session_permission(
        session_id,
        principal,
        Permission.USE_VOICE,
    )
    stt_enabled = (
        getattr(
            streaming_speech_provider,
            "provider_id",
            "disabled",
        )
        != "disabled"
    )
    tts_enabled = (
        getattr(
            streaming_tts_provider,
            "provider_id",
            "disabled",
        )
        != "disabled"
    )
    stt_health = await voice_provider_health.snapshot(
        "streaming_stt"
    )
    tts_health = await voice_provider_health.snapshot(
        "streaming_tts"
    )
    stt_available = (
        stt_enabled
        and stt_health.state.value != "open"
    )
    tts_available = (
        tts_enabled
        and tts_health.state.value != "open"
    )
    return VoiceTransportCapabilities(
        streaming_stt_enabled=stt_enabled,
        streaming_stt_available=stt_available,
        streaming_tts_enabled=tts_enabled,
        streaming_tts_available=tts_available,
        stt_health=stt_health.state,
        tts_health=tts_health.state,
        vad_enabled=vad_config is not None,
        vad_backend=(
            "pcm16-energy"
            if vad_config is not None
            else None
        ),
        stt_protocol=(
            "nora.stt.v1"
            if stt_enabled
            else None
        ),
        tts_protocol=(
            "nora.tts.v1"
            if tts_enabled
            else None
        ),
    )


@app.get(
    "/v1/sessions/{session_id}/voice",
    response_model=VoiceSessionState,
)
async def voice_state(
    session_id: str,
    principal: Principal = Depends(current_principal),
) -> VoiceSessionState:
    await require_session_permission(
        session_id,
        principal,
        Permission.USE_VOICE,
    )
    return voice.state(session_id)


@app.post(
    "/v1/sessions/{session_id}/voice/speech-started",
    response_model=VoiceSessionState,
)
async def voice_speech_started(
    session_id: str,
    principal: Principal = Depends(current_principal),
) -> VoiceSessionState:
    await require_session_permission(
        session_id,
        principal,
        Permission.USE_VOICE,
    )
    state = await voice.speech_started(session_id)
    await tts_bridge.cancel_active(
        session_id=session_id,
        reason="barge_in",
    )
    return state


@app.post(
    "/v1/sessions/{session_id}/voice/transcript-partial",
    response_model=VoiceSessionState,
)
async def voice_transcript_partial(
    session_id: str,
    event: TranscriptEvent,
    principal: Principal = Depends(current_principal),
) -> VoiceSessionState:
    await require_session_permission(
        session_id,
        principal,
        Permission.USE_VOICE,
    )
    return await voice.transcript_partial(session_id, event)


@app.post(
    "/v1/sessions/{session_id}/voice/transcript-final",
    response_model=VoiceTurnResult,
)
async def voice_transcript_final(
    session_id: str,
    event: TranscriptEvent,
    principal: Principal = Depends(current_principal),
) -> VoiceTurnResult:
    await require_session_permission(
        session_id,
        principal,
        Permission.USE_VOICE,
    )
    return await voice.transcript_final(session_id, event)


@app.post(
    "/v1/sessions/{session_id}/voice/tts-started",
    response_model=VoiceSessionState,
)
async def voice_tts_started(
    session_id: str,
    event: TtsLifecycleEvent,
    principal: Principal = Depends(current_principal),
) -> VoiceSessionState:
    await require_session_permission(
        session_id,
        principal,
        Permission.USE_VOICE,
    )
    return await voice.tts_started(session_id, event)


@app.post(
    "/v1/sessions/{session_id}/voice/tts-completed",
    response_model=VoiceSessionState,
)
async def voice_tts_completed(
    session_id: str,
    event: TtsLifecycleEvent,
    principal: Principal = Depends(current_principal),
) -> VoiceSessionState:
    await require_session_permission(
        session_id,
        principal,
        Permission.USE_VOICE,
    )
    return await voice.tts_completed(session_id, event)


@app.post(
    "/v1/sessions/{session_id}/voice/tts-cancelled",
    response_model=VoiceSessionState,
)
async def voice_tts_cancelled(
    session_id: str,
    event: TtsLifecycleEvent,
    principal: Principal = Depends(current_principal),
) -> VoiceSessionState:
    await require_session_permission(
        session_id,
        principal,
        Permission.USE_VOICE,
    )
    return await voice.tts_cancelled(session_id, event)


@app.websocket("/v1/ws/interviews/{session_id}")
async def interview_socket(websocket: WebSocket, session_id: str) -> None:
    set_correlation_id(
        resolve_correlation_id(
            websocket.headers.get("x-request-id"),
            prefix="ws",
        )
    )
    try:
        principal = principal_resolver.resolve(websocket.headers)
        session = await store.get_session(session_id)
        if not session:
            await websocket.close(code=1008)
            return
        AccessPolicy.require(
            principal,
            Permission.RUN_INTERVIEW,
            session=session,
        )
    except HTTPException:
        await websocket.close(code=1008)
        return

    await websocket.accept()
    try:
        step = await service.start(session_id)
        if step.interviewer_turn:
            await websocket.send_json(
                {"type": "interviewer_turn", "data": step.interviewer_turn.model_dump(mode="json")}
            )
        if step.tool_invocation:
            await websocket.send_json(
                {"type": "tool_opened", "data": step.tool_invocation.model_dump(mode="json")}
            )

        while step.status.value != "completed":
            event = await websocket.receive_json()
            event_type = event.get("type")

            if event_type == "ping":
                await websocket.send_json({"type": "pong"})
                continue

            if event_type == "candidate_control":
                AccessPolicy.require(
                    principal,
                    Permission.CANDIDATE_CONTROL,
                    session=session,
                )
                request = CandidateControlRequest.model_validate(event.get("data", {}))
                result = await service.candidate_control(session_id, request)
                await websocket.send_json(
                    {"type": "candidate_control_ack", "data": result.model_dump(mode="json")}
                )
                if result.interviewer_turn:
                    await websocket.send_json(
                        {
                            "type": "interviewer_turn",
                            "data": result.interviewer_turn.model_dump(mode="json"),
                        }
                    )
                continue

            if event_type == "voice_transport_selected":
                AccessPolicy.require(
                    principal,
                    Permission.USE_VOICE,
                    session=session,
                )
                selection = VoiceTransportSelectionEvent.model_validate(
                    event.get("data", {})
                )
                await voice.transport_selected(
                    session_id,
                    selection,
                )
                await websocket.send_json({
                    "type": "voice_transport_ack",
                    "data": selection.model_dump(mode="json"),
                })
                continue

            if event_type == "voice_transport_fallback":
                AccessPolicy.require(
                    principal,
                    Permission.USE_VOICE,
                    session=session,
                )
                fallback = VoiceTransportFallbackEvent.model_validate(
                    event.get("data", {})
                )
                await voice.transport_fallback(
                    session_id,
                    fallback,
                )
                await websocket.send_json({
                    "type": "voice_transport_ack",
                    "data": fallback.model_dump(mode="json"),
                })
                continue

            if event_type == "voice_speech_started":
                AccessPolicy.require(
                    principal,
                    Permission.USE_VOICE,
                    session=session,
                )
                state = await voice.speech_started(session_id)
                await tts_bridge.cancel_active(
                    session_id=session_id,
                    reason="barge_in",
                )
                await websocket.send_json(
                    {"type": "voice_state", "data": state.model_dump(mode="json")}
                )
                continue

            if event_type == "voice_transcript_partial":
                AccessPolicy.require(
                    principal,
                    Permission.USE_VOICE,
                    session=session,
                )
                transcript_event = TranscriptEvent.model_validate(event.get("data", {}))
                state = await voice.transcript_partial(session_id, transcript_event)
                await websocket.send_json(
                    {"type": "voice_state", "data": state.model_dump(mode="json")}
                )
                continue

            if event_type == "voice_transcript_final":
                AccessPolicy.require(
                    principal,
                    Permission.USE_VOICE,
                    session=session,
                )
                transcript_event = TranscriptEvent.model_validate(event.get("data", {}))
                await websocket.send_json({"type": "candidate_ack"})
                voice_result = await voice.transcript_final(
                    session_id,
                    transcript_event,
                )
                await websocket.send_json(
                    {
                        "type": "voice_state",
                        "data": voice_result.state.model_dump(mode="json"),
                    }
                )
                if voice_result.interviewer_turn:
                    await websocket.send_json(
                        {
                            "type": "interviewer_turn",
                            "data": voice_result.interviewer_turn.model_dump(mode="json"),
                        }
                    )
                if voice_result.tool_invocation:
                    await websocket.send_json(
                        {
                            "type": "tool_opened",
                            "data": voice_result.tool_invocation.model_dump(mode="json"),
                        }
                    )
                if voice_result.completed:
                    await websocket.send_json(
                        {"type": "interview_completed", "session_id": session_id}
                    )
                    break
                continue

            if event_type in {
                "voice_tts_started",
                "voice_tts_completed",
                "voice_tts_cancelled",
            }:
                AccessPolicy.require(
                    principal,
                    Permission.USE_VOICE,
                    session=session,
                )
                lifecycle = TtsLifecycleEvent.model_validate(event.get("data", {}))
                if event_type == "voice_tts_started":
                    state = await voice.tts_started(session_id, lifecycle)
                elif event_type == "voice_tts_completed":
                    state = await voice.tts_completed(session_id, lifecycle)
                else:
                    state = await voice.tts_cancelled(session_id, lifecycle)
                await websocket.send_json(
                    {"type": "voice_state", "data": state.model_dump(mode="json")}
                )
                continue

            if event_type != "candidate_text" or not str(event.get("text", "")).strip():
                await websocket.send_json(
                    {
                        "type": "error",
                        "error": (
                            "Expected candidate_text, candidate_control, or supported voice event."
                        ),
                    }
                )
                continue

            AccessPolicy.require(
                principal,
                Permission.RUN_INTERVIEW,
                session=session,
            )
            await websocket.send_json({"type": "candidate_ack"})
            step = await service.answer(session_id, str(event["text"]).strip())
            if step.interviewer_turn:
                await websocket.send_json(
                    {"type": "interviewer_turn", "data": step.interviewer_turn.model_dump(mode="json")}
                )
            if step.tool_invocation:
                await websocket.send_json(
                    {"type": "tool_opened", "data": step.tool_invocation.model_dump(mode="json")}
                )
            if step.status.value == "completed":
                await websocket.send_json(
                    {"type": "interview_completed", "session_id": session_id}
                )
                break
    except WebSocketDisconnect:
        return
    except HTTPException as exc:
        await websocket.send_json({"type": "error", "error": exc.detail})
        await websocket.close(code=1008)



def _audio_error_payload(exc: Exception) -> dict:
    if isinstance(exc, ProviderCircuitOpenError):
        return {
            "code": "stt_circuit_open",
            "message": str(exc),
        }
    if isinstance(exc, StreamingSpeechUnavailableError):
        return {
            "code": "stt_unavailable",
            "message": str(exc),
        }
    if isinstance(exc, AudioStreamError):
        return {
            "code": exc.code,
            "message": str(exc),
        }
    if isinstance(exc, ValidationError):
        return {
            "code": "invalid_audio_message",
            "message": "Audio transport message failed validation",
        }
    if isinstance(exc, HTTPException):
        return {
            "code": f"http_{exc.status_code}",
            "message": str(exc.detail),
        }
    return {
        "code": "audio_transport_error",
        "message": str(exc)[:1000],
    }


def _tts_error_payload(exc: Exception) -> dict:
    if isinstance(exc, ProviderCircuitOpenError):
        return {
            "code": "tts_circuit_open",
            "message": str(exc),
        }
    if isinstance(exc, StreamingTtsUnavailableError):
        return {
            "code": "tts_unavailable",
            "message": str(exc),
        }
    if isinstance(exc, TtsStreamError):
        return {
            "code": exc.code,
            "message": str(exc),
        }
    if isinstance(exc, ValidationError):
        return {
            "code": "invalid_tts_message",
            "message": "TTS transport message failed validation",
        }
    if isinstance(exc, HTTPException):
        return {
            "code": f"http_{exc.status_code}",
            "message": str(exc.detail),
        }
    return {
        "code": "tts_transport_error",
        "message": str(exc)[:1000],
    }


def _cancel_audio_expiry(stream_id: str) -> None:
    task = _audio_expiry_tasks.pop(
        stream_id,
        None,
    )
    if task is not None:
        task.cancel()


def _schedule_audio_expiry(stream_id: str) -> None:
    _cancel_audio_expiry(stream_id)

    async def expire() -> None:
        try:
            await asyncio.sleep(
                AUDIO_RECONNECT_GRACE_SECONDS
            )
            await audio_bridge.close(
                stream_id=stream_id,
                cancel_provider=True,
            )
        except asyncio.CancelledError:
            return
        except Exception:
            return
        finally:
            _audio_expiry_tasks.pop(
                stream_id,
                None,
            )

    _audio_expiry_tasks[stream_id] = (
        asyncio.create_task(expire())
    )


@app.websocket("/v1/ws/tts/{session_id}")
async def tts_socket(
    websocket: WebSocket,
    session_id: str,
) -> None:
    set_correlation_id(
        resolve_correlation_id(
            websocket.headers.get("x-request-id"),
            prefix="ws",
        )
    )
    try:
        principal = principal_resolver.resolve(
            websocket.headers
        )
        session = await store.get_session(
            session_id
        )
        if session is None:
            await websocket.close(code=1008)
            return
        AccessPolicy.require(
            principal,
            Permission.USE_VOICE,
            session=session,
        )
    except HTTPException:
        await websocket.close(code=1008)
        return

    await websocket.accept()

    active_stream_id: str | None = None
    pump_task: asyncio.Task | None = None
    send_lock = asyncio.Lock()

    async def send_json(payload: dict) -> None:
        async with send_lock:
            await websocket.send_json(payload)

    async def pump_audio(
        *,
        stream_id: str,
        turn_id: str,
        generation: int,
    ) -> None:
        nonlocal active_stream_id, pump_task
        try:
            async for chunk in tts_bridge.chunks(
                stream_id=stream_id
            ):
                async with send_lock:
                    await websocket.send_json({
                        "type": "audio_chunk",
                        "data": {
                            "stream_id": stream_id,
                            "turn_id": turn_id,
                            "sequence": chunk.sequence,
                            "generation": chunk.generation,
                            "bytes": len(chunk.audio),
                        },
                    })
                    await websocket.send_bytes(
                        chunk.audio
                    )

            current = voice.state(session_id)
            interrupted = (
                current.generation
                != generation
            )
            await send_json({
                "type": (
                    "stream_cancelled"
                    if interrupted
                    else "stream_completed"
                ),
                "data": {
                    "stream_id": stream_id,
                    "turn_id": turn_id,
                    "generation": generation,
                    "reason": (
                        "barge_in"
                        if interrupted
                        else None
                    ),
                },
            })
        except asyncio.CancelledError:
            return
        except WebSocketDisconnect:
            return
        except Exception as exc:
            try:
                await send_json({
                    "type": "error",
                    "error": _tts_error_payload(
                        exc
                    ),
                })
            except Exception:
                return
        finally:
            if active_stream_id == stream_id:
                active_stream_id = None
            pump_task = None

    try:
        while True:
            message = await websocket.receive_json()
            message_type = str(
                message.get("type", "")
            )

            if message_type == "ping":
                await send_json({"type": "pong"})
                continue

            if message_type == "open":
                if active_stream_id is not None:
                    await send_json({
                        "type": "error",
                        "error": {
                            "code": "tts_stream_already_open",
                            "message": (
                                "Cancel the active TTS stream "
                                "before opening another one."
                            ),
                        },
                    })
                    continue

                request = TtsStreamOpenRequest.model_validate(
                    message.get("data", {})
                )
                opened = await tts_bridge.open(
                    session_id=session_id,
                    turn_id=request.turn_id,
                    locale=request.locale,
                    config=request.config,
                )
                active_stream_id = (
                    opened.state.stream_id
                )
                await send_json({
                    "type": "stream_opened",
                    "data": opened.model_dump(
                        mode="json"
                    ),
                })
                pump_task = asyncio.create_task(
                    pump_audio(
                        stream_id=opened.state.stream_id,
                        turn_id=opened.state.turn_id,
                        generation=opened.state.generation,
                    )
                )
                continue

            if message_type == "cancel":
                if active_stream_id is None:
                    await send_json({
                        "type": "stream_cancelled",
                        "data": None,
                    })
                    continue

                stream_id = active_stream_id
                await tts_bridge.close(
                    stream_id=stream_id,
                    reason="client_cancelled",
                )
                if (
                    pump_task is not None
                    and not pump_task.done()
                ):
                    pump_task.cancel()
                active_stream_id = None
                pump_task = None
                await send_json({
                    "type": "stream_cancelled",
                    "data": {
                        "stream_id": stream_id,
                        "reason": "client_cancelled",
                    },
                })
                continue

            await send_json({
                "type": "error",
                "error": {
                    "code": "unknown_tts_message",
                    "message": (
                        "Expected open, cancel, or ping."
                    ),
                },
            })

    except WebSocketDisconnect:
        if active_stream_id is not None:
            try:
                await tts_bridge.close(
                    stream_id=active_stream_id,
                    reason="client_disconnect",
                )
            except TtsStreamNotFoundError:
                pass
        if (
            pump_task is not None
            and not pump_task.done()
        ):
            pump_task.cancel()
        return
    except (
        ProviderCircuitOpenError,
        StreamingTtsUnavailableError,
        TtsStreamConflictError,
        TtsStreamNotFoundError,
        TtsStreamError,
        ValidationError,
        HTTPException,
    ) as exc:
        try:
            await send_json({
                "type": "error",
                "error": _tts_error_payload(exc),
            })
        finally:
            if active_stream_id is not None:
                try:
                    await tts_bridge.close(
                        stream_id=active_stream_id,
                        reason="transport_error",
                    )
                except TtsStreamNotFoundError:
                    pass
            if (
                pump_task is not None
                and not pump_task.done()
            ):
                pump_task.cancel()
            await websocket.close(code=1008)


@app.websocket("/v1/ws/audio/{session_id}")
async def audio_socket(
    websocket: WebSocket,
    session_id: str,
) -> None:
    set_correlation_id(
        resolve_correlation_id(
            websocket.headers.get("x-request-id"),
            prefix="ws",
        )
    )
    try:
        principal = principal_resolver.resolve(
            websocket.headers
        )
        session = await store.get_session(
            session_id
        )
        if session is None:
            await websocket.close(code=1008)
            return
        AccessPolicy.require(
            principal,
            Permission.USE_VOICE,
            session=session,
        )
    except HTTPException:
        await websocket.close(code=1008)
        return

    await websocket.accept()

    active_stream_id: str | None = None
    event_task: asyncio.Task | None = None
    send_lock = asyncio.Lock()

    async def send_json(payload: dict) -> None:
        async with send_lock:
            await websocket.send_json(payload)

    async def pump_events(stream_id: str) -> None:
        try:
            async for event in audio_bridge.events(
                stream_id=stream_id
            ):
                if isinstance(
                    event,
                    StreamingPartialTranscript,
                ):
                    await send_json({
                        "type": "transcript_partial",
                        "data": {
                            "text": event.event.text,
                            "confidence": event.event.confidence,
                            "voice_state": (
                                event.state.model_dump(
                                    mode="json"
                                )
                            ),
                        },
                    })
                    continue

                if isinstance(
                    event,
                    StreamingFinalTranscript,
                ):
                    result = event.result
                    payload = {
                        "text": event.event.text,
                        "confidence": event.event.confidence,
                        "voice_state": (
                            result.state.model_dump(
                                mode="json"
                            )
                        ),
                        "completed": result.completed,
                        "interviewer_turn": (
                            result.interviewer_turn.model_dump(
                                mode="json"
                            )
                            if result.interviewer_turn
                            else None
                        ),
                        "tool_invocation": (
                            result.tool_invocation.model_dump(
                                mode="json"
                            )
                            if result.tool_invocation
                            else None
                        ),
                    }
                    await send_json({
                        "type": "transcript_final",
                        "data": payload,
                    })
                    continue

                if isinstance(
                    event,
                    StreamingProviderFailure,
                ):
                    await send_json({
                        "type": "error",
                        "error": {
                            "code": "stt_provider_failure",
                            "message": event.message,
                            "error_type": event.error_type,
                        },
                    })
        except asyncio.CancelledError:
            return
        except WebSocketDisconnect:
            return
        except Exception as exc:
            try:
                await send_json({
                    "type": "error",
                    "error": _audio_error_payload(exc),
                })
            except Exception:
                return

    try:
        while True:
            message = await websocket.receive_json()
            message_type = str(
                message.get("type", "")
            )

            if message_type == "ping":
                await send_json({"type": "pong"})
                continue

            if message_type == "open":
                if active_stream_id is not None:
                    await send_json({
                        "type": "error",
                        "error": {
                            "code": "stream_already_open",
                            "message": (
                                "Close the active audio stream "
                                "before opening another one."
                            ),
                        },
                    })
                    continue

                request = AudioStreamOpenRequest.model_validate(
                    message.get("data", {})
                )
                opened = await audio_bridge.open(
                    session_id=session_id,
                    locale=request.locale,
                    config=request.config,
                )
                await tts_bridge.cancel_active(
                    session_id=session_id,
                    reason="barge_in",
                )
                active_stream_id = (
                    opened.state.stream_id
                )
                await send_json({
                    "type": "stream_opened",
                    "data": opened.model_dump(
                        mode="json"
                    ),
                })
                event_task = asyncio.create_task(
                    pump_events(
                        active_stream_id
                    )
                )
                continue

            if message_type == "reconnect":
                if active_stream_id is not None:
                    await send_json({
                        "type": "error",
                        "error": {
                            "code": "stream_already_open",
                            "message": (
                                "This socket already has an "
                                "active audio stream."
                            ),
                        },
                    })
                    continue

                request = (
                    AudioStreamReconnectRequest
                    .model_validate(
                        message.get("data", {})
                    )
                )
                audio_bridge.reconnect(
                    stream_id=request.stream_id,
                    session_id=session_id,
                    reconnect_token=(
                        request.reconnect_token
                    ),
                    generation=request.generation,
                    next_sequence=(
                        request.next_sequence
                    ),
                )
                _cancel_audio_expiry(
                    request.stream_id
                )
                active_stream_id = (
                    request.stream_id
                )
                await send_json({
                    "type": "stream_reconnected",
                    "data": (
                        audio_stream_manager
                        .state(
                            active_stream_id
                        )
                        .model_dump(mode="json")
                    ),
                })
                event_task = asyncio.create_task(
                    pump_events(
                        active_stream_id
                    )
                )
                continue

            if message_type == "chunk":
                if active_stream_id is None:
                    raise AudioReconnectError(
                        "open or reconnect an audio stream first"
                    )
                chunk = AudioChunkMessage.model_validate(
                    message.get("data", {})
                )
                result = await audio_bridge.push_chunk(
                    stream_id=active_stream_id,
                    chunk=chunk,
                )
                await send_json({
                    "type": "chunk_ack",
                    "data": result.model_dump(
                        mode="json"
                    ),
                })
                if (
                    result.vad is not None
                    and result.vad.auto_commit_recommended
                ):
                    await voice.vad_endpoint(
                        session_id,
                        result.vad,
                    )
                    await audio_bridge.commit(
                        stream_id=active_stream_id,
                    )
                    reason = (
                        "vad_max_duration"
                        if result.vad.state.value
                        == "max_duration"
                        else "vad_silence"
                    )
                    await send_json({
                        "type": "stream_committed",
                        "data": {
                            "stream_id": active_stream_id,
                            "reason": reason,
                            "vad": result.vad.model_dump(
                                mode="json"
                            ),
                        },
                    })
                continue

            if message_type == "commit":
                if active_stream_id is None:
                    raise AudioReconnectError(
                        "open or reconnect an audio stream first"
                    )
                await audio_bridge.commit(
                    stream_id=active_stream_id,
                )
                await send_json({
                    "type": "stream_committed",
                    "data": {
                        "stream_id": active_stream_id,
                    },
                })
                continue

            if message_type == "close":
                if active_stream_id is None:
                    await send_json({
                        "type": "stream_closed",
                        "data": None,
                    })
                    continue

                request = AudioStreamCloseRequest.model_validate(
                    message.get(
                        "data",
                        {
                            "stream_id": active_stream_id,
                        },
                    )
                )
                if (
                    request.stream_id
                    != active_stream_id
                ):
                    raise AudioReconnectError(
                        "close request references "
                        "a different audio stream"
                    )

                _cancel_audio_expiry(
                    active_stream_id
                )
                await audio_bridge.close(
                    stream_id=active_stream_id,
                    cancel_provider=(
                        request.cancel_provider
                    ),
                )
                if (
                    event_task is not None
                    and not event_task.done()
                ):
                    event_task.cancel()
                await send_json({
                    "type": "stream_closed",
                    "data": {
                        "stream_id": (
                            active_stream_id
                        ),
                    },
                })
                active_stream_id = None
                event_task = None
                continue

            await send_json({
                "type": "error",
                "error": {
                    "code": "unknown_audio_message",
                    "message": (
                        "Expected open, reconnect, chunk, commit, "
                        "close, or ping."
                    ),
                },
            })

    except WebSocketDisconnect:
        if active_stream_id is not None:
            _schedule_audio_expiry(
                active_stream_id
            )
        if (
            event_task is not None
            and not event_task.done()
        ):
            event_task.cancel()
        return
    except (
        AudioBackpressureError,
        AudioGenerationError,
        AudioReconnectError,
        AudioSequenceError,
        AudioStreamError,
        ProviderCircuitOpenError,
        StreamingSpeechUnavailableError,
        ValidationError,
        HTTPException,
    ) as exc:
        try:
            await send_json({
                "type": "error",
                "error": _audio_error_payload(exc),
            })
        finally:
            if active_stream_id is not None:
                _schedule_audio_expiry(
                    active_stream_id
                )
            if (
                event_task is not None
                and not event_task.done()
            ):
                event_task.cancel()
            await websocket.close(code=1008)
