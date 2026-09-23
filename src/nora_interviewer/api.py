from __future__ import annotations

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from .config import build_brain
from .models import CandidateResponse, CreateSession, InterviewSession, JobSpec, SessionStep, VoxRubricTrace
from .service import InterviewService
from .storage import InMemoryStore
from .web import WEB_DIR, render_interview_room

store = InMemoryStore()
service = InterviewService(store=store, brain=build_brain())
app = FastAPI(
    title="Nora Interviewer",
    version="0.2.0",
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


@app.get("/v1/sessions/{session_id}", response_model=InterviewSession)
async def get_session(session_id: str) -> InterviewSession:
    session = await store.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    return session


@app.get("/v1/sessions/{session_id}/voxrubric", response_model=VoxRubricTrace)
async def export_voxrubric(session_id: str) -> VoxRubricTrace:
    return await service.export_voxrubric(session_id)


@app.websocket("/v1/ws/interviews/{session_id}")
async def interview_socket(websocket: WebSocket, session_id: str) -> None:
    await websocket.accept()
    try:
        step = await service.start(session_id)
        if step.interviewer_turn:
            await websocket.send_json({"type": "interviewer_turn", "data": step.interviewer_turn.model_dump(mode="json")})
        while step.status.value != "completed":
            event = await websocket.receive_json()
            if event.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
                continue
            if event.get("type") != "candidate_text" or not str(event.get("text", "")).strip():
                await websocket.send_json({"type": "error", "error": "Expected {type: candidate_text, text: ...}"})
                continue
            await websocket.send_json({"type": "candidate_ack"})
            step = await service.answer(session_id, str(event["text"]).strip())
            if step.interviewer_turn:
                await websocket.send_json({"type": "interviewer_turn", "data": step.interviewer_turn.model_dump(mode="json")})
            if step.status.value == "completed":
                await websocket.send_json({"type": "interview_completed", "session_id": session_id})
                break
    except WebSocketDisconnect:
        return
    except HTTPException as exc:
        await websocket.send_json({"type": "error", "error": exc.detail})
        await websocket.close(code=1008)
