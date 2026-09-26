# External Sandbox Service

Nora v0.5 supports a dedicated remote code-execution boundary through the versioned `nora.sandbox.v1` protocol.

The existing local Docker runner remains available for development. The remote runner is the production-oriented boundary for deployments that do not want untrusted candidate code executed on the Nora API host.

## Configuration

```bash
export NORA_SANDBOX_MODE=remote
export NORA_SANDBOX_REMOTE_URL=https://sandbox.example
export NORA_SANDBOX_REMOTE_TOKEN=<service-token>
export NORA_SANDBOX_REMOTE_TIMEOUT_SECONDS=35
```

HTTPS is required by default.

A development-only escape hatch exists for local HTTP services:

```bash
export NORA_SANDBOX_REMOTE_ALLOW_INSECURE=true
```

## Request contract

Nora sends:

```text
POST {NORA_SANDBOX_REMOTE_URL}/v1/executions/python
```

with a JSON payload shaped as:

```json
{
  "protocol": "nora.sandbox.v1",
  "language": "python",
  "source": "...candidate source...",
  "harness": "...server-owned harness...",
  "limits": {
    "timeout_seconds": 5.0,
    "memory_mb": 256,
    "cpus": 0.5,
    "pids_limit": 64
  },
  "policy": {
    "network_access": false,
    "filesystem": "ephemeral",
    "privileged": false,
    "max_output_bytes": 20000
  }
}
```

The sandbox service is expected to enforce the supplied limits as upper bounds, not suggestions.

## Response contract

A successful sandbox response uses the same protocol version:

```json
{
  "protocol": "nora.sandbox.v1",
  "provider_id": "sandbox-cluster-a",
  "execution_id": "exec_123",
  "result": {
    "exit_code": 0,
    "stdout": "...",
    "stderr": "",
    "timed_out": false,
    "duration_ms": 842,
    "artifacts": [
      {
        "name": "result.json",
        "media_type": "application/json",
        "size_bytes": 120,
        "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "reference": "sandbox://exec_123/result.json"
      }
    ]
  }
}
```

Nora validates the result contract and truncates stdout/stderr to bounded lengths before storing evaluation evidence.

## Policy enforcement before dispatch

Remote execution is not a free-form API from the interview model.

The existing Nora tool path still applies first:

```text
Interview Brain
      |
      v
job-scoped Tool Policy
      |
      v
trusted server template
      |
      v
candidate submission
      |
      v
CodingInterviewTool
      |
      v
SandboxRunner
      |
      +--> Docker
      +--> Remote nora.sandbox.v1
```

This means the interview agent cannot bypass:

- allowed template IDs;
- competency restrictions;
- per-job tool budget;
- duplicate-template prevention;
- hidden test ownership;
- server-owned harness construction.

Only after those controls does a coding submission reach the sandbox runner.

## Failure and degradation behavior

The remote runner converts network failures, timeouts, service overload, gateway errors, protocol mismatch, invalid JSON, and invalid result contracts into `SandboxUnavailable`.

The coding tool already handles `SandboxUnavailable` as a non-fatal review state:

- the candidate submission remains recorded;
- no fake automatic score is produced;
- `passed` and `score` remain unset;
- the evaluation explicitly requires manual/external review.

This prevents a sandbox outage from silently becoming a candidate failure.

## Execution provenance

Sandbox results can retain:

- provider ID;
- execution ID;
- execution duration;
- timeout state;
- exit code;
- bounded stdout/stderr;
- produced artifact name/media type/size/SHA-256/reference.

That provenance is carried into Nora's tool-evaluation evidence.

## Security boundary

The remote sandbox service should independently enforce:

- no outbound network unless a future explicitly authorized task requires it;
- non-privileged execution;
- ephemeral filesystem;
- CPU, memory, process, file-descriptor, and wall-clock limits;
- per-execution isolation;
- bounded output;
- service-to-service authentication;
- deletion/retention policy for generated artifacts and execution logs.

Nora does not treat a successful HTTP response as proof of strong isolation. The deployment remains responsible for the sandbox service's actual isolation technology.
