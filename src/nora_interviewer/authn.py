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
