# Request & WebSocket Correlation Tracing

Nora assigns a bounded correlation identifier to every HTTP request and WebSocket connection.

The purpose is operational traceability:

- connect a transport request to audit events it created;
- investigate a failed voice interaction without using candidate data as a correlation key;
- group application logs and downstream provider calls around one request/connection;
- keep trace identifiers independent from candidate, session, job, and turn identifiers.

## HTTP

Clients may provide:

```http
X-Request-ID: client-trace-1234
```

Nora accepts only bounded identifiers matching a conservative character set and length. Invalid or missing values are replaced with a Nora-generated identifier.

The resolved identifier is returned on the response:

```http
X-Request-ID: client-trace-1234
```

Generated request IDs use a random UUID-derived value and do not encode user information.

## WebSockets

Interview, STT-audio, and TTS WebSocket handlers use the same `X-Request-ID` input convention.

If a valid ID is not supplied, Nora generates a connection-scoped ID with a `ws_` prefix.

Async tasks created from that connection inherit the correlation context, including provider-stream tasks.

## Audit events

New audit events created inside an active request/connection context include:

```json
{
  "payload": {
    "_trace": {
      "correlation_id": "client-trace-1234"
    }
  }
}
```

The trace metadata is inside the event payload and therefore participates in Nora's existing tamper-evident event hash.

This design preserves compatibility with previously sealed histories:

- old events remain unchanged;
- their historical hashes are still recomputed using their original payloads;
- new events simply contain additional payload metadata before they are sealed.

## Privacy

A correlation ID must not intentionally encode:

- candidate name or candidate reference;
- email address;
- job ID;
- session ID;
- phone number;
- transcript content;
- assessment result;
- secret or credential.

Nora validates the syntax and length of client-supplied IDs, but deployments should still generate opaque identifiers rather than meaningful strings.

Correlation IDs are not exported as Prometheus labels. Global metrics remain low-cardinality and privacy-minimized.

## Distributed systems

A deployment can use `X-Request-ID` as the application-level correlation key across:

```text
load balancer
    ↓
Nora API
    ↓
interview orchestration
    ↓
STT / TTS gateway
    ↓
audit trail
```

This is intentionally simpler than a full OpenTelemetry implementation. A future tracing adapter can map Nora correlation IDs to W3C trace context without changing the interview/audit domain model.
