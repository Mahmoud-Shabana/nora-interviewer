from fastapi.testclient import TestClient

import nora_interviewer.api as api
from nora_interviewer.authn import (
    DevHeaderPrincipalResolver,
)
from nora_interviewer.rubric_drafting import (
    RubricDraft,
    RubricDraftCompetency,
)
from nora_interviewer.rubric_service import (
    RubricWorkflowService,
)
from nora_interviewer.storage import InMemoryStore


class FakeDrafter:
    drafter_id = "fake:drafter"

    async def draft(self, request):
        return RubricDraft(
            title=request.title,
            job_description=request.job_description,
            locale=request.locale,
            competencies=[
                RubricDraftCompetency(
                    id="debugging",
                    description=(
                        "Diagnoses production failures using evidence."
                    ),
                    anchor_question=(
                        "Describe a production incident and your evidence."
                    ),
                    rationale=(
                        "Production reliability is role-related."
                    ),
                    observable_evidence=[
                        "Concrete diagnostic evidence"
                    ],
                ),
                RubricDraftCompetency(
                    id="systems",
                    description=(
                        "Reasons about systems trade-offs and reliability."
                    ),
                    anchor_question=(
                        "Describe a system trade-off you made."
                    ),
                    rationale=(
                        "Architecture choices are role-related."
                    ),
                    observable_evidence=[
                        "Explicit trade-off reasoning"
                    ],
                ),
                RubricDraftCompetency(
                    id="python",
                    description=(
                        "Builds maintainable Python services."
                    ),
                    anchor_question=(
                        "Describe a Python service you owned."
                    ),
                    rationale=(
                        "Python engineering is role-related."
                    ),
                    observable_evidence=[
                        "Implementation ownership"
                    ],
                ),
            ],
            max_questions=request.max_questions,
            anchor_ratio=request.anchor_ratio,
            drafter_id=self.drafter_id,
        )


def configure_test_workflow(monkeypatch):
    store = InMemoryStore()
    workflow = RubricWorkflowService(
        store=store,
        drafter=FakeDrafter(),
    )
    monkeypatch.setattr(
        api,
        "principal_resolver",
        DevHeaderPrincipalResolver(),
    )
    monkeypatch.setattr(
        api,
        "rubric_service",
        workflow,
    )
    return store


def recruiter_headers():
    return {
        "X-Nora-Principal": "recruiter-1",
        "X-Nora-Role": "recruiter",
    }


def candidate_headers():
    return {
        "X-Nora-Principal": "candidate",
        "X-Nora-Role": "candidate",
        "X-Nora-Candidate-Ref": "candidate-1",
    }


def draft_payload():
    return {
        "title": "Backend Engineer",
        "job_description": (
            "Build Python services and diagnose production incidents."
        ),
        "competency_count": 3,
    }


def test_recruiter_can_persist_draft_but_candidate_cannot(monkeypatch):
    configure_test_workflow(monkeypatch)
    client = TestClient(api.app)

    candidate = client.post(
        "/v1/rubrics/draft",
        json=draft_payload(),
        headers=candidate_headers(),
    )
    assert candidate.status_code == 403

    recruiter = client.post(
        "/v1/rubrics/draft",
        json=draft_payload(),
        headers=recruiter_headers(),
    )
    assert recruiter.status_code == 200
    body = recruiter.json()
    assert body["activation_status"] == "draft_only"
    assert body["drafter_id"] == "fake:drafter"
    assert len(body["competencies"]) == 3
    assert "hire" not in body
    assert "recommendation" not in body

    retrieved = client.get(
        f"/v1/rubrics/drafts/{body['id']}",
        headers=recruiter_headers(),
    )
    assert retrieved.status_code == 200
    assert retrieved.json()["id"] == body["id"]


def test_recruiter_approval_creates_job_with_server_owned_provenance(monkeypatch):
    store = configure_test_workflow(monkeypatch)
    client = TestClient(api.app)

    draft = client.post(
        "/v1/rubrics/draft",
        json=draft_payload(),
        headers=recruiter_headers(),
    ).json()

    competencies = [
        {
            "id": item["id"],
            "description": (
                item["description"] + " Reviewed."
                if item["id"] == "debugging"
                else item["description"]
            ),
            "weight": item["weight"],
            "anchor_question": item["anchor_question"],
        }
        for item in draft["competencies"]
    ]

    approved = client.post(
        f"/v1/rubrics/drafts/{draft['id']}/approve",
        json={
            "title": draft["title"],
            "description": draft["job_description"],
            "competencies": competencies,
            "max_questions": draft["max_questions"],
            "anchor_ratio": draft["anchor_ratio"],
            "tool_templates": [],
            "max_tools": 2,
            "review_note": "Reviewed anchors and competency scope.",
        },
        headers=recruiter_headers(),
    )
    assert approved.status_code == 200

    body = approved.json()
    assert body["draft"]["activation_status"] == "approved"
    job = body["job"]
    provenance = job["rubric_provenance"]
    assert provenance["draft_id"] == draft["id"]
    assert provenance["drafter_id"] == "fake:drafter"
    assert provenance["approved_by"] == "recruiter-1"
    assert provenance["review_note"] == (
        "Reviewed anchors and competency scope."
    )
    assert provenance["edit_summary"][
        "competencies_modified"
    ] == ["debugging"]

    persisted_job = __import__("asyncio").run(
        store.get_job(job["id"])
    )
    assert persisted_job is not None
    assert (
        persisted_job.rubric_provenance.approved_by
        == "recruiter-1"
    )

    second = client.post(
        f"/v1/rubrics/drafts/{draft['id']}/approve",
        json={
            "title": draft["title"],
            "description": draft["job_description"],
            "competencies": competencies,
            "max_questions": draft["max_questions"],
            "anchor_ratio": draft["anchor_ratio"],
            "tool_templates": [],
            "max_tools": 2,
        },
        headers=recruiter_headers(),
    )
    assert second.status_code == 409


def test_candidate_cannot_read_or_approve_rubric_draft(monkeypatch):
    configure_test_workflow(monkeypatch)
    client = TestClient(api.app)

    draft = client.post(
        "/v1/rubrics/draft",
        json=draft_payload(),
        headers=recruiter_headers(),
    ).json()

    assert client.get(
        f"/v1/rubrics/drafts/{draft['id']}",
        headers=candidate_headers(),
    ).status_code == 403

    response = client.post(
        f"/v1/rubrics/drafts/{draft['id']}/approve",
        json={
            "title": draft["title"],
            "description": draft["job_description"],
            "competencies": [
                {
                    "id": item["id"],
                    "description": item["description"],
                    "weight": item["weight"],
                    "anchor_question": item["anchor_question"],
                }
                for item in draft["competencies"]
            ],
            "max_questions": draft["max_questions"],
            "anchor_ratio": draft["anchor_ratio"],
        },
        headers=candidate_headers(),
    )
    assert response.status_code == 403
