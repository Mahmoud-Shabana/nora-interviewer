import asyncio

import pytest

from nora_interviewer.models import Competency
from nora_interviewer.rubric_drafting import (
    RubricApprovalRequest,
    RubricDraft,
    RubricDraftCompetency,
    approve_rubric_draft,
)
from nora_interviewer.sqlite_store import SqliteStore
from nora_interviewer.storage import (
    InMemoryStore,
    StoreConflictError,
)


def run(coro):
    return asyncio.run(coro)


def draft():
    return RubricDraft(
        id="draft-1",
        title="Backend Engineer",
        job_description=(
            "Build reliable Python services and diagnose production incidents."
        ),
        locale="en",
        competencies=[
            RubricDraftCompetency(
                id="debugging",
                description="Diagnoses production failures using evidence.",
                anchor_question=(
                    "Describe an incident and the evidence you used."
                ),
                rationale="Reliability is role-related.",
                observable_evidence=["Diagnostic evidence"],
            ),
            RubricDraftCompetency(
                id="systems",
                description="Reasons about system reliability trade-offs.",
                anchor_question=(
                    "Describe a reliability trade-off you made."
                ),
                rationale="Architecture is role-related.",
                observable_evidence=["Trade-off reasoning"],
            ),
            RubricDraftCompetency(
                id="python",
                description="Builds maintainable Python services.",
                anchor_question=(
                    "Describe a Python service you owned."
                ),
                rationale="Python is role-related.",
                observable_evidence=["Implementation ownership"],
            ),
        ],
        max_questions=10,
        anchor_ratio=0.4,
        drafter_id="fake:model",
    )


def approval_request():
    return RubricApprovalRequest(
        job_id="job-approved",
        title="Backend Engineer",
        description=(
            "Build reliable Python services and diagnose production incidents."
        ),
        competencies=[
            Competency(
                id="debugging",
                description=(
                    "Diagnoses production failures using grounded evidence."
                ),
                weight=1.2,
                anchor_question=(
                    "Describe an incident and show how evidence "
                    "changed your diagnosis."
                ),
            ),
            Competency(
                id="systems",
                description="Reasons about system reliability trade-offs.",
                anchor_question=(
                    "Describe a reliability trade-off you made."
                ),
            ),
            Competency(
                id="python",
                description="Builds maintainable Python services.",
                anchor_question=(
                    "Describe a Python service you owned."
                ),
            ),
        ],
        max_questions=10,
        anchor_ratio=0.4,
        review_note="Reviewed by recruiting.",
    )


@pytest.mark.parametrize("backend", ["memory", "sqlite"])
def test_rubric_draft_roundtrip_and_atomic_approval(
    backend,
    tmp_path,
):
    async def scenario():
        store = (
            InMemoryStore()
            if backend == "memory"
            else SqliteStore(tmp_path / "nora.db")
        )
        source = draft()
        await store.put_rubric_draft(source)

        loaded = await store.get_rubric_draft(source.id)
        assert loaded is not None
        assert loaded.activation_status == "draft_only"
        assert loaded.approved_job_id is None

        approved_draft, job = approve_rubric_draft(
            loaded,
            approval_request(),
            approved_by="recruiter-1",
        )
        await store.approve_rubric_draft(
            source.id,
            approved_draft,
            job,
        )

        persisted_draft = await store.get_rubric_draft(
            source.id
        )
        persisted_job = await store.get_job(job.id)

        assert persisted_draft is not None
        assert persisted_job is not None
        assert persisted_draft.activation_status == "approved"
        assert persisted_draft.approved_job_id == job.id
        assert persisted_draft.approved_by == "recruiter-1"
        assert (
            persisted_job.rubric_provenance.draft_id
            == source.id
        )
        assert (
            persisted_job.rubric_provenance.approved_by
            == "recruiter-1"
        )
        assert (
            persisted_job.rubric_provenance.edit_summary[
                "competencies_modified"
            ]
            == ["debugging"]
        )

        with pytest.raises(StoreConflictError):
            await store.approve_rubric_draft(
                source.id,
                approved_draft,
                job,
            )

        await store.close()

    run(scenario())


def test_memory_store_rejects_duplicate_draft_ids():
    async def scenario():
        store = InMemoryStore()
        source = draft()
        await store.put_rubric_draft(source)
        with pytest.raises(
            StoreConflictError,
            match="already exists",
        ):
            await store.put_rubric_draft(source)

    run(scenario())
