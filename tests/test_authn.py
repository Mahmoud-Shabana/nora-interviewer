from fastapi import HTTPException

from nora_interviewer.authn import (
    DevHeaderPrincipalResolver,
    DisabledPrincipalResolver,
)
from nora_interviewer.authorization import ActorRole


def test_disabled_auth_returns_service_principal():
    principal = DisabledPrincipalResolver().resolve({})
    assert principal.role is ActorRole.SERVICE


def test_dev_header_resolver_builds_candidate_principal():
    principal = DevHeaderPrincipalResolver().resolve({
        "x-nora-principal": "candidate-user",
        "x-nora-role": "candidate",
        "x-nora-candidate-ref": "candidate-123",
    })

    assert principal.id == "candidate-user"
    assert principal.role is ActorRole.CANDIDATE
    assert principal.candidate_ref == "candidate-123"


def test_dev_header_candidate_requires_candidate_ref():
    resolver = DevHeaderPrincipalResolver()
    try:
        resolver.resolve({
            "x-nora-principal": "candidate-user",
            "x-nora-role": "candidate",
        })
        assert False, "expected HTTPException"
    except HTTPException as exc:
        assert exc.status_code == 401
        assert "X-Nora-Candidate-Ref" in str(exc.detail)


def test_dev_header_rejects_unknown_role():
    resolver = DevHeaderPrincipalResolver()
    try:
        resolver.resolve({
            "x-nora-principal": "someone",
            "x-nora-role": "super-admin",
        })
        assert False, "expected HTTPException"
    except HTTPException as exc:
        assert exc.status_code == 401
        assert "Unknown Nora role" in str(exc.detail)
