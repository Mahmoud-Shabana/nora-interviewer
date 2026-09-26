# Nora v0.5.0 Development Plan

Status: planned  
Baseline: v0.4.0 release line  
Current development line: main

This plan starts only after the v0.4.0 metadata/docs freeze. It must avoid reopening completed voice, persistence, audit, and VoxRubric integration work unless a concrete implementation gap is discovered.

## Development rules

1. Search the existing codebase before adding a capability.
2. Prefer production boundaries and reusable contracts over demo-only features.
3. Do not add commits solely to increase commit count.
4. Do not run GitHub Actions, pytest, or other test execution while the current account constraint remains.
5. Use static review, type/contract inspection, and documentation reconciliation during the constraint.
6. Keep hiring decisions human-owned; Nora may surface evidence and review context, not autonomous final decisions.

## Gate 1 — Organization identity

- [ ] organization-specific OIDC login/session integration
- [ ] issuer/audience/provider configuration per deployment
- [ ] mapped organization roles and recruiter/reviewer claims
- [ ] session ownership continuity across authenticated clients
- [ ] security and deployment documentation

## Gate 2 — Encrypted artifact storage

- [ ] object-storage abstraction for candidate artifacts/audio
- [ ] encrypted-at-rest provider boundary
- [ ] signed/expiring artifact access
- [ ] retention/deletion integration
- [ ] audit provenance for artifact creation, access, and deletion

## Gate 3 — External sandbox service

- [ ] remote sandbox protocol independent from the API process
- [ ] job/template policy enforcement before dispatch
- [ ] resource/time/network policy contract
- [ ] structured execution result and artifact provenance
- [ ] graceful unavailable/degraded behavior

## Gate 4 — Domain practical evaluators

- [ ] richer coding evaluator contract
- [ ] data-analysis evaluator
- [ ] document-analysis evaluator
- [ ] system-design/case-study evaluator
- [ ] evaluator provenance and human-review handoff

## Gate 5 — Arabic technical interview depth

- [ ] Arabic dialect-aware interview fixtures
- [ ] Arabic/English technical terminology preservation
- [ ] code-switch-aware transcript metadata
- [ ] domain vocabulary packs for software/AI/engineering interviews
- [ ] export fields needed by VoxRubric ASR-preservation evaluation

## Gate 6 — Developer and deployment experience

- [ ] deployment reference configuration
- [ ] OIDC/object-store/sandbox examples
- [ ] migration notes from v0.4
- [ ] architecture and threat-boundary update
- [ ] v0.5 changelog and release metadata reconciliation

## Explicitly frozen unless a real gap appears

Do not rebuild:

- browser/server STT and TTS
- STT reconnect/resume
- VAD
- voice provider circuit breaker
- SQLite/PostgreSQL persistence
- optimistic versioning and ETags
- retention manager
- tamper-evident audit chain
- semantic Evidence Judge
- Job & Rubric Studio
- VoxRubric export
- operational SLO and Prometheus metrics

Those are v0.4 capabilities and should only change for a concrete v0.5 dependency or defect.
