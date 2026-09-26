# Outbound Webhooks

Nora v0.6 can emit privacy-minimized session lifecycle webhooks after successful session persistence.

## Configuration

Subscriptions are deployment configuration:

```bash
export NORA_WEBHOOK_SUBSCRIPTIONS_JSON='[
  {
    "id": "ats-primary",
    "url": "https://ats.example/webhooks/nora",
    "secret": "replace-with-at-least-32-bytes",
    "organization_id": "acme",
    "event_types": [
      "session_created",
      "tool_evaluated",
      "appeal_submitted",
      "review_completed",
      "session_completed"
    ]
  }
]'
```

Optional delivery settings:

```bash
export NORA_WEBHOOK_TIMEOUT_SECONDS=8
export NORA_WEBHOOK_MAX_ATTEMPTS=3
export NORA_WEBHOOK_RETRY_BASE_SECONDS=0.25
```

Plain HTTP endpoints are rejected unless the explicit development override is enabled.

## Privacy-safe event policy

Webhooks deliberately do not forward raw Nora audit payloads.

The outbound body contains only:

- schema version;
- subscription ID;
- organization ID;
- session ID;
- event sequence;
- event type;
- event timestamp;
- audit event hash.

Nora does not include:

- transcript text;
- candidate answers;
- artifact contents;
- evidence quotes;
- appeal text;
- integrity-signal details;
- candidate reference.

Only an allowlisted set of lifecycle/governance/tool/artifact events can be subscribed to. Voice transcript and candidate-turn events are not webhook-safe event types.

## Signing

Every delivery includes:

```text
X-Nora-Webhook-Signature: sha256=<HMAC-SHA256>
X-Nora-Webhook-Event: <event-type>
X-Nora-Webhook-Idempotency-Key: nora:<subscription>:<session>:<seq>
```

The signature is computed over the exact canonical JSON request body with the subscription secret.

Receivers should verify the signature before parsing or acting on the payload.

## Organization scope

A subscription with `organization_id` receives events only for sessions in that organization.

A subscription without organization scope is deployment-global and should be reserved for trusted internal integrations.

## Retry behavior

Nora retries only bounded transient failures:

- network errors/timeouts;
- HTTP 408;
- HTTP 409;
- HTTP 425;
- HTTP 429;
- HTTP 5xx.

Other non-2xx statuses are treated as terminal for that delivery attempt series.

Backoff is bounded exponential delay controlled by deployment settings.

## Idempotency

The idempotency key is deterministic for:

```text
subscription + session + source event sequence
```

Receivers should store processed keys and safely ignore duplicates.

## Audit delivery state

After delivery attempts complete, Nora appends a `webhook_delivery` audit event containing:

- subscription ID;
- source event sequence/type;
- delivered state;
- attempt count;
- status code when available;
- normalized transport error type when available.

Webhook-delivery audit events are never sent back out as webhooks, preventing delivery loops.

Webhook delivery is best-effort. An unavailable integration does not invalidate the primary interview/session state transition.
