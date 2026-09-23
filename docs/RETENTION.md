# Data Retention and Session Lifecycle

Nora treats data retention as an explicit operational policy rather than an implicit database side effect.

## Session timestamps

Every interview session records:

- `created_at`
- `completed_at`

`completed_at` is written when the interview reaches the completed state.

## Retention defaults

The retention API is intentionally conservative.

Default request:

```json
{
  "max_age_days": 90,
  "completed_only": true,
  "dry_run": true
}
```

This means:

- active sessions are skipped;
- sessions younger than the cutoff are retained;
- matching sessions are reported;
- nothing is deleted until `dry_run=false`.

## API

```text
POST /v1/system/retention/run
```

The operation requires the internal:

```text
run_retention
```

permission.

In the current authorization policy, only the `service` role has that permission.

## Preview before deletion

Recommended workflow:

1. run with `dry_run=true`;
2. inspect `matched`;
3. confirm the cutoff and candidate scope;
4. run the same policy with `dry_run=false`.

Example preview:

```json
{
  "max_age_days": 90,
  "completed_only": true,
  "dry_run": true
}
```

Candidate-scoped preview:

```json
{
  "max_age_days": 90,
  "completed_only": true,
  "dry_run": true,
  "candidate_ref": "candidate-123"
}
```

## Age basis

For completed sessions:

```text
age_basis = completed_at
```

If an operator explicitly sets `completed_only=false`, an active session can be evaluated using:

```text
age_basis = created_at
```

This behavior is visible in each `RetentionMatch`.

## Storage independence

`RetentionManager` depends only on the `Store` protocol:

- `list_sessions()`
- `delete_session()`

The same retention logic therefore works for:

- in-memory development storage;
- SQLite local durable storage;
- future PostgreSQL/object-aware backends.

## Production direction

A production lifecycle should additionally define:

- organization-specific retention duration;
- legal hold behavior;
- candidate deletion-request workflow;
- audio/artifact cascading deletion;
- backup retention;
- audit trail for administrative deletion actions;
- encrypted storage and key lifecycle;
- jurisdiction-specific requirements.

The current retention manager is a deterministic policy engine and local operational primitive, not a complete legal-compliance system.
