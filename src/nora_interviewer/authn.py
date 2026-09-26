from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from fastapi import HTTPException

from .authorization import ActorRole, Principal, service_principal


class PrincipalResolver(Protocol):
    def resolve(
        self,
        headers: Mapping[str, str],
    ) -> Principal: ...


class DisabledPrincipalResolver:
    """Backward-compatible local/demo mode.

    Every request is treated as the trusted local service. Production deployments
    should not use this mode as their authorization boundary.
    """

    def resolve(
        self,
        headers: Mapping[str, str],
    ) -> Principal:
        return service_principal()


class DevHeaderPrincipalResolver:
    """Development-only role simulation through HTTP headers.

    This is intentionally named DEV header auth because client-controlled headers
    are not a production authentication mechanism.
    """

    principal_header = "x-nora-principal"
    role_header = "x-nora-role"
    candidate_ref_header = "x-nora-candidate-ref"

    def resolve(
        self,
        headers: Mapping[str, str],
    ) -> Principal:
        principal_id = str(
            headers.get(self.principal_header, "")
        ).strip()
        role_raw = str(
            headers.get(self.role_header, "")
        ).strip().lower()
        candidate_ref = str(
            headers.get(self.candidate_ref_header, "")
        ).strip() or None

        if not principal_id or not role_raw:
            raise HTTPException(
                status_code=401,
                detail=(
                    "Development authorization requires "
                    "X-Nora-Principal and X-Nora-Role"
                ),
            )

        try:
            role = ActorRole(role_raw)
        except ValueError as exc:
            raise HTTPException(
                status_code=401,
                detail=f"Unknown Nora role: {role_raw!r}",
            ) from exc

        if (
            role is ActorRole.CANDIDATE
            and candidate_ref is None
        ):
            raise HTTPException(
                status_code=401,
                detail=(
                    "Candidate development principal requires "
                    "X-Nora-Candidate-Ref"
                ),
            )

        return Principal(
            id=principal_id,
            role=role,
            candidate_ref=candidate_ref,
        )



