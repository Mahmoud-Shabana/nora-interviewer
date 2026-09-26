# Nora v0.6.0 Development Plan

Status: active — Gates 1–2 complete  
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

- [ ] signed webhook delivery contract
- [ ] organization-scoped subscriptions
- [ ] bounded retry/idempotency metadata
- [ ] auditable delivery state
- [ ] privacy-safe event payload policy

## Gate 4 — Provider resilience

- [ ] provider timeout budgets
- [ ] retry classification and bounded backoff contracts
- [ ] circuit-state exposure for model/judge/sandbox providers
- [ ] degraded-mode provenance
- [ ] operator documentation

## Gate 5 — Evidence portability

- [ ] portable evidence bundle schema
- [ ] artifact/checksum references
- [ ] audit-chain head and export provenance
- [ ] organization-scoped bundle access
- [ ] VoxRubric interoperability notes

## Gate 6 — Release preparation

- [ ] v0.6 deployment reference
- [ ] v0.5 → v0.6 migration notes
- [ ] architecture/threat-boundary update
- [ ] changelog reconciliation
- [ ] package/runtime/API metadata reconciliation
