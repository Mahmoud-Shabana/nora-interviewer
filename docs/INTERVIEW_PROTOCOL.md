# Nora Interview Protocol

Nora separates **comparability**, **adaptivity**, **evidence**, and **governance** instead of hiding them behind a single model prompt.

## 1. Dual-lane interviewing

Each job can define a target anchor ratio.

```text
standardized anchors  +  adaptive investigation
        40%                    60%
```

Anchor questions are configured on competencies and remain stable across candidates. Adaptive questions are produced by the interview brain from the candidate's actual answers.

The planner gives a genuine follow-up priority when the latest answer needs investigation. Otherwise it schedules an anchor whenever the standardized share has fallen below the configured target.

Every interviewer turn records:

```json
{
  "question_lane": "anchor",
  "decision_reason": "anchor:standardized_anchor"
}
```

This makes the trade-off between consistency and personalization observable.

## 2. Skill Evidence Graph

A candidate answer is not automatically a positive skill score.

The default progression is:

```text
unknown
  |
claimed
  |
demonstrated
  |
verified
```

Two additional states are first-class:

```text
insufficient_evidence
contradicted
```

Candidate responses create **claim provenance** only. A semantic evaluator or another verified source must explicitly create a stronger observation.

Every observation carries:

- competency ID;
- transcript turn ID;
- evidence state;
- confidence;
- note;
- source.

A contradiction is sticky: a later positive observation does not silently erase it.

## 3. Candidate transcript rights

Only candidate turns can be corrected.

A correction never destroys the original transcript. Nora stores:

- original text;
- corrected text;
- candidate reason;
- revision ID;
- target turn ID.

The active transcript uses the latest correction, while the append-only event log preserves the revision history.

## 4. Appeals

Candidates can submit an appeal tied to specific conversation turns.

An appeal starts as `pending`. The model does not resolve the appeal itself. This creates a stable hook for a later human-review workflow.

## 5. Progressive integrity

Integrity is configured per session:

```text
none
identity
passive_signals
secure
proctored
```

The level describes the permitted assessment mode. It is not a candidate score.

Integrity detectors create signals with confidence and evidence. Every signal is explicitly:

```json
{"requires_human_review": true}
```

There is intentionally no automatic rejection field in the integrity model.

## 6. Event log and replay

Material interview actions are appended to an ordered event stream:

```text
session_created
interview_started
interviewer_turn
candidate_turn
evidence_observed
transcript_corrected
appeal_submitted
integrity_signal
session_completed
```

Events use contiguous sequence numbers. The replay layer rejects broken sequences instead of guessing.

The current replay implementation reconstructs lifecycle state and important references. Future versions can re-run the same event history through a different interview brain or evaluation stack for model-comparison experiments.

## 7. Separation of responsibilities

The conversation model can suggest a question or follow-up. It does not own:

- session identifiers;
- turn lineage;
- competency validity;
- evidence state;
- transcript revisions;
- appeals;
- integrity decisions;
- final hiring decisions.

Those remain application-owned state.
