# Nora v0.6.0 Development Plan

Status: implementation complete; runtime verification deferred  
Baseline: v0.5.0 release line  
Current development line: main

## Development rules

1. Do not reopen completed v0.5 capabilities without a concrete dependency or defect.
2. Keep production integrations behind provider-neutral contracts.
3. No GitHub Actions, pytest, or runtime test execution while the current account constraint remains.
4. Use static review and contract inspection only during the constraint.
5. Keep hiring decisions human-owned and auditable.

## Gate 1 — Managed artifact storage

- [x] S3-compatible object-store provider
- [x] SSE-S3 and SSE-KMS configuration
- [x] endpoint/region/bucket/prefix configuration
- [x] normalized storage errors and not-found handling
- [x] deployment and migration documentation

### Gate 1 implementation notes

Nora now supports S3-compatible artifact storage with mandatory server-side encryption, SSE-S3/SSE-KMS selection, optional KMS key, bucket/prefix/region/endpoint configuration, normalized provider failures, and compatibility with the existing signed-access/integrity/retention artifact lifecycle.

No runtime tests or CI were executed; completion refers to implementation and static contract review.

## Gate 2 — Workload/service identity

- [x] dedicated service-workload JWT resolver
- [x] separate service audience and issuer configuration
- [x] optional organization scope for workloads
- [x] no candidate/recruiter/reviewer role escalation
- [x] capability and deployment documentation

### Gate 2 implementation notes

Nora now has a workload-only JWT resolver that always produces the internal service role, separate workload issuer/audience/JWKS configuration, optional organization scoping for service tokens, and a hybrid `oidc+workload` mode that accepts human and machine identity domains without letting workload tokens choose human roles.

No runtime tests or CI were executed; completion refers to implementation and static contract review.

## Gate 3 — Outbound webhooks

- [x] signed webhook delivery contract
- [x] organization-scoped subscriptions
- [x] bounded retry/idempotency metadata
- [x] auditable delivery state
- [x] privacy-safe event payload policy

### Gate 3 implementation notes

Session persistence can now be decorated with signed outbound webhook delivery. Subscriptions are organization-scoped deployment configuration, payloads expose only privacy-minimized lifecycle metadata, HMAC signatures and deterministic idempotency keys are included, retry behavior is bounded, and delivery results are recorded as non-recursive audit events.

No runtime tests or CI were executed; completion refers to implementation and static contract review.

## Gate 4 — Provider resilience

- [x] provider timeout budgets
- [x] retry classification and bounded backoff contracts
- [x] circuit-state exposure for model/judge/sandbox providers
- [x] degraded-mode provenance
- [x] operator documentation

### Gate 4 implementation notes

Completion-based Brain/Judge/Rubric providers and the remote sandbox now share bounded timeout/retry/circuit semantics. Provider circuit snapshots are available through a protected system endpoint, and deterministic Brain fallback records explicit degraded-mode provenance instead of failing silently.

No runtime tests or CI were executed; completion refers to implementation and static contract review.

## Gate 5 — Evidence portability

- [x] portable evidence bundle schema
- [x] artifact/checksum references
- [x] audit-chain head and export provenance
- [x] organization-scoped bundle access
- [x] VoxRubric interoperability notes

### Gate 5 implementation notes

Nora now exports a `nora.evidence.bundle.v1` portable evidence object with active evidence provenance, artifact metadata/checksums, verified audit-chain head, canonical VoxRubric trace digest, and a deterministic bundle digest. Access uses the existing session/organization authorization boundary, and backend artifact storage locations are not exposed.

No runtime tests or CI were executed; completion refers to implementation and static contract review.

## Gate 6 — Release preparation

- [x] v0.6 deployment reference
- [x] v0.5 → v0.6 migration notes
- [x] architecture/threat-boundary update
- [x] changelog reconciliation
- [x] package/runtime/API metadata reconciliation


### Gate 6 implementation notes

The repository now includes a v0.6 deployment reference, v0.5-to-v0.6 migration guide, updated integration/threat boundaries, and synchronized package/runtime/API/README/changelog metadata at `0.6.0`.

All six v0.6 implementation gates are complete. Runtime test execution and GitHub Actions were intentionally not run because of the current account constraint.

## Final v0.6 status

- Gate 1 — Managed artifact storage: complete
- Gate 2 — Workload/service identity: complete
- Gate 3 — Outbound webhooks: complete
- Gate 4 — Provider resilience: complete
- Gate 5 — Evidence portability: complete
- Gate 6 — Release preparation: complete

Package/runtime/API metadata: `0.6.0`

Runtime verification: deferred by explicit account constraint; no pytest, GitHub Actions, or other test execution was run during this pass.
