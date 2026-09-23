import pytest
from fastapi import HTTPException

from nora_interviewer.authn import JwtJwksPrincipalResolver
from nora_interviewer.authorization import ActorRole


def resolver(**overrides):
    values = {
        "jwks_url": "https://identity.example/.well-known/jwks.json",
        "issuer": "https://identity.example/",
        "audience": "https://api.nora.example",
        "algorithms": ("RS256",),
    }
    values.update(overrides)
    return JwtJwksPrincipalResolver(**values)


def test_jwt_resolver_requires_bearer_authorization_header():
    auth = resolver()

    with pytest.raises(HTTPException) as exc:
        auth.resolve({})

    assert exc.value.status_code == 401
    assert exc.value.headers["WWW-Authenticate"] == "Bearer"


def test_jwks_mode_rejects_symmetric_algorithms():
    with pytest.raises(ValueError, match="asymmetric"):
        resolver(algorithms=("HS256",))


def test_candidate_claim_mapping_requires_candidate_reference():
    auth = resolver()

    principal = auth._claims_to_principal({
        "sub": "candidate-user",
        "nora_role": "candidate",
        "candidate_ref": "candidate-123",
    })
    assert principal.role is ActorRole.CANDIDATE
    assert principal.id == "candidate-user"
    assert principal.candidate_ref == "candidate-123"

    with pytest.raises(HTTPException) as exc:
        auth._claims_to_principal({
            "sub": "candidate-user",
            "nora_role": "candidate",
        })
    assert exc.value.status_code == 403


def test_service_role_is_denied_by_default():
    auth = resolver()

    with pytest.raises(HTTPException) as exc:
        auth._claims_to_principal({
            "sub": "machine-client",
            "nora_role": "service",
        })

    assert exc.value.status_code == 403
    assert "disabled" in str(exc.value.detail)


def test_service_role_can_be_enabled_explicitly():
    auth = resolver(allow_service_role=True)

    principal = auth._claims_to_principal({
        "sub": "machine-client",
        "nora_role": "service",
    })
    assert principal.role is ActorRole.SERVICE


def test_resolve_maps_verified_claims_to_principal_without_trusting_headers(monkeypatch):
    auth = resolver()

    monkeypatch.setattr(
        auth,
        "_decode_token",
        lambda token: {
            "sub": "recruiter-1",
            "nora_role": "recruiter",
            "exp": 9999999999,
        },
    )

    principal = auth.resolve({
        "authorization": "Bearer signed.jwt.value",
        "x-nora-role": "service",
    })

    assert principal.id == "recruiter-1"
    assert principal.role is ActorRole.RECRUITER
