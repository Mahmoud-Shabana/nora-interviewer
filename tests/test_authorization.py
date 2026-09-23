from fastapi import HTTPException

from nora_interviewer.authorization import (
    AccessPolicy,
    ActorRole,
    Permission,
    Principal,
    service_principal,
)
from nora_interviewer.models import InterviewSession


def test_service_principal_has_full_access():
    principal = service_principal()
    for permission in Permission:
        AccessPolicy.require(
            principal,
            permission,
        )


def test_candidate_cannot_open_recruiter_tool():
    principal = Principal(
        id="candidate-user",
        role=ActorRole.CANDIDATE,
        candidate_ref="candidate-1",
    )
    try:
        AccessPolicy.require(
            principal,
            Permission.OPEN_TOOL,
        )
        assert False, "expected HTTPException"
    except HTTPException as exc:
        assert exc.status_code == 403


def test_candidate_can_access_only_own_session():
    principal = Principal(
        id="candidate-user",
        role=ActorRole.CANDIDATE,
        candidate_ref="candidate-1",
    )
    own = InterviewSession(
        job_id="job",
        candidate_ref="candidate-1",
        locale="en",
    )
    other = InterviewSession(
        job_id="job",
        candidate_ref="candidate-2",
        locale="en",
    )

    AccessPolicy.require(
        principal,
        Permission.RUN_INTERVIEW,
        session=own,
    )

    try:
        AccessPolicy.require(
            principal,
            Permission.RUN_INTERVIEW,
            session=other,
        )
        assert False, "expected HTTPException"
    except HTTPException as exc:
        assert exc.status_code == 403
        assert "another candidate session" in str(exc.detail)


def test_reviewer_can_write_evidence_but_not_edit_transcript():
    reviewer = Principal(
        id="reviewer",
        role=ActorRole.REVIEWER,
    )

    AccessPolicy.require(
        reviewer,
        Permission.WRITE_EVIDENCE,
    )

    try:
        AccessPolicy.require(
            reviewer,
            Permission.CORRECT_TRANSCRIPT,
        )
        assert False, "expected HTTPException"
    except HTTPException as exc:
        assert exc.status_code == 403
