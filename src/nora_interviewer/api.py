from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from .authorization import AccessPolicy, Permission, Principal
from .coding import CodingChallengeRequest
from .config import (
    build_brain,
    build_evidence_judge,
    build_principal_resolver,
)
from .counterfactual import CounterfactualReplayReport
from .feedback import CandidateFeedbackReport
from .models import (
    CandidateAppeal,
    CandidateAppealRequest,
    CandidateControlRequest,
    CandidateControlResult,
    CandidateResponse,
    CompetencyEvidence,
    CreateSession,
    EvidenceObservation,
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
from .service import InterviewService
from .storage import InMemoryStore
from .voice import (
    RealtimeVoiceCoordinator,
    TranscriptEvent,
    TtsLifecycleEvent,
    VoiceSessionState,
    VoiceTurnResult,
)
from .web import WEB_DIR, render_interview_room

store = InMemoryStore()
service = InterviewService(
    store=store,
    brain=build_brain(),
    evidence_judge=build_evidence_judge(),
)
voice = RealtimeVoiceCoordinator(service=service, store=store)
principal_resolver = build_principal_resolver()


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


app = FastAPI(
    title="Nora Interviewer",
    version="0.4.0-dev",
    description="Provider-neutral orchestration API for auditable AI interviews.",
)
app.mount("/assets", StaticFiles(directory=WEB_DIR), name="assets")


@app.get("/", response_class=HTMLResponse)
async def home() -> HTMLResponse:
    return HTMLResponse(render_interview_room())


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


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


@app.post("/v1/sessions/{session_id}/start", response_model=SessionStep)
async def start_session(
    session_id: str,
    principal: Principal = Depends(current_principal),
) -> SessionStep:
    await require_session_permission(
        session_id,
        principal,
        Permission.RUN_INTERVIEW,
    )
    return await service.start(session_id)


@app.post("/v1/sessions/{session_id}/responses", response_model=SessionStep)
async def submit_response(
    session_id: str,
    response: CandidateResponse,
    principal: Principal = Depends(current_principal),
) -> SessionStep:
    await require_session_permission(
        session_id,
        principal,
        Permission.RUN_INTERVIEW,
    )
    return await service.answer(session_id, response.text)


@app.post(
    "/v1/sessions/{session_id}/controls",
    response_model=CandidateControlResult,
)
async def candidate_control(
    session_id: str,
    request: CandidateControlRequest,
    principal: Principal = Depends(current_principal),
) -> CandidateControlResult:
    await require_session_permission(
        session_id,
        principal,
        Permission.CANDIDATE_CONTROL,
    )
    return await service.candidate_control(session_id, request)


@app.post(
    "/v1/sessions/{session_id}/coding-challenges",
    response_model=ToolInvocation,
    status_code=201,
)
async def open_coding_challenge(
    session_id: str,
    request: CodingChallengeRequest,
    principal: Principal = Depends(current_principal),
) -> ToolInvocation:
    await require_session_permission(
        session_id,
        principal,
        Permission.OPEN_TOOL,
    )
    return await service.open_coding_challenge(session_id, request)


@app.post(
    "/v1/sessions/{session_id}/tools",
    response_model=ToolInvocation,
    status_code=201,
)
async def open_tool(
    session_id: str,
    invocation: ToolInvocation,
    principal: Principal = Depends(current_principal),
) -> ToolInvocation:
    await require_session_permission(
        session_id,
        principal,
        Permission.OPEN_TOOL,
    )
    return await service.open_tool(session_id, invocation)


@app.post(
    "/v1/sessions/{session_id}/tools/{tool_id}/submit",
    response_model=ToolStep,
)
async def submit_tool(
    session_id: str,
    tool_id: str,
    request: ToolSubmissionRequest,
    principal: Principal = Depends(current_principal),
) -> ToolStep:
    await require_session_permission(
        session_id,
        principal,
        Permission.SUBMIT_TOOL,
    )
    return await service.submit_tool(session_id, tool_id, request)


@app.get("/v1/sessions/{session_id}", response_model=InterviewSession)
async def get_session(
    session_id: str,
    principal: Principal = Depends(current_principal),
) -> InterviewSession:
    return await require_session_permission(
        session_id,
        principal,
        Permission.READ_SESSION,
    )


@app.post(
    "/v1/sessions/{session_id}/corrections",
    response_model=TranscriptRevision,
    status_code=201,
)
async def correct_transcript(
    session_id: str,
    request: TranscriptCorrectionRequest,
    principal: Principal = Depends(current_principal),
) -> TranscriptRevision:
    await require_session_permission(
        session_id,
        principal,
        Permission.CORRECT_TRANSCRIPT,
    )
    return await service.correct_transcript(session_id, request)


@app.post(
    "/v1/sessions/{session_id}/appeals",
    response_model=CandidateAppeal,
    status_code=201,
)
async def submit_appeal(
    session_id: str,
    request: CandidateAppealRequest,
    principal: Principal = Depends(current_principal),
) -> CandidateAppeal:
    await require_session_permission(
        session_id,
        principal,
        Permission.SUBMIT_APPEAL,
    )
    return await service.submit_appeal(session_id, request)


@app.post(
    "/v1/sessions/{session_id}/integrity-signals",
    response_model=IntegritySignal,
    status_code=201,
)
async def submit_integrity_signal(
    session_id: str,
    request: IntegritySignalRequest,
    principal: Principal = Depends(current_principal),
) -> IntegritySignal:
    await require_session_permission(
        session_id,
        principal,
        Permission.WRITE_INTEGRITY,
    )
    return await service.submit_integrity_signal(session_id, request)


@app.post(
    "/v1/sessions/{session_id}/evidence",
    response_model=CompetencyEvidence,
)
async def observe_evidence(
    session_id: str,
    observation: EvidenceObservation,
    principal: Principal = Depends(current_principal),
) -> CompetencyEvidence:
    await require_session_permission(
        session_id,
        principal,
        Permission.WRITE_EVIDENCE,
    )
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
