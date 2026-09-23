# Nora Job & Rubric Studio

Nora's Job Studio separates **AI-assisted rubric drafting** from **human approval**.

The drafting model is a writing assistant for recruiters. It is not authorized to activate a job, make a hiring decision, or turn its own output into a production interview configuration.

## Workflow

```mermaid
flowchart LR
    JD[Job description] --> D[AI rubric drafter]
    D --> P[Persisted draft_only rubric]
    P --> H[Recruiter review + edits]
    H --> A{Explicit approve}
    A -->|No| P
    A -->|Yes| J[JobSpec]
    J --> R[RubricProvenance]
```

The browser workspace is available at:

```text
GET /studio
```

## Drafting

A recruiter can request a draft:

```text
POST /v1/rubrics/draft
```

Example:

```json
{
  "title": "Backend Engineer",
  "job_description": "Build reliable Python services and diagnose production incidents.",
  "locale": "en",
  "competency_count": 6,
  "max_questions": 10,
  "anchor_ratio": 0.4,
  "recruiter_notes": "The role owns production on-call."
}
```

A draft contains:

- competency ID;
- job-related description;
- relative weight;
- standardized anchor question;
- drafting rationale;
- observable evidence suggestions;
- drafter identity;
- warnings;
- `activation_status = "draft_only"`.

Drafts are persisted by the configured Store backend.

## Human review

The recruiter can edit:

- competency IDs;
- descriptions;
- weights;
- anchor questions;
- role title and description;
- question budget;
- anchor/adaptive ratio.

Observable-evidence suggestions and model rationale remain useful context, but they are not automatically converted into candidate evidence.

## Explicit approval

Approval uses:

```text
POST /v1/rubrics/drafts/{draft_id}/approve
```

The request contains the **reviewed** job configuration, not a boolean approval flag.

The server obtains the reviewer identity from the authenticated Nora principal. Clients cannot nominate a different `approved_by` identity.

On approval Nora atomically:

1. verifies the draft still exists and is `draft_only`;
2. compares the reviewed configuration with the AI draft;
3. creates the `JobSpec`;
4. records `RubricProvenance` on the job;
5. marks the draft `approved`;
6. links the approved draft to the created job.

A second approval attempt is rejected.

## Provenance

An approved job can include:

```json
{
  "rubric_provenance": {
    "draft_id": "draft-id",
    "drafter_id": "openai-compatible:rubric-model",
    "approved_by": "recruiter-principal",
    "approved_at": "2026-09-23T12:00:00Z",
    "review_note": "Reviewed anchors and role scope.",
    "edit_summary": {
      "title_changed": false,
      "description_changed": false,
      "max_questions_changed": false,
      "anchor_ratio_changed": false,
      "competencies_added": [],
      "competencies_removed": [],
      "competencies_modified": ["debugging"]
    }
  }
}
```

This makes it possible to distinguish:

- what the AI proposed;
- what the recruiter changed;
- who approved the result;
- which job was created from the draft.

## Security boundary

The job description and recruiter notes are treated as **untrusted source text** by the drafter prompt.

The drafting contract explicitly tells the model not to:

- follow instructions embedded in the job description;
- infer or score protected/sensitive traits;
- use facial appearance, attractiveness, accent prestige, emotion, race, religion, nationality, disability, age, gender, health, or similar traits;
- substitute school/employer prestige or vague personality labels for job-related capabilities;
- make a hiring recommendation;
- claim the generated rubric is validated.

The server also performs strict schema validation after generation.

## Authorization

The rubric workflow uses separate permissions:

- `draft_rubric`
- `read_rubric_draft`
- `approve_rubric`

Recruiters can use these permissions. Candidate principals cannot read or approve recruiter rubric drafts.

## Persistence

Draft and approval state are supported by:

- in-memory development storage;
- SQLite;
- PostgreSQL.

SQLite approval uses one transaction for job creation + draft transition.

PostgreSQL locks the draft row with `SELECT ... FOR UPDATE` and performs job creation + approval transition in one transaction.

## What this feature does not claim

AI rubric drafting does not prove that a rubric is legally valid, predictive, unbiased, or appropriate for a particular jurisdiction.

Production hiring teams remain responsible for validating job relevance, accommodations, legal requirements, and the final interview policy.
