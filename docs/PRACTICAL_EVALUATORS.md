# Practical Evaluators

Nora's practical-tool layer separates artifact structure validation from final human judgment.

## Evaluator contract

Every tool evaluator receives:

- the server-owned `ToolInvocation`;
- the candidate `ToolSubmission`;
- the canonical `InterviewSession`;
- the active `JobSpec`.

Evaluators return a structured `ToolEvaluation` with evidence and provenance.

## Coding

The coding evaluator can execute server-owned public/hidden tests through the configured sandbox runner.

Its evidence now records:

- evaluator ID/version;
- originating template ID;
- sandbox provider;
- remote execution ID when present;
- produced artifact provenance;
- duration/timeout/exit state.

A sandbox outage does not become a candidate failure. Nora records the submission and hands it to human/external review.

## System design / case study

The system-design evaluator validates the declared deliverables, currently including:

- architecture summary;
- failure modes;
- trade-offs;
- validation metrics.

It records completeness and domain signals but intentionally leaves `passed` and `score` unset.

## Document analysis

The document evaluator validates:

- verified facts;
- open questions;
- contributing factors;
- remediation.

It also records whether explicit evidence references are present and warns reviewers when grounding references are absent.

## Data analysis

The data-analysis evaluator validates:

- analysis;
- assumptions;
- result;
- validation.

It additionally records whether calculations were supplied.

The built-in `data-analysis-service-latency-v1` template exercises this contract.

## Provenance

Structured domain evaluations include:

```text
evaluator_id
evaluator_version
tool_kind
template_id
automatic_hiring_decision=false
automatic_score=false
```

Coding evaluation similarly records evaluator and sandbox provenance.

## Human-review boundary

Nora does not convert structural completeness into a hiring recommendation.

For document, data-analysis, and system-design tasks:

```text
passed = null
score = null
review_required = true
```

The structured evaluator helps the reviewer see missing deliverables, grounding gaps, and provenance without pretending that schema completeness proves job suitability.
