# Tamper-Evident Audit Chain

Nora's interview event log is now cryptographically chained.

The goal is not to claim that a local database is magically immutable. The goal is to make post-hoc modification of exported or persisted event history **detectable**.

## Event fields

Each sealed `InterviewEvent` contains:

```text
seq
type
turn_id
payload
created_at
hash_version
prev_hash
event_hash
```

Current hash version:

```text
1
```

## Canonical hash material

Nora computes SHA-256 over canonical JSON containing:

```json
{
  "hash_version": 1,
  "seq": 2,
  "type": "interview_started",
  "turn_id": null,
  "payload": {},
  "created_at": "2026-09-23T12:00:01+00:00",
  "prev_hash": "..."
}
```

Canonical JSON rules:

- UTF-8;
- sorted keys;
- compact separators;
- JSON-safe payload normalization;
- explicit ISO timestamp;
- previous event hash included.

The resulting SHA-256 hex digest becomes `event_hash`.

## Chain

```text
event 1
  prev_hash = null
  event_hash = H1

event 2
  prev_hash = H1
  event_hash = H2

event 3
  prev_hash = H2
  event_hash = H3
```

Changing the payload, timestamp, type, sequence, turn reference, or previous hash changes the digest.

## Legacy sessions

Older sessions can contain unhashed events.

When Nora appends the first new event to a fully legacy history, it seals the existing history first, then appends the new event.

A mixed partially-hashed/partially-legacy chain is rejected instead of being silently repaired.

## Replay behavior

`replay_events()` verifies the hash chain before reconstructing session state.

If verification fails, replay raises an `AuditChainError`.

It does not reconstruct state from a tampered sealed history.

## VoxRubric export

Nora exports:

```text
metadata.audit_chain
metadata.audit_events
```

The export includes the canonical timestamp and JSON-safe payload representation used by the original hash calculation.

VoxRubric then recomputes every hash independently through:

```text
audit_chain_integrity
```

This means the evaluator does not have to trust Nora's own `verified=true` statement.

## What this protects against

The chain can detect:

- modified event payload;
- modified event type;
- modified event timestamp;
- changed turn reference;
- changed event order;
- deleted middle event;
- replaced previous hash;
- stale/incorrect declared chain head.

## What this does not protect against

A hash chain alone does not prevent an attacker with full system control from replacing the entire database and generating a new chain.

Stronger production guarantees can add:

- external immutable log sink;
- signed checkpoints;
- KMS-backed signing keys;
- periodic chain-head anchoring;
- write-once object storage;
- organization audit export.

The current implementation establishes deterministic tamper evidence and independent export verification.
