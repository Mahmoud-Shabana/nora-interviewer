# Interview Session Lifecycle

Nora models interview sessions as an explicit state machine.

```text
created
   |
   | start
   v
running
  /   \
 /     \
complete cancel
 |       |
 v       v
completed cancelled
```

`completed` and `cancelled` are terminal states.

## Created

A newly created session has:

- explicit AI interview consent;
- explicit transcript consent;
- initialized competency evidence graph;
- no interviewer turns yet.

Calling `start` moves the session to `running`.

## Running

A running session may accept:

- candidate responses;
- candidate controls;
- voice events;
- practical tool submissions;
- transcript corrections;
- appeals.

Session writes use optimistic versioning.

REST clients may also use ETag preconditions. See [Concurrency](CONCURRENCY.md).

## Completed

A completed session:

- has a `completed_at` timestamp;
- cannot accept new candidate answers;
- cannot be cancelled retroactively;
- remains available for feedback, review, replay, and audit export.

The final closing interviewer turn is not counted as an ordinary interview question.

## Cancelled

A cancelled session:

- has `cancelled_at`;
- preserves the cancellation reason;
- leaves the evidence/audit history intact;
- cannot accept new answers, controls, or practical tools;
- cancels any open/submitted practical tool;
- closes active realtime voice state;
- invalidates active TTS generation;
- remains available for review and audit.

Cancellation is idempotent: retrying cancellation on an already-cancelled session does not rewrite the original reason or create duplicate terminal events.

A completed session cannot later be cancelled.

## Cancellation permissions

The application policy allows:

- the candidate to cancel their own session;
- a recruiter to cancel a session;
- the internal service role to cancel sessions.

A reviewer cannot cancel a session.

Candidate ownership rules still apply: one candidate cannot cancel another candidate's interview.

## Audit events

Session cancellation may append:

```text
tool_cancelled
voice_tts_cancelled
session_cancelled
```

The exact tool/voice events depend on what was active when cancellation occurred.

Replay reconstructs:

- terminal session status;
- cancelled tool IDs;
- pause reset;
- ordered event history.

## REST endpoint

```http
POST /v1/sessions/{session_id}/cancel
If-Match: "nora-session-<session-id>-vN"

{
  "reason": "Candidate requested cancellation."
}
```

`If-Match` is optional but recommended for REST clients.

A stale ETag returns `412 Precondition Failed`.

A storage race that occurs after the ETag check returns `409 Conflict`.

## Why cancellation is separate from completion

Completion means the interview protocol reached its intended end.

Cancellation means the protocol was deliberately terminated before completion.

Keeping the states separate prevents analytics, retention logic, replay, and review systems from treating an interrupted interview as a successfully completed one.
