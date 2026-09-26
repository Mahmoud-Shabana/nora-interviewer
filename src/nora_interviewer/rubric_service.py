from __future__ import annotations

from fastapi import HTTPException

from .rubric_drafting import (
    RubricApprovalRequest,
    RubricApprovalResult,
    RubricDraft,
    RubricDraftRequest,
    RubricDrafter,
    RubricDraftError,
    approve_rubric_draft,
)
from .storage import Store, StoreConflictError


class RubricWorkflowService:
    """Persist AI-authored drafts and require explicit recruiter approval."""

    def __init__(
        self,
        *,
        store: Store,
        drafter: RubricDrafter,
    ) -> None:
        self.store = store
        self.drafter = drafter

    async def draft(
        self,
        request: RubricDraftRequest,
        *,
        organization_id: str | None = None,
    ) -> RubricDraft:
        draft = await self.drafter.draft(
            request
        )
        if organization_id is not None:
            draft = draft.model_copy(
                update={"organization_id": organization_id},
            )
        try:
            await self.store.put_rubric_draft(
                draft
            )
        except StoreConflictError as exc:
            raise HTTPException(
                status_code=409,
                detail="Rubric draft id collision",
            ) from exc
        return draft

    async def get(
        self,
        draft_id: str,
        *,
        organization_id: str | None = None,
    ) -> RubricDraft:
        draft = await self.store.get_rubric_draft(
            draft_id
        )
        if draft is None:
            raise HTTPException(
                status_code=404,
                detail="Rubric draft not found",
            )
        if (
            organization_id is not None
            and draft.organization_id != organization_id
        ):
            raise HTTPException(
                status_code=404,
                detail="Rubric draft not found",
            )
        return draft

    async def approve(
        self,
        draft_id: str,
        request: RubricApprovalRequest,
        *,
        approved_by: str,
        organization_id: str | None = None,
    ) -> RubricApprovalResult:
        draft = await self.get(
            draft_id,
            organization_id=organization_id,
        )
        try:
            approved_draft, job = (
                approve_rubric_draft(
                    draft,
                    request,
                    approved_by=approved_by,
                    organization_id=organization_id,
                )
            )
            await self.store.approve_rubric_draft(
                draft_id,
                approved_draft,
                job,
            )
        except RubricDraftError as exc:
            raise HTTPException(
                status_code=409,
                detail=str(exc),
            ) from exc
        except StoreConflictError as exc:
            raise HTTPException(
                status_code=409,
                detail=str(exc),
            ) from exc
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail="Rubric draft not found",
            ) from exc

        return RubricApprovalResult(
            draft=approved_draft,
            job=job,
        )
