import pytest

from nora_interviewer.authn import JwtJwksPrincipalResolver
from nora_interviewer.config import build_principal_resolver


def clear(monkeypatch):
    for name in [
        "NORA_AUTH_MODE",
        "NORA_AUTH_JWKS_URL",
        "NORA_AUTH_ISSUER",
        "NORA_AUTH_AUDIENCE",
        "NORA_AUTH_ALGORITHMS",
        "NORA_AUTH_ALLOW_INSECURE_JWKS",
        "NORA_AUTH_ALLOW_SERVICE_ROLE",
        "NORA_AUTH_LEEWAY_SECONDS",
        "NORA_AUTH_PRINCIPAL_CLAIM",
        "NORA_AUTH_ROLE_CLAIM",
        "NORA_AUTH_CANDIDATE_REF_CLAIM",
    ]:
        monkeypatch.delenv(name, raising=False)


def test_jwt_jwks_mode_requires_identity_metadata(monkeypatch):
    clear(monkeypatch)
    monkeypatch.setenv("NORA_AUTH_MODE", "jwt-jwks")

    with pytest.raises(RuntimeError, match="JWKS_URL"):
        build_principal_resolver()


def test_jwt_jwks_mode_builds_production_resolver(monkeypatch):
    clear(monkeypatch)
    monkeypatch.setenv("NORA_AUTH_MODE", "jwt-jwks")
    monkeypatch.setenv(
        "NORA_AUTH_JWKS_URL",
        "https://identity.example/.well-known/jwks.json",
    )
    monkeypatch.setenv(
        "NORA_AUTH_ISSUER",
        "https://identity.example/",
    )
    monkeypatch.setenv(
        "NORA_AUTH_AUDIENCE",
        "https://api.nora.example",
    )
    monkeypatch.setenv(
        "NORA_AUTH_ALGORITHMS",
        "RS256,PS256",
    )
    monkeypatch.setenv(
        "NORA_AUTH_LEEWAY_SECONDS",
        "15",
    )

    auth = build_principal_resolver()

    assert isinstance(auth, JwtJwksPrincipalResolver)
    assert auth.algorithms == ("RS256", "PS256")
    assert auth.leeway_seconds == 15
    assert auth.allow_service_role is False


def test_jwt_jwks_mode_rejects_plain_http_by_default(monkeypatch):
    clear(monkeypatch)
    monkeypatch.setenv("NORA_AUTH_MODE", "jwt-jwks")
    monkeypatch.setenv(
        "NORA_AUTH_JWKS_URL",
        "http://identity.local/jwks.json",
    )
    monkeypatch.setenv("NORA_AUTH_ISSUER", "http://identity.local/")
    monkeypatch.setenv("NORA_AUTH_AUDIENCE", "nora")

    with pytest.raises(RuntimeError, match="https"):
        build_principal_resolver()
