from fastapi import HTTPException

from nora_interviewer.authorization import (
    AccessPolicy,
    ActorRole,
    Permission,
    Principal,
)
from nora_interviewer.models import InterviewSession


def test_candidate_can_cancel_only_own_session():
    own = InterviewSession(
        id="own",
        job_id="job",
        candidate_ref="candidate-a",
        locale="en",
    )
    other = InterviewSession(
        id="other",
        job_id="job",
        candidate_ref="candidate-b",
        locale="en",
    )
    candidate = Principal(
        id="candidate-user",
        role=ActorRole.CANDIDATE,
        candidate_ref="candidate-a",
    )

    AccessPolicy.require(
        candidate,
        Permission.CANCEL_SESSION,
        session=own,
    )

    try:
        AccessPolicy.require(
            candidate,
            Permission.CANCEL_SESSION,
            session=other,
        )
        assert False, "expected ownership denial"
    except HTTPException as exc:
        assert exc.status_code == 403


def test_recruiter_can_cancel_but_reviewer_cannot():
    session = InterviewSession(
        id="session",
        job_id="job",
        candidate_ref="candidate",
        locale="en",
    )
    recruiter = Principal(
        id="recruiter",
        role=ActorRole.RECRUITER,
    )
    reviewer = Principal(
        id="reviewer",
        role=ActorRole.REVIEWER,
    )

    AccessPolicy.require(
        recruiter,
        Permission.CANCEL_SESSION,
        session=session,
    )

    try:
        AccessPolicy.require(
            reviewer,
            Permission.CANCEL_SESSION,
            session=session,
        )
        assert False, "expected reviewer cancellation denial"
    except HTTPException as exc:
        assert exc.status_code == 403
