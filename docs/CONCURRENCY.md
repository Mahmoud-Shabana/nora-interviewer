# Session Concurrency and ETags

Nora protects interview state at two layers:

1. **storage optimistic concurrency**;
2. **optional HTTP ETag preconditions**.

The goal is to prevent silent lost updates when two writers act on the same interview session.

## Storage version

Every `InterviewSession` has:

```json
{
  "version": 7
}
```

A store write succeeds only when the writer's in-memory version matches the currently persisted version.

Conceptually:

```text
writer loads v7
      |
another writer saves v8
      |
first writer tries to save v7
      |
      v
StoreConflictError
```

The API maps storage conflicts to:

```text
409 Conflict
```

This is the final server-side protection against races.

## HTTP ETag

`GET /v1/sessions/{id}` returns:

```http
ETag: "nora-session-<session-id>-v7"
X-Nora-Session-Version: 7
Cache-Control: no-store
```

A client may send that ETag on a later mutation:

```http
If-Match: "nora-session-<session-id>-v7"
```

If the session is still on that version, the request proceeds.

If the session has already moved to another version, Nora returns:

```text
412 Precondition Failed
```

with the current ETag and version in the error detail.

## Why both 412 and 409 exist

They cover different races.

### 412 — stale client state

The client submits an ETag that is already stale when the request reaches Nora.

### 409 — concurrent server write

The client precondition was current when checked, but another server operation committed before this operation persisted its result.

The storage compare-and-swap still catches that race.

## Backward compatibility

`If-Match` is optional.

Existing clients that do not use conditional requests continue to work, while newer clients can opt into stronger stale-state protection.

## Protected REST mutations

The session ETag precondition is accepted on:

- interview start;
- candidate responses;
- candidate controls;
- coding challenge creation;
- generic tool creation;
- tool submission;
- transcript corrections;
- appeal submission;
- appeal review;
- integrity signal submission;
- integrity review;
- explicit evidence observations.

WebSocket flows do not require client ETags because the server-side optimistic store remains authoritative.

## Client pattern

A safe REST client can follow this loop:

```text
GET session
   |
   +--> capture ETag
   |
POST mutation with If-Match
   |
   +--> 2xx: continue
   |
   +--> 412: reload session and reconcile
   |
   +--> 409: another write won after the precondition check;
             reload and retry only if the user action is still valid
```

Clients should not blindly replay a rejected mutation when the underlying interview state has materially changed.
