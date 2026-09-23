# Independent Semantic Evidence Judge

Nora separates **interview generation** from **semantic evidence classification**.

The Interview Brain proposes what to ask next.

The Evidence Judge answers a narrower question:

> Does this specific candidate answer contain job-related evidence for the competencies attached to the question?

It does not make the hiring decision.

## Why it is independent

Using one model to ask the question, interpret the answer, assign evidence, and make a final decision creates a difficult-to-audit feedback loop.

Nora therefore keeps a separate contract:

```text
Interview Brain
     |
     | asks question
     v
Candidate answer
     |
     v
Independent Evidence Judge
     |
     v
Grounding Gate
     |
     v
Skill Evidence Graph
```

The judge can use a completely different provider/model from the interviewer.

## Configuration

Evidence judging is disabled by default.

```bash
NORA_EVIDENCE_JUDGE_MODE=disabled
```

To configure an independent OpenAI-compatible judge:

```bash
NORA_EVIDENCE_JUDGE_MODE=openai-compatible
NORA_EVIDENCE_JUDGE_BASE_URL=https://judge-provider.example/v1
NORA_EVIDENCE_JUDGE_MODEL=judge-model
NORA_EVIDENCE_JUDGE_API_KEY=...
```

These settings are deliberately separate from `NORA_LLM_*`.

## Allowed transcript states

The semantic transcript judge may emit:

```text
demonstrated
contradicted
insufficient_evidence
```

It may not emit:

```text
verified
```

Transcript evidence alone does not prove external truth.

## Literal quote grounding

A `demonstrated` or `contradicted` finding must include a literal quote copied from the referenced candidate answer.

Example accepted observation:

```json
{
  "competency_id": "debugging",
  "state": "demonstrated",
  "confidence": 0.91,
  "quote": "compared event-loop lag with database query duration",
  "rationale": "The answer compares competing hypotheses using measurements."
}
```

If the quote is absent from the candidate answer, the observation is rejected.

The check exists twice:

1. in `GroundedEvidenceGate`;
2. again in `EvidenceGraph.apply_observation`.

The second check is defense in depth for callers that bypass the semantic judge layer.

## Failure behavior

A semantic judge failure does **not** terminate the interview.

Nora appends:

```text
evidence_judge_failed
```

with:

- judge ID;
- question turn ID;
- answer turn ID;
- requested competency IDs;
- error type;
- bounded error text.

The original candidate claim evidence remains intact.

## Export to VoxRubric

Nora exports:

- accepted semantic evidence in `evidence_graph`;
- rejected/runtime judge events in `evidence_judge_failures`.

VoxRubric's `semantic_judge_integrity` metric then checks:

- semantic evidence references candidate turns;
- demonstrated/contradicted evidence has a quote;
- the quote is literal;
- transcript judges never emit `verified`;
- confidence is valid;
- judge failures are visible as regressions.

## Security boundary

Candidate text is untrusted data.

The Evidence Judge prompt explicitly instructs the provider not to follow instructions embedded inside candidate answers.

Application code still owns:

- allowed competency IDs;
- allowed evidence states;
- quote validation;
- evidence provenance;
- final graph mutation.

The model never directly mutates interview state.