class JwtJwksPrincipalResolver:
    """Production-oriented Bearer JWT resolver backed by a remote JWKS.

    Algorithms, issuer, and audience are application configuration. They are
    never inferred from attacker-controlled token headers or claims.
    """

    def __init__(
        self,
        *,
        jwks_url: str,
        issuer: str,
        audience: str,
        algorithms: tuple[str, ...] = ("RS256",),
        principal_claim: str = "sub",
        role_claim: str = "nora_role",
        candidate_ref_claim: str = "candidate_ref",
        leeway_seconds: float = 30.0,
        allow_service_role: bool = False,
    ) -> None:
        try:
            import jwt
        except ImportError as exc:
            raise RuntimeError(
                "JWT/JWKS authentication requires the 'auth' extra: "
                "pip install -e '.[auth]'"
            ) from exc

        if not jwks_url:
            raise ValueError("jwks_url is required")
        if not issuer:
            raise ValueError("issuer is required")
        if not audience:
            raise ValueError("audience is required")
        if not algorithms:
            raise ValueError("at least one JWT algorithm is required")

        allowed_asymmetric = {
            "RS256",
            "RS384",
            "RS512",
            "PS256",
            "PS384",
            "PS512",
            "ES256",
            "ES384",
            "ES512",
            "EdDSA",
        }
        unsupported = sorted(
            set(algorithms) - allowed_asymmetric
        )
        if unsupported:
            raise ValueError(
                "JWKS auth only allows configured asymmetric algorithms: "
                f"{unsupported}"
            )

        self.jwks_url = jwks_url
        self.issuer = issuer
        self.audience = audience
        self.algorithms = tuple(algorithms)
        self.principal_claim = principal_claim
        self.role_claim = role_claim
        self.candidate_ref_claim = candidate_ref_claim
        self.leeway_seconds = leeway_seconds
        self.allow_service_role = allow_service_role
        self._jwt = jwt
        self._jwks_client = jwt.PyJWKClient(
            jwks_url,
            cache_jwk_set=True,
            lifespan=300,
        )

    def _bearer_token(
        self,
        headers: Mapping[str, str],
    ) -> str:
        authorization = str(
            headers.get("authorization", "")
        ).strip()
        scheme, separator, token = authorization.partition(" ")
        if (
            not separator
            or scheme.casefold() != "bearer"
            or not token.strip()
        ):
            raise HTTPException(
                status_code=401,
                detail="Bearer access token is required",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return token.strip()

    def _decode_token(self, token: str) -> dict:
        try:
            signing_key = (
                self._jwks_client
                .get_signing_key_from_jwt(token)
            )
            claims = self._jwt.decode(
                token,
                key=signing_key.key,
                algorithms=list(self.algorithms),
                audience=self.audience,
                issuer=self.issuer,
                leeway=self.leeway_seconds,
                options={
                    "require": ["exp"],
                    "verify_signature": True,
                    "verify_exp": True,
                    "verify_aud": True,
                    "verify_iss": True,
                },
            )
        except Exception as exc:
            raise HTTPException(
                status_code=401,
                detail="Bearer token validation failed",
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc

        if not isinstance(claims, dict):
            raise HTTPException(
                status_code=401,
                detail="Bearer token claims are invalid",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return claims

    def _claims_to_principal(
        self,
        claims: Mapping[str, object],
    ) -> Principal:
        principal_id = claims.get(self.principal_claim)
        if not isinstance(principal_id, str) or not principal_id.strip():
            raise HTTPException(
                status_code=401,
                detail=(
                    "Bearer token is missing the configured "
                    f"principal claim {self.principal_claim!r}"
                ),
                headers={"WWW-Authenticate": "Bearer"},
            )

        role_value = claims.get(self.role_claim)
        if not isinstance(role_value, str):
            raise HTTPException(
                status_code=403,
                detail=(
                    "Bearer token is missing a valid Nora role claim "
                    f"{self.role_claim!r}"
                ),
            )
        try:
            role = ActorRole(role_value.strip().lower())
        except ValueError as exc:
            raise HTTPException(
                status_code=403,
                detail=f"Unknown Nora role in token: {role_value!r}",
            ) from exc

        if (
            role is ActorRole.SERVICE
            and not self.allow_service_role
        ):
            raise HTTPException(
                status_code=403,
                detail=(
                    "JWT service principals are disabled by configuration"
                ),
            )

        candidate_ref_value = claims.get(
            self.candidate_ref_claim
        )
        candidate_ref = (
            candidate_ref_value.strip()
            if isinstance(candidate_ref_value, str)
            and candidate_ref_value.strip()
            else None
        )
        if (
            role is ActorRole.CANDIDATE
            and candidate_ref is None
        ):
            raise HTTPException(
                status_code=403,
                detail=(
                    "Candidate token is missing the configured "
                    f"candidate reference claim "
                    f"{self.candidate_ref_claim!r}"
                ),
            )

        return Principal(
            id=principal_id.strip(),
            role=role,
            candidate_ref=candidate_ref,
        )

    def resolve(
        self,
        headers: Mapping[str, str],
    ) -> Principal:
        token = self._bearer_token(headers)
        claims = self._decode_token(token)
        return self._claims_to_principal(claims)



class OrganizationOidcPrincipalResolver(JwtJwksPrincipalResolver):
    """OIDC resolver with deployment-scoped organization and group mapping.

    The identity provider owns authentication. Nora maps trusted OIDC claims
    into its small internal role model without requiring a Nora-specific role
    claim to be minted by the provider.
    """

    def __init__(
        self,
        *,
        jwks_url: str,
        issuer: str,
        audience: str,
        organization_id: str,
        organization_claim: str = "org_id",
        groups_claim: str = "groups",
        role_mapping: Mapping[str, ActorRole],
        algorithms: tuple[str, ...] = ("RS256",),
        principal_claim: str = "sub",
        candidate_ref_claim: str = "candidate_ref",
        candidate_ref_from_subject: bool = True,
        leeway_seconds: float = 30.0,
    ) -> None:
        organization_id = organization_id.strip()
        organization_claim = organization_claim.strip()
        groups_claim = groups_claim.strip()
        if not organization_id:
            raise ValueError("organization_id is required")
        if not organization_claim:
            raise ValueError("organization_claim is required")
        if not groups_claim:
            raise ValueError("groups_claim is required")
        if not role_mapping:
            raise ValueError("role_mapping must not be empty")

        normalized_mapping: dict[str, ActorRole] = {}
        for external, role in role_mapping.items():
            key = str(external).strip()
            if not key:
                raise ValueError(
                    "OIDC role mapping contains an empty external value"
                )
            if role is ActorRole.SERVICE:
                raise ValueError(
                    "OIDC role mapping cannot grant the service role"
                )
            normalized_mapping[key] = role

        super().__init__(
            jwks_url=jwks_url,
            issuer=issuer,
            audience=audience,
            algorithms=algorithms,
            principal_claim=principal_claim,
            role_claim="__oidc_mapped_role__",
            candidate_ref_claim=candidate_ref_claim,
            leeway_seconds=leeway_seconds,
            allow_service_role=False,
        )
        self.organization_id = organization_id
        self.organization_claim = organization_claim
        self.groups_claim = groups_claim
        self.role_mapping = normalized_mapping
        self.candidate_ref_from_subject = candidate_ref_from_subject

    @staticmethod
    def _claim_values(value: object) -> list[str]:
        if isinstance(value, str):
            return [
                item.strip()
                for item in value.split(",")
                if item.strip()
            ]
        if isinstance(value, (list, tuple, set)):
            return [
                item.strip()
                for item in value
                if isinstance(item, str) and item.strip()
            ]
        return []

    def _claims_to_principal(
        self,
        claims: Mapping[str, object],
    ) -> Principal:
        organization = claims.get(self.organization_claim)
        organization_values = self._claim_values(organization)
        if self.organization_id not in organization_values:
            raise HTTPException(
                status_code=403,
                detail=(
                    "Bearer token is not scoped to the configured "
                    "Nora organization"
                ),
            )

        external_groups = self._claim_values(
            claims.get(self.groups_claim)
        )
        mapped_roles = {
            self.role_mapping[group]
            for group in external_groups
            if group in self.role_mapping
        }
        if not mapped_roles:
            raise HTTPException(
                status_code=403,
                detail=(
                    "Bearer token groups do not map to a Nora role"
                ),
            )
        if len(mapped_roles) > 1:
            raise HTTPException(
                status_code=403,
                detail=(
                    "Bearer token maps to multiple Nora roles; "
                    "role mapping must be unambiguous"
                ),
            )

        principal_id = claims.get(self.principal_claim)
        if not isinstance(principal_id, str) or not principal_id.strip():
            raise HTTPException(
                status_code=401,
                detail=(
                    "Bearer token is missing the configured "
                    f"principal claim {self.principal_claim!r}"
                ),
                headers={"WWW-Authenticate": "Bearer"},
            )

        role = next(iter(mapped_roles))
        candidate_ref_value = claims.get(
            self.candidate_ref_claim
        )
        candidate_ref = (
            candidate_ref_value.strip()
            if isinstance(candidate_ref_value, str)
            and candidate_ref_value.strip()
            else None
        )
        if (
            role is ActorRole.CANDIDATE
            and candidate_ref is None
            and self.candidate_ref_from_subject
        ):
            candidate_ref = principal_id.strip()

        if (
            role is ActorRole.CANDIDATE
            and candidate_ref is None
        ):
            raise HTTPException(
                status_code=403,
                detail=(
                    "Candidate OIDC identity does not provide a stable "
                    "candidate reference"
                ),
            )

        return Principal(
            id=principal_id.strip(),
            role=role,
            candidate_ref=candidate_ref,
            organization_id=self.organization_id,
        )
