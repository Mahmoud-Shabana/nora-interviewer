from fastapi import HTTPException

from nora_interviewer.authorization import (
    AccessPolicy,
    ActorRole,
    Permission,
    Principal,
)
from nora_interviewer.models import InterviewSession


SESSION = InterviewSession(
    id="session",
    job_id="job",
    candidate_ref="candidate",
    locale="en",
)


def principal(role: ActorRole) -> Principal:
    return Principal(
        id=f"{role.value}-user",
        role=role,
        candidate_ref=(
            "candidate"
            if role is ActorRole.CANDIDATE
            else None
        ),
    )


def allowed(role: ActorRole, permission: Permission) -> bool:
    try:
        AccessPolicy.require(
            principal(role),
            permission,
            session=SESSION,
        )
        return True
    except HTTPException:
        return False


def test_recruiter_assigns_and_cancels_but_does_not_work_assignment():
    assert allowed(
        ActorRole.RECRUITER,
        Permission.ASSIGN_REVIEW,
    )
    assert allowed(
        ActorRole.RECRUITER,
        Permission.CANCEL_REVIEW_ASSIGNMENT,
    )
    assert not allowed(
        ActorRole.RECRUITER,
        Permission.WORK_REVIEW_ASSIGNMENT,
    )


def test_reviewer_works_assignment_but_cannot_manage_handoff():
    assert allowed(
        ActorRole.REVIEWER,
        Permission.WORK_REVIEW_ASSIGNMENT,
    )
    assert not allowed(
        ActorRole.REVIEWER,
        Permission.ASSIGN_REVIEW,
    )
    assert not allowed(
        ActorRole.REVIEWER,
        Permission.CANCEL_REVIEW_ASSIGNMENT,
    )


def test_candidate_has_no_review_assignment_permissions():
    for permission in (
        Permission.ASSIGN_REVIEW,
        Permission.WORK_REVIEW_ASSIGNMENT,
        Permission.CANCEL_REVIEW_ASSIGNMENT,
    ):
        assert not allowed(
            ActorRole.CANDIDATE,
            permission,
        )
