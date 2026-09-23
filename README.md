# Nora Interviewer

> An open interview operating system for auditable, adaptive, multilingual AI interviews.

Nora is a research-grade interview orchestration platform built around a simple idea:

> **Structured enough to be comparable. Adaptive enough to be intelligent. Auditable enough to be trusted.**

It is not designed as a black-box candidate scorer. Conversation, evidence, practical artifacts, candidate rights, integrity signals, voice state, and evaluation live in separate inspectable layers.

Nora exports its sessions to [VoxRubric](https://github.com/Mahmoud-Shabana/voxrubric) for independent regression and benchmark evaluation.

## Current development: v0.4

The package is actively evolving toward v0.4. The current main branch already includes the systems below.

## Interview intelligence

### Dual-lane protocol

Each role can combine:

```text
standardized anchor questions
            +
adaptive investigation
```

Anchors preserve comparability across candidates. Adaptive follow-ups investigate the candidate's actual evidence, reasoning, and trade-offs.

Every interviewer turn records its lane and decision reason.

### Structured interview brain

Nora supports:

- deterministic development brain;
- structured LLM brain;
- OpenAI-compatible completion provider;
- deterministic fallback if the primary provider fails;
- explicit question budget;
- competency state;
- job-scoped practical-tool policy;
- server-side validation of every model-returned competency/tool request.

The LLM does **not** own session IDs, turn lineage, tool authority, evidence state, appeals, or integrity decisions.

## Candidate controls

Candidates can interact with the interview process explicitly instead of hacking those requests into ordinary answers:

- Repeat
- Clarify
- Thinking time
- Resume
- Correct last answer
- Ask Nora

These controls are audited separately and do not silently consume ordinary question budget.

## Skill Evidence Graph

A candidate answer does not automatically become a positive skill score.

Current evidence states:

```text
unknown
  |
claimed
  |
demonstrated
  |
verified

additional states:
insufficient_evidence
contradicted
```

Evidence carries:

- competency ID;
- source transcript/artifact turn;
- state;
- confidence;
- optional grounded quote;
- note;
- source.

Practical-tool success currently raises evidence only to `demonstrated`, not automatically to `verified`.

## Candidate rights

Nora implements candidate protections as product behavior:

- explicit consent to AI-led interviewing;
- separate transcript-processing consent;
- transcript correction while preserving original text;
- appeals tied to exact turns;
- append-only audit events;
- replay support;
- evidence provenance;
- human-review-only integrity signals.

See `docs/CANDIDATE_RIGHTS.md`.

## Progressive integrity

Per-session integrity modes:

```text
none
identity
passive_signals
secure
proctored
```

An integrity signal is a review input, not a misconduct verdict.

The data model intentionally keeps:

```text
requires_human_review = true
```

instead of an automatic rejection field.

## Practical interview tools

Nora has a provider-neutral interview-tool layer.

Supported tool categories currently include:

- coding;
- case study;
- whiteboard;
- document analysis;
- dataset tasks.

### Job-scoped tool policy

A role explicitly lists the practical templates the interview brain is allowed to request.

The model can request only the approved `template_id`. The server validates:

- template authorization;
- competency policy;
- maximum tool budget;
- duplicate-template use;
- hidden evaluator state.

### Built-in trusted templates

Current server-side templates include:

- Python event de-duplication coding task;
- bursty API system-design case;
- service dependency whiteboard;
- incident-review document exercise.

### Coding sandbox

Coding challenges keep public and hidden tests separate.

Candidate code is **not** executed inside the Nora server process.

The optional local Docker runner uses:

- disposable containers;
- network disabled;
- read-only filesystem;
- dropped Linux capabilities;
- `no-new-privileges`;
- unprivileged user;
- PID limits;
- memory limits;
- CPU limits;
- file-descriptor limits;
- execution timeout.

If the sandbox is disabled or unavailable, Nora records the submission and returns a manual/external-review result instead of inventing a score.

The local Docker runner is a development/CI isolation layer, not a claim of perfect hostile-code containment for high-stakes production.

## Post-tool reasoning

Submitting an artifact does not end the interview.

The flow is:

```text
Nora opens tool
      |
candidate submits artifact
      |
tool evaluator
      |
artifact becomes a transcript/provenance turn
      |
Skill Evidence Graph update
      |
Nora asks a reasoning/trade-off follow-up
      |
interview continues
```

This lets Nora evaluate the reasoning around code or artifacts instead of reducing the task to pass/fail tests.

## Realtime voice architecture

Nora now has a provider-neutral realtime voice lifecycle:

```text
idle
  |
  v
listening
  |
  v
processing
  |
  v
speaking
  |
  v
idle
```

The voice coordinator records:

- speech started;
- partial transcript;
- final transcript;
- interviewer response ready;
- TTS started;
- TTS completed;
- TTS cancelled;
- barge-in.

### Barge-in

If the candidate begins speaking while Nora is speaking:

1. active TTS is cancelled;
2. an interruption event is recorded;
3. the voice generation is incremented;
4. Nora moves immediately to listening;
5. stale audio can be discarded by future streaming providers.

### Voice latency breakdown

Nora records three separate stages:

```text
speech -> final transcript
final transcript -> interviewer response
response -> TTS start
```

Those events export directly to VoxRubric, which evaluates lifecycle integrity, latency, and interruption recovery.

See `docs/VOICE_PROTOCOL.md`.

## Browser interview room

The built-in interview room currently includes:

- role setup;
- competency setup;
- integrity-mode selection;
- practical-tool policy selection;
- realtime WebSocket conversation;
- Arabic/English locale selection;
- browser voice demo;
- candidate control toolbar;
- practical task workbench;
- coding editor area;
- public coding checks;
- artifact submission;
- tool-evaluation result display;
- automatic post-tool interview continuation;
- VoxRubric trace export.

Browser speech APIs are a zero-key demo transport. Production speech can replace them while preserving Nora's interview and audit semantics.

## Event log and replay

Material actions are recorded as ordered events including:

```text
session_created
interview_started
interviewer_turn
candidate_turn
candidate_control
evidence_observed
transcript_corrected
appeal_submitted
integrity_signal
tool_opened
tool_submitted
tool_evaluated
voice_speech_started
voice_transcript_partial
voice_transcript_final
voice_response_ready
voice_tts_started
voice_tts_completed
voice_tts_cancelled
voice_barge_in
session_completed
```

Replay rejects broken event ordering instead of guessing.

## Counterfactual decision replay

Nora includes a teacher-forced policy comparison layer.

The recorded candidate answers are held fixed while an alternate interview brain can be asked:

> Given this same state and same answer, what would you have done next?

The report compares:

- follow-up vs advance behavior;
- completion decisions;
- competency overlap;
- question-token overlap.

This is intended for model/policy comparison and stability experiments. It does not claim that a fully branched alternate interview would unfold identically.

## Candidate feedback

Candidate-facing feedback is evidence-based rather than a magic score.

It separates:

```text
supported evidence
needs more evidence
conflicting evidence
```

and links statements back to relevant interview turns.

The report explicitly states that it is not a final hiring decision or personality assessment.

## VoxRubric export

Nora exports:

- ordered turns;
- question lanes;
- competency tags;
- response latency;
- candidate controls;
- Skill Evidence Graph;
- transcript revisions;
- appeals;
- integrity signals;
- tool invocations;
- tool submissions;
- tool evaluations;
- voice audit events;
- session metadata.

VoxRubric can then independently test governance, evidence provenance, tool integrity, voice behavior, and interview structure.

## Independent semantic evidence judge

**Work in progress on main.**

The next evaluation layer separates the evidence judge from the interviewer brain.

The intended contract is:

```text
candidate answer
      |
independent evidence judge
      |
literal quote validation
      |
EvidenceObservation
      |
Skill Evidence Graph
```

A transcript-only semantic judge will not be allowed to turn ordinary conversational evidence directly into `verified` skill. Grounded quotes must exist in the referenced candidate turn before the observation can be accepted.

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

Or:

```bash
docker compose up --build
```

## Optional coding sandbox

Disabled by default:

```bash
export NORA_SANDBOX_MODE=disabled
```

Local Docker mode:

```bash
export NORA_SANDBOX_MODE=docker
export NORA_SANDBOX_IMAGE=python:3.12-alpine
uvicorn nora_interviewer.api:app --reload
```

## LLM mode

Default deterministic mode:

```bash
export NORA_BRAIN_MODE=rule
```

OpenAI-compatible provider mode:

```bash
export NORA_BRAIN_MODE=openai-compatible
export NORA_LLM_BASE_URL=https://your-provider.example/v1
export NORA_LLM_MODEL=your-model
export NORA_LLM_API_KEY=...
uvicorn nora_interviewer.api:app --reload
```

## Core API

```text
POST /v1/jobs
POST /v1/sessions
POST /v1/sessions/{id}/start
POST /v1/sessions/{id}/responses
POST /v1/sessions/{id}/controls

POST /v1/sessions/{id}/coding-challenges
POST /v1/sessions/{id}/tools
POST /v1/sessions/{id}/tools/{tool_id}/submit

POST /v1/sessions/{id}/corrections
POST /v1/sessions/{id}/appeals
POST /v1/sessions/{id}/evidence
POST /v1/sessions/{id}/integrity-signals

GET  /v1/sessions/{id}
GET  /v1/sessions/{id}/feedback
GET  /v1/sessions/{id}/events
GET  /v1/sessions/{id}/replay
POST /v1/sessions/{id}/decision-replay
GET  /v1/sessions/{id}/voxrubric

GET  /v1/sessions/{id}/voice
POST /v1/sessions/{id}/voice/speech-started
POST /v1/sessions/{id}/voice/transcript-partial
POST /v1/sessions/{id}/voice/transcript-final
POST /v1/sessions/{id}/voice/tts-started
POST /v1/sessions/{id}/voice/tts-completed
POST /v1/sessions/{id}/voice/tts-cancelled

WS   /v1/ws/interviews/{id}
```

## Architecture

```text
Candidate UI / Voice / Practical tools
                  |
                  v
          Interview transport
                  |
        +---------+----------+
        |                    |
        v                    v
RealtimeVoice          Session Orchestrator
Coordinator                   |
                         +-----+------+
                         |            |
                  DualLanePlanner  InterviewBrain
                         |            |
                         +-----+------+
                               |
                      Agent Tool Policy
                               |
                +--------------+---------------+
                |              |               |
              Coding        Case/Docs       Whiteboard
             Sandbox
                |
                v
         Practical Artifact
                |
                v
        Skill Evidence Graph
                |
        +-------+---------+
        |                 |
Candidate Rights      Integrity Signals
        |                 |
        +-------+---------+
                |
          Event Log / Replay
                |
                v
          VoxRubric Export
```

## Documentation

- `docs/ARCHITECTURE.md`
- `docs/INTERVIEW_PROTOCOL.md`
- `docs/CANDIDATE_RIGHTS.md`
- `docs/VOICE_PROTOCOL.md`

## Safety baseline

Nora should not score facial appearance, attractiveness, accent prestige, inferred emotion, race, religion, nationality, disability, age, gender, health, or similar protected/sensitive traits.

Video may be used for presence, recording, screen sharing, diagrams, or other interaction artifacts. Job-relevant evaluation should remain tied to explicit competencies, evidence, practical work, applicable law, and accountable review.

## Development direction

Next major layers:

- independent semantic Evidence Judge;
- real streaming STT/TTS provider adapters;
- VAD and audio-chunk transport;
- reconnect/backpressure handling;
- recruiter/candidate role separation and authorization;
- durable PostgreSQL persistence;
- encrypted artifact/audio storage;
- retention controls;
- richer practical-tool evaluators;
- Nora adapter for VoxRubric Arena;
- Arabic dialect/technical-ASR benchmark packs;
- statistical repeated-run evaluation.

## License

Apache-2.0.
