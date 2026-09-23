from fastapi import HTTPException

from nora_interviewer.authorization import (
    AccessPolicy,
    ActorRole,
    Permission,
    Principal,
)
from nora_interviewer.models import InterviewSession


def test_candidate_cannot_read_recruiter_review_report():
    candidate = Principal(
        id="candidate-user",
        role=ActorRole.CANDIDATE,
        candidate_ref="candidate-1",
    )
    session = InterviewSession(
        id="session",
        job_id="job",
        candidate_ref="candidate-1",
        locale="en",
    )

    try:
        AccessPolicy.require(
            candidate,
            Permission.READ_RECRUITER_REPORT,
            session=session,
        )
        assert False, "expected reviewer report access to be denied"
    except HTTPException as exc:
        assert exc.status_code == 403


def test_recruiter_and_reviewer_can_read_review_layer():
    session = InterviewSession(
        id="session",
        job_id="job",
        candidate_ref="candidate-1",
        locale="en",
    )
    for role in (ActorRole.RECRUITER, ActorRole.REVIEWER):
        principal = Principal(
            id=f"{role.value}-user",
            role=role,
        )
        AccessPolicy.require(
            principal,
            Permission.READ_RECRUITER_REPORT,
            session=session,
        )
        AccessPolicy.require(
            principal,
            Permission.READ_REVIEW_QUEUE,
        )
