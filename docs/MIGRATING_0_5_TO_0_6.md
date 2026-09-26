# Migrating from Nora v0.5 to v0.6

v0.6 is designed as an additive production-integration release.

## Package behavior

Existing v0.5 deployments remain compatible when new integrations are left disabled.

New capabilities are opt-in through environment configuration.

## Artifact storage

v0.5 encrypted-local storage remains available.

For multi-instance production, v0.6 adds:

```bash
NORA_ARTIFACT_STORE_MODE=s3
```

The S3 provider uses the existing Nora artifact metadata, signed-access, checksum, and retention lifecycle. Moving existing objects between backends is a deployment data-migration operation; Nora does not silently copy encrypted-local files into S3.

## Authentication

Existing modes remain:

```text
disabled
dev-header
jwt-jwks
oidc
```

New modes:

```text
workload-jwt
oidc+workload
```

Use `oidc+workload` when human users and machine integrations need access to the same Nora deployment.

A workload token never chooses candidate/recruiter/reviewer roles.

## Scoped service identities

An unscoped internal service principal keeps administrative behavior.

When a workload token carries the configured organization claim, session-scoped access is restricted to that organization.

Review service integrations that previously assumed every service identity was cross-organization.

## Webhooks

Webhook delivery is disabled when `NORA_WEBHOOK_SUBSCRIPTIONS_JSON` is empty.

When enabled, Nora decorates the configured Store and emits only allowlisted privacy-minimized event metadata.

Webhook failures do not roll back the primary interview state transition.

Receivers must be idempotent because retries may produce duplicate HTTP deliveries.

## Provider resilience

OpenAI-compatible Brain/Judge/Rubric providers now use bounded retry and circuit behavior.

The deterministic fallback Brain now prefixes degraded decision provenance with:

```text
degraded_fallback:<ErrorType>:
```

Consumers that parse `decision_reason` should treat that prefix as structured degradation context, not as a new question lane.

## Remote sandbox

The remote sandbox now uses bounded retry and circuit protection.

Sandbox unavailability continues to produce manual-review-required tool evaluation rather than a fabricated candidate failure.

## System operations

New protected endpoint:

```text
GET /v1/system/resilience
```

Capability output now includes workload identity, webhooks, provider resilience, and portable evidence export flags.

## Portable evidence bundles

New endpoint:

```text
GET /v1/sessions/{session_id}/evidence-bundle
```

Candidates can export their own session evidence; recruiter/reviewer/service access remains subject to Nora authorization and organization scope.

The bundle intentionally omits storage backend keys and full transcript duplication.

## Verification note

The v0.6 implementation was prepared under an explicit no-test-execution constraint. No pytest or GitHub Actions run is claimed by this migration guide.
