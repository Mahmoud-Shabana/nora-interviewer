# Nora v0.4.0 Release Plan

Status: active  
Baseline: `5a615f0d`  
Current development line: `main`

This file is the canonical release checklist. It exists specifically to prevent repeated work on already completed subsystems.

## Rules

1. Search existing code, tests, docs, and recent commits before starting a feature.
2. Do not reopen a completed subsystem without a failing test, integration gap, or documented release blocker.
3. Voice work is frozen unless a concrete regression appears.
4. README and roadmap status must be reconciled with code before release.
5. A release gate is not complete until behavior is covered by tests.

## Confirmed complete / frozen

- browser -> server streaming STT
- server -> browser streaming TTS
- browser STT reconnect/resume with reconnect token and frame reconciliation
- VAD endpointing and auditable endpoint events
- STT/TTS provider health and circuit breaker
- voice fallback telemetry
- distributed request/session correlation tracing
- operational SLO assessment and Prometheus metrics
- memory, SQLite, and PostgreSQL persistence
- optimistic session versioning and ETags
- JWT/JWKS authentication and authorization boundaries
- retention manager and protected retention API
- tamper-evident audit chain
- semantic evidence judge and multi-model ensemble
- Job & Rubric Studio with explicit human approval
- VoxRubric trace export

## Release gates

### Gate 1 — Truth reconciliation

- [x] audit current implementation before adding new work
- [x] reconcile stale README roadmap entries
- [x] keep this release checklist aligned with completed commits

### Gate 2 — End-to-end release regression

- [x] create a deterministic full interview regression covering job creation, session start, candidate answer, evidence, review, and VoxRubric export
- [x] include candidate control behavior in the regression
- [x] include at least one practical-tool lifecycle
- [x] verify audit-chain export remains valid at the end of the flow

### Gate 3 — Failure/recovery regression

- [ ] exercise storage conflict behavior
- [ ] exercise provider degradation/fallback behavior
- [ ] exercise session cancellation cleanup
- [ ] verify SLO/operations state reflects the failures without high-cardinality identifiers

### Gate 4 — Release preparation

- [ ] synchronize README and architecture docs
- [ ] update changelog
- [ ] bump package version to 0.4.0 only after release gates pass

## Explicitly not next

Do not rebuild:

- VAD
- STT reconnect/resume
- distributed tracing
- retention controls
- VoxRubric Arena integration

These are already implemented and should only change in response to a concrete failing regression or release requirement.
