from __future__ import annotations

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from .coding import CodingChallengeRequest
from .config import build_brain
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
from .web import WEB_DIR, render_interview_room

store = InMemoryStore()
service = InterviewService(store=store, brain=build_brain())
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
async def create_job(job: JobSpec) -> JobSpec:
    return await service.create_job(job)


@app.post("/v1/sessions", response_model=InterviewSession, status_code=201)
async def create_session(request: CreateSession) -> InterviewSession:
    return await service.create_session(request)


@app.post("/v1/sessions/{session_id}/start", response_model=SessionStep)
async def start_session(session_id: str) -> SessionStep:
    return await service.start(session_id)


@app.post("/v1/sessions/{session_id}/responses", response_model=SessionStep)
async def submit_response(session_id: str, response: CandidateResponse) -> SessionStep:
    return await service.answer(session_id, response.text)


@app.post(
    "/v1/sessions/{session_id}/controls",
    response_model=CandidateControlResult,
)
async def candidate_control(
    session_id: str,
    request: CandidateControlRequest,
) -> CandidateControlResult:
    return await service.candidate_control(session_id, request)


@app.post(
    "/v1/sessions/{session_id}/coding-challenges",
    response_model=ToolInvocation,
    status_code=201,
)
async def open_coding_challenge(
    session_id: str,
    request: CodingChallengeRequest,
) -> ToolInvocation:
    return await service.open_coding_challenge(session_id, request)


@app.post(
    "/v1/sessions/{session_id}/tools",
    response_model=ToolInvocation,
    status_code=201,
)
async def open_tool(
    session_id: str,
    invocation: ToolInvocation,
) -> ToolInvocation:
    return await service.open_tool(session_id, invocation)


@app.post(
    "/v1/sessions/{session_id}/tools/{tool_id}/submit",
    response_model=ToolStep,
)
async def submit_tool(
    session_id: str,
    tool_id: str,
    request: ToolSubmissionRequest,
) -> ToolStep:
    return await service.submit_tool(session_id, tool_id, request)


@app.get("/v1/sessions/{session_id}", response_model=InterviewSession)
async def get_session(session_id: str) -> InterviewSession:
    session = await store.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    return session


@app.post(
    "/v1/sessions/{session_id}/corrections",
    response_model=TranscriptRevision,
    status_code=201,
)
async def correct_transcript(
    session_id: str,
    request: TranscriptCorrectionRequest,
) -> TranscriptRevision:
    return await service.correct_transcript(session_id, request)


@app.post(
    "/v1/sessions/{session_id}/appeals",
    response_model=CandidateAppeal,
    status_code=201,
)
async def submit_appeal(
    session_id: str,
    request: CandidateAppealRequest,
) -> CandidateAppeal:
    return await service.submit_appeal(session_id, request)


@app.post(
    "/v1/sessions/{session_id}/integrity-signals",
    response_model=IntegritySignal,
    status_code=201,
)
async def submit_integrity_signal(
    session_id: str,
    request: IntegritySignalRequest,
) -> IntegritySignal:
    return await service.submit_integrity_signal(session_id, request)


@app.post(
    "/v1/sessions/{session_id}/evidence",
    response_model=CompetencyEvidence,
)
async def observe_evidence(
    session_id: str,
    observation: EvidenceObservation,
) -> CompetencyEvidence:
    return await service.observe_evidence(session_id, observation)


@app.get(
    "/v1/sessions/{session_id}/feedback",
    response_model=CandidateFeedbackReport,
)
async def candidate_feedback(session_id: str) -> CandidateFeedbackReport:
    return await service.candidate_feedback(session_id)


@app.get(
    "/v1/sessions/{session_id}/events",
    response_model=list[InterviewEvent],
)
async def get_events(session_id: str) -> list[InterviewEvent]:
    return await service.events(session_id)


@app.get(
    "/v1/sessions/{session_id}/replay",
    response_model=ReplayState,
)
async def replay_session(session_id: str) -> ReplayState:
    return await service.replay(session_id)


@app.post(
    "/v1/sessions/{session_id}/decision-replay",
    response_model=CounterfactualReplayReport,
)
async def decision_replay(session_id: str) -> CounterfactualReplayReport:
    return await service.decision_replay(session_id)


@app.get("/v1/sessions/{session_id}/voxrubric", response_model=VoxRubricTrace)
async def export_voxrubric(session_id: str) -> VoxRubricTrace:
    return await service.export_voxrubric(session_id)


@app.websocket("/v1/ws/interviews/{session_id}")
async def interview_socket(websocket: WebSocket, session_id: str) -> None:
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

            if event_type != "candidate_text" or not str(event.get("text", "")).strip():
                await websocket.send_json(
                    {
                        "type": "error",
                        "error": (
                            "Expected candidate_text or candidate_control event."
                        ),
                    }
                )
                continue

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
