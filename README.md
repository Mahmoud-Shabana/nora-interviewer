# Nora Interviewer

> An open interview operating system for auditable, adaptive, multilingual AI interviews.

Nora is not designed as a black-box candidate scorer. It is a research-grade interview orchestration platform that keeps **conversation, evidence, candidate rights, integrity signals, and evaluation** as separate, inspectable layers.

The project pairs naturally with [VoxRubric](https://github.com/Mahmoud-Shabana/voxrubric), which evaluates Nora traces and other interview agents.

## Current v0.3

### Interview intelligence

- **Dual-lane protocol:** standardized anchor questions + adaptive investigation.
- traceable follow-ups through `parent_turn_id`.
- structured LLM brain with an OpenAI-compatible provider adapter.
- deterministic fallback if the model/provider fails.
- explicit competency and question-budget state.
- browser interview room with live WebSocket conversation.
- optional browser speech recognition + speech synthesis demo.

### Evidence

Nora maintains a provenance-first **Skill Evidence Graph**.

A candidate answer initially proves only that a claim was made. Stronger states must be explicitly observed:

```text
unknown -> claimed -> demonstrated -> verified
                  \-> insufficient_evidence
                  \-> contradicted
```

Evidence observations reference real transcript turns and keep evaluator confidence separate from candidate claims.

### Candidate rights

- explicit consent to AI interviewing.
- separate consent to transcript processing.
- candidate transcript correction while preserving original text.
- candidate appeals linked to exact conversation turns.
- append-only audit events and replay.
- no hidden sensitive-trait scoring schema.

See `docs/CANDIDATE_RIGHTS.md`.

### Progressive integrity

Integrity is opt-in per session:

```text
none
identity
passive_signals
secure
proctored
```

Integrity detectors produce **review signals**, not automatic misconduct decisions. Every signal is explicitly marked `requires_human_review=true`.

### Evaluation export

Nora exports a VoxRubric-compatible trace containing:

- question lanes;
- response latency;
- competency tags;
- evidence graph;
- transcript revisions;
- appeals;
- integrity signals;
- audit metadata.

VoxRubric can then validate not only interview quality, but governance invariants such as evidence provenance and human-review-only integrity signals.

## Run locally

```bash
python -m pip install -e '.[dev]'
pytest
uvicorn nora_interviewer.api:app --reload
```

Open:

```text
http://localhost:8000
```

Or use Docker:

```bash
docker compose up --build
```

## LLM mode

The default is deterministic `rule` mode so a fresh clone runs without credentials.

To use an OpenAI-compatible chat-completions server:

```bash
export NORA_BRAIN_MODE=openai-compatible
export NORA_LLM_BASE_URL=https://your-provider.example/v1
export NORA_LLM_MODEL=your-model
export NORA_LLM_API_KEY=...
uvicorn nora_interviewer.api:app --reload
```

The LLM proposes a structured next action and candidate-facing text. Nora—not the model—owns session state, valid competency IDs, turn lineage, evidence state, appeals, integrity signals, and audit history.

## Core API

```text
POST /v1/jobs
POST /v1/sessions
POST /v1/sessions/{id}/start
POST /v1/sessions/{id}/responses

POST /v1/sessions/{id}/corrections
POST /v1/sessions/{id}/appeals
POST /v1/sessions/{id}/evidence
POST /v1/sessions/{id}/integrity-signals

GET  /v1/sessions/{id}
GET  /v1/sessions/{id}/events
GET  /v1/sessions/{id}/replay
GET  /v1/sessions/{id}/voxrubric

WS   /v1/ws/interviews/{id}
```

## Architecture

```text
Candidate UI / Voice / Coding / future tools
                  |
                  v
          Interview transport
                  |
                  v
         Session orchestrator
           /             \
 DualLanePlanner      InterviewBrain
       |                   |
       +---------+---------+
                 |
                 v
          Skill Evidence Graph
                 |
      +----------+-----------+
      |                      |
 Audit / Candidate Rights   Integrity Signals
      |                      |
      +----------+-----------+
                 |
                 v
          VoxRubric export
```

See:

- `docs/ARCHITECTURE.md`
- `docs/INTERVIEW_PROTOCOL.md`
- `docs/CANDIDATE_RIGHTS.md`

## Browser voice demo

When supported by the browser, Nora can use browser-native speech recognition to fill the answer box and speech synthesis to read interviewer questions aloud.

This is a zero-key demo layer, not the final production speech stack. Production voice should add streaming STT/TTS, VAD, cancellation, barge-in, reconnects, backpressure, and measured end-to-end latency.

## Safety baseline

Nora should not score facial appearance, attractiveness, accent prestige, inferred emotion, race, religion, nationality, disability, age, gender, health, or similar protected/sensitive traits.

Job-relevant decisions should stay tied to explicit rubrics, reviewable evidence, applicable law, and accountable human review.

## License

Apache-2.0.
