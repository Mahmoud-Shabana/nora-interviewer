from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from pydantic import ValidationError
from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from .audio_stream_manager import AudioStreamManager
from .authorization import AccessPolicy, Permission, Principal
from .capabilities import SystemCapabilities, describe_capabilities
from .coding import CodingChallengeRequest
from .config import (
    build_brain,
    build_evidence_judge,
    build_principal_resolver,
    build_store,
    build_streaming_speech_provider,
)
from .counterfactual import CounterfactualReplayReport
from .feedback import CandidateFeedbackReport
from .models import (
    AppealReviewRequest,
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
    ReviewDashboardSummary,
    ReviewQueueItem,
)
from .review_bundle import ReviewBundle, build_review_bundle
from .review_service import ReviewService
from .providers.streaming_speech import StreamingSpeechUnavailableError
from .retention import RetentionManager, RetentionReport, RetentionRequest
from .service import InterviewService
from .voice import (
    RealtimeVoiceCoordinator,
    TranscriptEvent,
    TtsLifecycleEvent,
    VoiceSessionState,
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
from .voice_stream_bridge import (
    StreamingFinalTranscript,
    StreamingPartialTranscript,
    StreamingProviderFailure,
    VoiceStreamBridge,
)
from .web import WEB_DIR, render_interview_room, render_review_console

API_VERSION = "0.4.0-dev"

store = build_store()
service = InterviewService(
    store=store,
    brain=build_brain(),
    evidence_judge=build_evidence_judge(),
)
voice = RealtimeVoiceCoordinator(service=service, store=store)
principal_resolver = build_principal_resolver()
retention = RetentionManager(store)
review_service = ReviewService(store=store)
streaming_speech_provider = build_streaming_speech_provider()
audio_stream_manager = AudioStreamManager()
audio_bridge = VoiceStreamBridge(
    manager=audio_stream_manager,
    provider=streaming_speech_provider,
    voice=voice,
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
    try:
        yield
    finally:
        for task in list(_audio_expiry_tasks.values()):
            task.cancel()
        await audio_bridge.close_all()
        await store.close()


app = FastAPI(
    title="Nora Interviewer",
    version=API_VERSION,
    description="Provider-neutral orchestration API for auditable AI interviews.",
    lifespan=lifespan,
)
app.mount("/assets", StaticFiles(directory=WEB_DIR), name="assets")


@app.get("/", response_class=HTMLResponse)
async def home() -> HTMLResponse:
    return HTMLResponse(render_interview_room())


@app.get("/review", response_class=HTMLResponse)
async def review_console() -> HTMLResponse:
    return HTMLResponse(render_review_console())


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
    return await review_service.summary()


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
    return await service.create_job(job)


@app.post("/v1/sessions", response_model=InterviewSession, status_code=201)
async def create_session(
    request: CreateSession,
    principal: Principal = Depends(current_principal),
) -> InterviewSession:
    require_global_permission(
        principal,
        Permission.CREATE_SESSION,
    )
    return await service.create_session(request)


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
    return await voice.speech_started(session_id)


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

            if event_type == "voice_speech_started":
                AccessPolicy.require(
                    principal,
                    Permission.USE_VOICE,
                    session=session,
                )
                state = await voice.speech_started(session_id)
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
                            "Expected candidate_text, candidate_control, or voice event."
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


@app.websocket("/v1/ws/audio/{session_id}")
async def audio_socket(
    websocket: WebSocket,
    session_id: str,
) -> None:
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
                        "Expected open, reconnect, chunk, "
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
