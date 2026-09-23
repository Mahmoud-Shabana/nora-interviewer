from fastapi.testclient import TestClient

import nora_interviewer.api as api
from nora_interviewer.authn import (
    DevHeaderPrincipalResolver,
)
from nora_interviewer.rubric_drafting import (
    RubricDraft,
    RubricDraftCompetency,
)


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


def test_recruiter_can_request_draft_but_candidate_cannot(monkeypatch):
    monkeypatch.setattr(
        api,
        "principal_resolver",
        DevHeaderPrincipalResolver(),
    )
    monkeypatch.setattr(
        api,
        "rubric_drafter",
        FakeDrafter(),
    )

    client = TestClient(api.app)
    payload = {
        "title": "Backend Engineer",
        "job_description": (
            "Build Python services and diagnose production incidents."
        ),
        "competency_count": 3,
    }

    candidate = client.post(
        "/v1/rubrics/draft",
        json=payload,
        headers={
            "X-Nora-Principal": "candidate",
            "X-Nora-Role": "candidate",
            "X-Nora-Candidate-Ref": "candidate-1",
        },
    )
    assert candidate.status_code == 403

    recruiter = client.post(
        "/v1/rubrics/draft",
        json=payload,
        headers={
            "X-Nora-Principal": "recruiter",
            "X-Nora-Role": "recruiter",
        },
    )
    assert recruiter.status_code == 200
    body = recruiter.json()
    assert body["activation_status"] == "draft_only"
    assert body["drafter_id"] == "fake:drafter"
    assert len(body["competencies"]) == 3
    assert "hire" not in body
    assert "recommendation" not in body
