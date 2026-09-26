# Nora v0.5 Deployment Reference

This reference configuration shows how the v0.5 production boundaries fit together. It is a template, not a substitute for deployment-specific secret management, identity administration, storage policy, or legal review.

## Recommended topology

```text
Browser / client
      |
      v
OIDC identity provider
      |
      v
Nora API instances
  |       |        |
  |       |        +--> Remote sandbox service
  |       +-----------> Encrypted artifact/object storage
  +-------------------> PostgreSQL
      |
      +--> STT/TTS providers
      +--> Interview brain / Evidence Judge providers
      +--> VoxRubric export pipeline
```

Nora API instances should not execute hostile candidate code directly in production.

## Identity

Organization-scoped OIDC:

```bash
export NORA_AUTH_MODE=oidc
export NORA_OIDC_JWKS_URL=https://id.example/.well-known/jwks.json
export NORA_OIDC_ISSUER=https://id.example/
export NORA_OIDC_AUDIENCE=https://nora.example
export NORA_OIDC_ORGANIZATION_ID=acme
export NORA_OIDC_ORGANIZATION_CLAIM=org_id
export NORA_OIDC_GROUPS_CLAIM=groups
export NORA_OIDC_ROLE_MAPPING='{"acme-candidates":"candidate","acme-recruiters":"recruiter","acme-reviewers":"reviewer"}'
```

Use your identity provider's stable subject identifier. Do not map external groups to Nora's internal `service` role.

## Database

For multi-instance deployments:

```bash
export NORA_STORE_MODE=postgres
export NORA_POSTGRES_DSN=postgresql://nora:<secret>@postgres.example/nora
export NORA_POSTGRES_MIN_SIZE=1
export NORA_POSTGRES_MAX_SIZE=10
export NORA_POSTGRES_TIMEOUT_SECONDS=30
```

Use TLS and managed credentials according to your PostgreSQL environment.

## Artifact storage

Built-in encrypted local storage is appropriate for a single-node deployment:

```bash
export NORA_ARTIFACT_STORE_MODE=encrypted-local
export NORA_ARTIFACT_LOCAL_PATH=/var/lib/nora/artifacts
export NORA_ARTIFACT_ENCRYPTION_KEY_B64=<base64-encoded-32-byte-key>
export NORA_ARTIFACT_ENCRYPTION_KEY_ID=primary
export NORA_ARTIFACT_SIGNING_SECRET=<minimum-32-byte-secret>
export NORA_ARTIFACT_MAX_BYTES=52428800
export NORA_ARTIFACT_ACCESS_TTL_SECONDS=300
```

For multi-instance production, implement the same `ArtifactObjectStore` boundary against managed object storage/KMS rather than sharing local filesystems.

## Remote sandbox

```bash
export NORA_SANDBOX_MODE=remote
export NORA_SANDBOX_REMOTE_URL=https://sandbox.example
export NORA_SANDBOX_REMOTE_TOKEN=<service-token>
export NORA_SANDBOX_REMOTE_TIMEOUT_SECONDS=35
```

The sandbox service must enforce its own isolation controls. Nora requests no network, ephemeral filesystem, non-privileged execution, and explicit resource limits.

## Voice

```bash
export NORA_STREAMING_STT_MODE=websocket-json
export NORA_STREAMING_STT_URL=wss://stt.example/v1/stream
export NORA_STREAMING_STT_TOKEN=<secret>

export NORA_STREAMING_TTS_MODE=websocket-json
export NORA_STREAMING_TTS_URL=wss://tts.example/v1/stream
export NORA_STREAMING_TTS_TOKEN=<secret>
```

Provider credentials should be stored outside source control.

## Interview brain

```bash
export NORA_BRAIN_MODE=openai-compatible
export NORA_LLM_BASE_URL=https://provider.example/v1
export NORA_LLM_MODEL=<model>
export NORA_LLM_API_KEY=<secret>
```

Evidence judging should use separate provider/model credentials where possible:

```bash
export NORA_EVIDENCE_JUDGE_MODE=openai-compatible
export NORA_EVIDENCE_JUDGE_BASE_URL=https://provider.example/v1
export NORA_EVIDENCE_JUDGE_MODEL=<independent-model>
export NORA_EVIDENCE_JUDGE_API_KEY=<separate-secret>
```

## Operations

Protect these endpoints behind recruiter/reviewer/service authorization:

```text
GET /health
GET /health/ready
GET /v1/system/capabilities
GET /v1/system/operations
GET /v1/system/slo
GET /v1/system/metrics
```

Nora's Prometheus labels are intentionally bounded and should not contain candidate/session transcript identifiers.

## Secret classes

Treat these as deployment secrets:

- OIDC administrative/configuration secrets where applicable;
- PostgreSQL credentials;
- artifact encryption keys;
- artifact signed-access secret;
- sandbox service token;
- STT/TTS provider tokens;
- LLM/Evidence Judge API keys.

Do not reuse the artifact encryption key as the signed-access secret.

## Minimum production controls

A production deployment should additionally provide:

- TLS termination and strict HTTPS/WSS;
- rate limiting and request-size limits at the edge;
- centralized secret management/KMS;
- database backups and restore drills;
- managed object-store lifecycle controls;
- dedicated sandbox isolation;
- audit-log access controls;
- retention/deletion policy;
- observability and alerting;
- organization identity lifecycle;
- jurisdiction-specific privacy/employment review.
