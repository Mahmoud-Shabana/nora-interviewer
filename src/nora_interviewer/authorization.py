from __future__ import annotations

from enum import Enum

from fastapi import HTTPException
from pydantic import Field

from .models import InterviewSession, StrictModel


class ActorRole(str, Enum):
    CANDIDATE = "candidate"
    RECRUITER = "recruiter"
    REVIEWER = "reviewer"
    SERVICE = "service"


class Permission(str, Enum):
    CREATE_JOB = "create_job"
    CREATE_SESSION = "create_session"
    RUN_INTERVIEW = "run_interview"
    CANDIDATE_CONTROL = "candidate_control"
    CORRECT_TRANSCRIPT = "correct_transcript"
    SUBMIT_APPEAL = "submit_appeal"
    READ_FEEDBACK = "read_feedback"
    OPEN_TOOL = "open_tool"
    SUBMIT_TOOL = "submit_tool"
    WRITE_EVIDENCE = "write_evidence"
    WRITE_INTEGRITY = "write_integrity"
    READ_SESSION = "read_session"
    READ_EVENTS = "read_events"
    READ_REPLAY = "read_replay"
    RUN_DECISION_REPLAY = "run_decision_replay"
    EXPORT_TRACE = "export_trace"
    USE_VOICE = "use_voice"
    RUN_RETENTION = "run_retention"
    READ_SYSTEM = "read_system"
    READ_REVIEW_QUEUE = "read_review_queue"
    READ_RECRUITER_REPORT = "read_recruiter_report"
    REVIEW_APPEAL = "review_appeal"
    REVIEW_INTEGRITY = "review_integrity"
    EXPORT_REVIEW_BUNDLE = "export_review_bundle"


class Principal(StrictModel):
    id: str = Field(min_length=1, max_length=256)
    role: ActorRole
    candidate_ref: str | None = Field(
        default=None,
        min_length=1,
        max_length=512,
    )


_ROLE_PERMISSIONS: dict[ActorRole, set[Permission]] = {
    ActorRole.CANDIDATE: {
        Permission.RUN_INTERVIEW,
        Permission.CANDIDATE_CONTROL,
        Permission.CORRECT_TRANSCRIPT,
        Permission.SUBMIT_APPEAL,
        Permission.READ_FEEDBACK,
        Permission.SUBMIT_TOOL,
        Permission.READ_SESSION,
        Permission.USE_VOICE,
    },
    ActorRole.RECRUITER: {
        Permission.CREATE_JOB,
        Permission.CREATE_SESSION,
        Permission.OPEN_TOOL,
        Permission.READ_SESSION,
        Permission.READ_EVENTS,
        Permission.READ_REPLAY,
        Permission.RUN_DECISION_REPLAY,
        Permission.EXPORT_TRACE,
        Permission.READ_SYSTEM,
        Permission.READ_REVIEW_QUEUE,
        Permission.READ_RECRUITER_REPORT,
        Permission.REVIEW_APPEAL,
        Permission.REVIEW_INTEGRITY,
        Permission.EXPORT_REVIEW_BUNDLE,
    },
    ActorRole.REVIEWER: {
        Permission.READ_SESSION,
        Permission.READ_EVENTS,
        Permission.READ_REPLAY,
        Permission.READ_FEEDBACK,
        Permission.WRITE_EVIDENCE,
        Permission.WRITE_INTEGRITY,
        Permission.EXPORT_TRACE,
        Permission.READ_SYSTEM,
        Permission.READ_REVIEW_QUEUE,
        Permission.READ_RECRUITER_REPORT,
        Permission.REVIEW_APPEAL,
        Permission.REVIEW_INTEGRITY,
        Permission.EXPORT_REVIEW_BUNDLE,
    },
    ActorRole.SERVICE: set(Permission),
}


class AccessPolicy:
    """Central authorization policy independent of HTTP authentication."""

    @staticmethod
    def require(
        principal: Principal,
        permission: Permission,
        *,
        session: InterviewSession | None = None,
    ) -> None:
        allowed = _ROLE_PERMISSIONS.get(
            principal.role,
            set(),
        )
        if permission not in allowed:
            raise HTTPException(
                status_code=403,
                detail=(
                    f"Role {principal.role.value!r} does not have "
                    f"permission {permission.value!r}"
                ),
            )

        if principal.role is ActorRole.CANDIDATE:
            if principal.candidate_ref is None:
                raise HTTPException(
                    status_code=403,
                    detail="Candidate principal is missing candidate_ref",
                )
            if session is not None:
                if principal.candidate_ref != session.candidate_ref:
                    raise HTTPException(
                        status_code=403,
                        detail=(
                            "Candidate principal cannot access "
                            "another candidate session"
                        ),
                    )


def service_principal() -> Principal:
    return Principal(
        id="local-service",
        role=ActorRole.SERVICE,
    )
