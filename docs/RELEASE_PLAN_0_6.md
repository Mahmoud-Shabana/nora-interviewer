# Nora v0.6.0 Development Plan

Status: active — Gate 1 in progress  
Baseline: v0.5.0 release line  
Current development line: main

## Development rules

1. Do not reopen completed v0.5 capabilities without a concrete dependency or defect.
2. Keep production integrations behind provider-neutral contracts.
3. No GitHub Actions, pytest, or runtime test execution while the current account constraint remains.
4. Use static review and contract inspection only during the constraint.
5. Keep hiring decisions human-owned and auditable.

## Gate 1 — Managed artifact storage

- [ ] S3-compatible object-store provider
- [ ] SSE-S3 and SSE-KMS configuration
- [ ] endpoint/region/bucket/prefix configuration
- [ ] normalized storage errors and not-found handling
- [ ] deployment and migration documentation

## Gate 2 — Workload/service identity

- [ ] dedicated service-workload JWT resolver
- [ ] separate service audience and issuer configuration
- [ ] optional organization scope for workloads
- [ ] no candidate/recruiter/reviewer role escalation
- [ ] capability and deployment documentation

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
