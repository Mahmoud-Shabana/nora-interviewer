# Provider Resilience

Nora v0.6 adds a shared resilience contract for model/judge/rubric providers and the remote sandbox.

## Completion providers

OpenAI-compatible completion providers now support:

- request timeout budget;
- bounded retry attempts;
- bounded exponential backoff;
- retryable HTTP classification;
- consecutive-failure circuit breaker;
- cooldown and half-open recovery;
- protected resilience-state reporting.

Configuration prefixes:

```text
NORA_LLM_*
NORA_EVIDENCE_JUDGE_*
NORA_RUBRIC_DRAFTER_*
```

Each prefix supports:

```text
_TIMEOUT_SECONDS
_MAX_ATTEMPTS
_RETRY_BASE_SECONDS
_FAILURE_THRESHOLD
_COOLDOWN_SECONDS
```

Example:

```bash
export NORA_LLM_TIMEOUT_SECONDS=20
export NORA_LLM_MAX_ATTEMPTS=2
export NORA_LLM_RETRY_BASE_SECONDS=0.25
export NORA_LLM_FAILURE_THRESHOLD=3
export NORA_LLM_COOLDOWN_SECONDS=20
```

## Retry classification

The shared HTTP retry classifier treats these as transient:

- 408;
- 409;
- 425;
- 429;
- HTTP 5xx.

Other non-2xx responses are not automatically retried.

Transport timeouts and request errors are retryable up to the configured attempt budget.

## Circuit behavior

A provider starts in `closed`.

After the configured number of consecutive failures it enters `open` and fails fast.

After the cooldown it moves to `half_open`; the next successful call closes the circuit, while another failure reopens it.

## Brain fallback provenance

When the LLM interview brain fails and Nora uses its deterministic fallback brain, the resulting decision reason is prefixed with:

```text
degraded_fallback:<ErrorType>:
```

That marker flows into interviewer-turn decision metadata and the audit/export path, so degraded operation is not silent.

## Evidence Judge behavior

Evidence Judge provider failures remain non-fatal to the interview flow.

Provider/circuit failures are captured by the existing evidence-judge failure path rather than being converted into unsupported evidence.

## Remote sandbox resilience

The remote sandbox now uses:

- request timeout budget;
- bounded retry;
- shared retry classification;
- circuit breaker;
- cooldown recovery.

When unavailable, the coding evaluator continues to produce an explicit manual-review state rather than a false candidate failure.

## Operator endpoint

Protected operators can inspect provider circuit state:

```text
GET /v1/system/resilience
```

The response exposes:

- component path;
- provider ID;
- circuit state;
- consecutive failures;
- total failures;
- total successes;
- remaining open-circuit cooldown.

It does not expose URLs, credentials, API keys, prompts, transcripts, candidate identifiers, or artifact contents.

Voice providers continue to use their dedicated health endpoint because the realtime voice circuit includes transport-specific state.
