# Nora Operations & Observability

Nora exposes a deliberately privacy-minimized operations surface for runtime monitoring.

The goal is to answer operational questions such as:

- How many sessions are currently retained?
- How many require human review?
- Are semantic evidence runs stale or failing?
- Are STT/TTS providers healthy?
- Is a voice-provider circuit open?
- How many audio/TTS streams are active?
- How much current audit/tool/evidence activity exists?

It does **not** export candidate text, candidate references, session IDs, job IDs, turn IDs, transcript content, artifact content, or credentials as metric labels.

## Protected endpoints

Both endpoints require the global `READ_SYSTEM` permission.

```text
GET /v1/system/operations
GET /v1/system/metrics
```

Candidates cannot access either endpoint.

### JSON snapshot

`/v1/system/operations` returns a structured snapshot containing:

- session counts by lifecycle state;
- recruiter review workload;
- pending appeals;
- pending integrity signals;
- unresolved practical-tool review items;
- stale and failed semantic evidence runs;
- voice-provider health snapshots;
- active/tracked STT audio streams;
- active TTS streams;
- retained event, voice-event, tool, and evidence-run counts.

The snapshot intentionally aggregates across sessions. It does not include per-candidate or per-session identifiers.

### Prometheus exposition

`/v1/system/metrics` emits Prometheus text exposition with bounded labels.

Example:

```text
nora_sessions_current 12
nora_sessions_by_status{status="running"} 3
nora_review_required_sessions 2
nora_stale_evidence_runs 1
nora_active_audio_streams 1
nora_active_tts_streams 0
nora_voice_provider_info{key="streaming_stt",provider_id="websocket-json",state="healthy"} 1
```

Labels are intentionally limited to low-cardinality operational dimensions such as:

- session status;
- provider key;
- provider implementation ID;
- provider health state.

Never add candidate IDs, session IDs, job IDs, emails, names, transcript text, artifact IDs, or arbitrary error messages as Prometheus labels.

## Voice provider health

Nora maintains process-local health state for configured streaming STT and TTS providers.

States:

```text
healthy
degraded
open
disabled
```

The circuit breaker is configured with:

```bash
export NORA_VOICE_PROVIDER_FAILURE_THRESHOLD=3
export NORA_VOICE_PROVIDER_COOLDOWN_SECONDS=20
```

A provider becomes degraded after failures. After the configured consecutive-failure threshold, its circuit opens for the cooldown period.

After cooldown, the next call acts as a probe. The provider is only marked healthy after useful stream output is observed:

- a valid STT transcript event; or
- a valid TTS audio chunk.

A successful socket connection alone does not reset a failing circuit.

## Voice transport continuity

The interview audit log records:

```text
voice_transport_selected
voice_provider_failed
voice_transport_fallback
```

This lets Nora distinguish:

- server STT/TTS selected normally;
- provider failure;
- server-to-browser fallback;
- browser transport actually selected after fallback.

VoxRubric consumes these events through `voice_transport_continuity` so fallback behavior can be regression-tested without relying on infrastructure logs.

## Security notes

The operations endpoints are not public health checks.

Use:

```text
GET /health
GET /health/ready
```

for liveness/readiness.

Use the protected operations endpoints for authenticated operators, monitoring collectors, or internal services.

In multi-instance deployments, the current provider circuit breaker is process-local. A shared circuit state can be added later if a deployment requires globally coordinated provider isolation.

## Privacy regression requirement

Any new operational metric should pass this test:

> Can its name, value, or label reveal a candidate, a particular interview, interview content, or a secret?

If yes, it does not belong in the global metrics endpoint.

Per-session diagnostics should remain in authenticated session/audit APIs instead.
