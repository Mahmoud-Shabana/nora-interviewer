from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SessionStatus(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class Speaker(str, Enum):
    INTERVIEWER = "interviewer"
    CANDIDATE = "candidate"
    SYSTEM = "system"


class QuestionLane(str, Enum):
    ANCHOR = "anchor"
    ADAPTIVE = "adaptive"
    CLOSING = "closing"


class EvidenceState(str, Enum):
    UNKNOWN = "unknown"
    CLAIMED = "claimed"
    DEMONSTRATED = "demonstrated"
    VERIFIED = "verified"
    CONTRADICTED = "contradicted"
    INSUFFICIENT = "insufficient_evidence"


class AppealStatus(str, Enum):
    PENDING = "pending"
    REVIEWED = "reviewed"


class IntegrityReviewStatus(str, Enum):
    PENDING = "pending"
    REVIEWED = "reviewed"


class IntegrityLevel(str, Enum):
    NONE = "none"
    IDENTITY = "identity"
    PASSIVE_SIGNALS = "passive_signals"
    SECURE = "secure"
    PROCTORED = "proctored"


class CandidateControlKind(str, Enum):
    REPEAT = "repeat"
    CLARIFY = "clarify"
    THINKING_TIME = "thinking_time"
    RESUME = "resume"
    CORRECT_LAST_ANSWER = "correct_last_answer"
    CANDIDATE_QUESTION = "candidate_question"


class ToolKind(str, Enum):
    CODING = "coding"
    CASE_STUDY = "case_study"
    WHITEBOARD = "whiteboard"
    DOCUMENT = "document"
    DATASET = "dataset"


class ToolStatus(str, Enum):
    OPEN = "open"
    SUBMITTED = "submitted"
    EVALUATED = "evaluated"
    CANCELLED = "cancelled"


class EventType(str, Enum):
    SESSION_CREATED = "session_created"
    INTERVIEW_STARTED = "interview_started"
    INTERVIEWER_TURN = "interviewer_turn"
    CANDIDATE_TURN = "candidate_turn"
    CANDIDATE_CONTROL = "candidate_control"
    TRANSCRIPT_CORRECTED = "transcript_corrected"
    APPEAL_SUBMITTED = "appeal_submitted"
    APPEAL_REVIEWED = "appeal_reviewed"
    EVIDENCE_OBSERVED = "evidence_observed"
    EVIDENCE_JUDGE_FAILED = "evidence_judge_failed"
    EVIDENCE_JUDGE_DISAGREEMENT = "evidence_judge_disagreement"
    EVIDENCE_JUDGE_RUN_RECORDED = "evidence_judge_run_recorded"
    EVIDENCE_SUPERSEDED = "evidence_superseded"
    INTEGRITY_SIGNAL = "integrity_signal"
    INTEGRITY_REVIEWED = "integrity_reviewed"
    TOOL_OPENED = "tool_opened"
    TOOL_SUBMITTED = "tool_submitted"
    TOOL_EVALUATED = "tool_evaluated"
    TOOL_CANCELLED = "tool_cancelled"
    VOICE_SPEECH_STARTED = "voice_speech_started"
    VOICE_TRANSCRIPT_PARTIAL = "voice_transcript_partial"
    VOICE_TRANSCRIPT_FINAL = "voice_transcript_final"
    VOICE_RESPONSE_READY = "voice_response_ready"
    VOICE_TTS_STARTED = "voice_tts_started"
    VOICE_TTS_COMPLETED = "voice_tts_completed"
    VOICE_TTS_CANCELLED = "voice_tts_cancelled"
    VOICE_BARGE_IN = "voice_barge_in"
    SESSION_COMPLETED = "session_completed"
    SESSION_CANCELLED = "session_cancelled"


class JobToolTemplate(StrictModel):
    template_id: str = Field(min_length=1, max_length=160)
    purpose: str = Field(min_length=2, max_length=1000)
    competency_ids: list[str] = Field(default_factory=list)


class Competency(StrictModel):
    id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    weight: float = Field(default=1.0, gt=0)
    anchor_question: str | None = Field(default=None, min_length=4)


class JobSpec(StrictModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    title: str = Field(min_length=2)
    description: str = Field(min_length=5)
    competencies: list[Competency] = Field(min_length=1)
    max_questions: int = Field(default=8, ge=1, le=30)
    anchor_ratio: float = Field(default=0.4, ge=0.0, le=1.0)
    tool_templates: list[JobToolTemplate] = Field(default_factory=list)
    max_tools: int = Field(default=2, ge=0, le=10)

    @model_validator(mode="after")
    def validate_job_contract(self) -> "JobSpec":
        ids = [c.id for c in self.competencies]
        if len(ids) != len(set(ids)):
            raise ValueError("competency ids must be unique")

        template_ids = [item.template_id for item in self.tool_templates]
        if len(template_ids) != len(set(template_ids)):
            raise ValueError("job tool template ids must be unique")

        known = set(ids)
        for item in self.tool_templates:
            unknown = sorted(set(item.competency_ids) - known)
            if unknown:
                raise ValueError(
                    f"tool template {item.template_id!r} references unknown competencies: {unknown}"
                )
        return self


class CreateSession(StrictModel):
    job_id: str
    candidate_ref: str = Field(min_length=1)
    locale: str = "en"
    consent_to_ai_interview: bool
    consent_to_transcript: bool
    integrity_level: IntegrityLevel = IntegrityLevel.NONE


class Turn(StrictModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    speaker: Speaker
    text: str
    parent_turn_id: str | None = None
    competency_tags: list[str] = Field(default_factory=list)
    response_latency_ms: int | None = Field(default=None, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CandidateControlRequest(StrictModel):
    kind: CandidateControlKind
    text: str | None = Field(default=None, max_length=5000)


class CandidateControlResult(StrictModel):
    kind: CandidateControlKind
    acknowledged: bool = True
    interviewer_turn: Turn | None = None
    target_turn_id: str | None = None
    pauses_interview: bool = False


class EvidenceItem(StrictModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    turn_id: str
    state: EvidenceState
    confidence: float = Field(ge=0.0, le=1.0)
    quote: str | None = Field(default=None, max_length=4000)
    note: str = Field(min_length=1)
    source: str = "interview"
    judge_run_id: str | None = Field(default=None, max_length=160)
    active: bool = True


class EvidenceJudgeRun(StrictModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    judge_id: str = Field(min_length=1, max_length=500)
    question_turn_id: str
    answer_turn_id: str
    competency_ids: list[str] = Field(default_factory=list)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    transcript_revision_count: int = Field(default=0, ge=0)
    observation_ids: list[str] = Field(default_factory=list)
    audit: dict[str, Any] = Field(default_factory=dict)
    error_type: str | None = Field(default=None, max_length=200)
    error: str | None = Field(default=None, max_length=2000)
    supersedes_run_id: str | None = None


class CompetencyEvidence(StrictModel):
    competency_id: str
    state: EvidenceState = EvidenceState.UNKNOWN
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    evidence: list[EvidenceItem] = Field(default_factory=list)


class TranscriptRevision(StrictModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    turn_id: str
    original_text: str
    corrected_text: str
    reason: str | None = None


class TranscriptCorrectionRequest(StrictModel):
    turn_id: str
    corrected_text: str = Field(min_length=1, max_length=20_000)
    reason: str | None = Field(default=None, max_length=1000)


class CandidateAppeal(StrictModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    message: str = Field(min_length=3, max_length=5000)
    turn_ids: list[str] = Field(default_factory=list)
    status: AppealStatus = AppealStatus.PENDING
    reviewed_by: str | None = Field(default=None, max_length=256)
    review_note: str | None = Field(default=None, max_length=5000)


class CandidateAppealRequest(StrictModel):
    message: str = Field(min_length=3, max_length=5000)
    turn_ids: list[str] = Field(default_factory=list)


class AppealReviewSubmission(StrictModel):
    note: str = Field(min_length=2, max_length=5000)


class AppealReviewRequest(StrictModel):
    reviewer_id: str = Field(min_length=1, max_length=256)
    note: str = Field(min_length=2, max_length=5000)


class IntegritySignal(StrictModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    kind: str = Field(min_length=2, max_length=120)
    confidence: float = Field(ge=0.0, le=1.0)
    note: str = Field(min_length=2, max_length=2000)
    evidence: dict[str, Any] = Field(default_factory=dict)
    requires_human_review: bool = True
    review_status: IntegrityReviewStatus = IntegrityReviewStatus.PENDING
    reviewed_by: str | None = Field(default=None, max_length=256)
    review_note: str | None = Field(default=None, max_length=5000)


class IntegritySignalRequest(StrictModel):
    kind: str = Field(min_length=2, max_length=120)
    confidence: float = Field(ge=0.0, le=1.0)
    note: str = Field(min_length=2, max_length=2000)
    evidence: dict[str, Any] = Field(default_factory=dict)


class IntegrityReviewSubmission(StrictModel):
    note: str = Field(min_length=2, max_length=5000)


class IntegrityReviewRequest(StrictModel):
    reviewer_id: str = Field(min_length=1, max_length=256)
    note: str = Field(min_length=2, max_length=5000)


class ToolInvocation(StrictModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    kind: ToolKind
    title: str = Field(min_length=2, max_length=200)
    instructions: str = Field(min_length=2, max_length=20_000)
    competency_tags: list[str] = Field(default_factory=list)
    status: ToolStatus = ToolStatus.OPEN
    payload: dict[str, Any] = Field(default_factory=dict)
    opened_from_turn_id: str | None = None


class ToolSubmissionRequest(StrictModel):
    content: dict[str, Any] = Field(default_factory=dict)


class ToolSubmission(StrictModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    tool_id: str
    content: dict[str, Any] = Field(default_factory=dict)


class ToolEvaluation(StrictModel):
    tool_id: str
    submission_id: str
    passed: bool | None = None
    score: float | None = Field(default=None, ge=0.0, le=1.0)
    summary: str = Field(min_length=1)
    evidence: dict[str, Any] = Field(default_factory=dict)


class ToolStep(StrictModel):
    tool_id: str
    evaluation: ToolEvaluation
    interviewer_turn: Turn | None = None
    next_tool_invocation: ToolInvocation | None = None
    status: SessionStatus


class InterviewEvent(StrictModel):
    seq: int = Field(ge=1)
    type: EventType
    turn_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    hash_version: int | None = Field(
        default=None,
        ge=1,
    )
    prev_hash: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    event_hash: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )


class InterviewSession(StrictModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    version: int = Field(default=0, ge=0)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    completed_at: datetime | None = None
    cancelled_at: datetime | None = None
    cancellation_reason: str | None = Field(default=None, max_length=2000)
    job_id: str
    candidate_ref: str
    locale: str
    integrity_level: IntegrityLevel = IntegrityLevel.NONE
    status: SessionStatus = SessionStatus.CREATED
    paused: bool = False
    turns: list[Turn] = Field(default_factory=list)
    covered_competencies: list[str] = Field(default_factory=list)
    followups_by_competency: dict[str, int] = Field(default_factory=dict)
    asked_anchor_competencies: list[str] = Field(default_factory=list)
    asked_questions: int = 0
    evidence_graph: dict[str, CompetencyEvidence] = Field(default_factory=dict)
    evidence_judge_runs: list[EvidenceJudgeRun] = Field(default_factory=list)
    transcript_revisions: list[TranscriptRevision] = Field(default_factory=list)
    appeals: list[CandidateAppeal] = Field(default_factory=list)
    integrity_signals: list[IntegritySignal] = Field(default_factory=list)
    tools: list[ToolInvocation] = Field(default_factory=list)
    tool_submissions: list[ToolSubmission] = Field(default_factory=list)
    tool_evaluations: list[ToolEvaluation] = Field(default_factory=list)
    events: list[InterviewEvent] = Field(default_factory=list)


class CandidateResponse(StrictModel):
    text: str = Field(min_length=1, max_length=20_000)


class CancelSessionRequest(StrictModel):
    reason: str = Field(min_length=2, max_length=2000)


class AgentToolRequest(StrictModel):
    template_id: str = Field(min_length=1, max_length=160)


class AgentDecision(StrictModel):
    text: str
    competency_tags: list[str] = Field(default_factory=list)
    parent_turn_id: str | None = None
    completes_interview: bool = False
    tool_request: AgentToolRequest | None = None
    reason: str


class SessionStep(StrictModel):
    session_id: str
    status: SessionStatus
    interviewer_turn: Turn | None = None
    tool_invocation: ToolInvocation | None = None


class EvidenceObservation(StrictModel):
    competency_id: str
    turn_id: str
    state: EvidenceState
    confidence: float = Field(ge=0.0, le=1.0)
    quote: str | None = Field(default=None, max_length=4000)
    note: str = Field(min_length=1)
    source: str = Field(default="evaluator", min_length=1, max_length=160)
    judge_run_id: str | None = Field(default=None, max_length=160)


class VoxRubricTrace(StrictModel):
    session_id: str
    role: str
    locale: str
    turns: list[dict[str, Any]]
    scorecards: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
