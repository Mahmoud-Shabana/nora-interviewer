# Nora v0.5.0 Development Plan

Status: active — Gates 1–4 complete  
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

- [x] organization-specific OIDC login/session integration
- [x] issuer/audience/provider configuration per deployment
- [x] mapped organization roles and recruiter/reviewer claims
- [x] session ownership continuity across authenticated clients
- [x] security and deployment documentation

### Gate 1 implementation notes

Organization OIDC now validates deployment-scoped issuer/audience/JWKS settings, verifies the organization claim, maps trusted identity-provider groups into Nora roles, carries organization identity on principals, and propagates organization scope through jobs, rubric drafts, sessions, review queues, and evidence-reevaluation queues. Session authorization rejects cross-organization access before candidate ownership checks.

No runtime tests or CI were executed for this gate because of the current account constraint; completion here refers to implementation and static contract review.

## Gate 2 — Encrypted artifact storage

- [x] object-storage abstraction for candidate artifacts/audio
- [x] encrypted-at-rest provider boundary
- [x] signed/expiring artifact access
- [x] retention/deletion integration
- [x] audit provenance for artifact creation, access, and deletion

### Gate 2 implementation notes

Nora now has an artifact object-store protocol, disabled provider, AES-256-GCM encrypted local provider, session-scoped artifact metadata, SHA-256 integrity verification, short-lived HMAC-signed access tokens, bounded streaming uploads, creation/access/deletion audit events, and retention purge integration.

The built-in provider is intentionally a local/single-node implementation of the contract. Managed cloud object-store adapters can implement the same interface later without changing session semantics.

No runtime tests or CI were executed for this gate because of the current account constraint; completion refers to implementation and static contract review.

## Gate 3 — External sandbox service

- [x] remote sandbox protocol independent from the API process
- [x] job/template policy enforcement before dispatch
- [x] resource/time/network policy contract
- [x] structured execution result and artifact provenance
- [x] graceful unavailable/degraded behavior

### Gate 3 implementation notes

Nora now supports a versioned `nora.sandbox.v1` remote execution service in addition to the local Docker development runner. Remote requests carry explicit resource and isolation policy, existing job/template authorization remains ahead of sandbox dispatch, structured execution provenance flows into tool evidence, and transport/protocol failures degrade to manual review instead of becoming false candidate failures.

No runtime tests or CI were executed for this gate because of the current account constraint; completion refers to implementation and static contract review.

## Gate 4 — Domain practical evaluators

- [x] richer coding evaluator contract
- [x] data-analysis evaluator
- [x] document-analysis evaluator
- [x] system-design/case-study evaluator
- [x] evaluator provenance and human-review handoff

### Gate 4 implementation notes

Nora now has structured domain evaluators for system-design/case-study, document-analysis, and data-analysis artifacts, plus richer coding evaluator provenance tied to sandbox provider/execution metadata. Domain evaluators report structural completeness and grounding signals while leaving final scoring/selection to human review.

No runtime tests or CI were executed for this gate because of the current account constraint; completion refers to implementation and static contract review.

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
