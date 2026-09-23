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
    ) -> RubricDraft:
        draft = await self.drafter.draft(
            request
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
    ) -> RubricDraft:
        draft = await self.store.get_rubric_draft(
            draft_id
        )
        if draft is None:
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
    ) -> RubricApprovalResult:
        draft = await self.get(
            draft_id
        )
        try:
            approved_draft, job = (
                approve_rubric_draft(
                    draft,
                    request,
                    approved_by=approved_by,
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
