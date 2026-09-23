from __future__ import annotations

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


class Speaker(str, Enum):
    INTERVIEWER = "interviewer"
    CANDIDATE = "candidate"
    SYSTEM = "system"


class Competency(StrictModel):
    id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    weight: float = Field(default=1.0, gt=0)


class JobSpec(StrictModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    title: str = Field(min_length=2)
    description: str = Field(min_length=5)
    competencies: list[Competency] = Field(min_length=1)
    max_questions: int = Field(default=8, ge=1, le=30)

    @model_validator(mode="after")
    def unique_competencies(self) -> "JobSpec":
        ids = [c.id for c in self.competencies]
        if len(ids) != len(set(ids)):
            raise ValueError("competency ids must be unique")
        return self


class CreateSession(StrictModel):
    job_id: str
    candidate_ref: str = Field(min_length=1)
    locale: str = "en"
    consent_to_ai_interview: bool
    consent_to_transcript: bool


class Turn(StrictModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    speaker: Speaker
    text: str
    parent_turn_id: str | None = None
    competency_tags: list[str] = Field(default_factory=list)
    response_latency_ms: int | None = Field(default=None, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class InterviewSession(StrictModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    job_id: str
    candidate_ref: str
    locale: str
    status: SessionStatus = SessionStatus.CREATED
    turns: list[Turn] = Field(default_factory=list)
    covered_competencies: list[str] = Field(default_factory=list)
    followups_by_competency: dict[str, int] = Field(default_factory=dict)
    asked_questions: int = 0


class CandidateResponse(StrictModel):
    text: str = Field(min_length=1, max_length=20_000)


class AgentDecision(StrictModel):
    text: str
    competency_tags: list[str] = Field(default_factory=list)
    parent_turn_id: str | None = None
    completes_interview: bool = False
    reason: str


class SessionStep(StrictModel):
    session_id: str
    status: SessionStatus
    interviewer_turn: Turn | None = None


class VoxRubricTrace(StrictModel):
    session_id: str
    role: str
    locale: str
    turns: list[dict[str, Any]]
    scorecards: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
