# Nora v0.6 Deployment Reference

Nora v0.6 extends the v0.5 deployment model with managed S3-compatible artifact storage, workload identity, outbound webhooks, provider resilience, and portable evidence exports.

## Recommended topology

```text
Human clients
    |
    v
Organization OIDC
    |
    +----------------------+
                           |
Service workloads          v
    |                 Nora API
    v                    / | \
Workload JWT -----------+  |  +--> Signed webhooks
                          |  |
                          |  +--> Remote sandbox
                          |
                          +----> PostgreSQL
                          +----> S3-compatible object storage
                          +----> STT / TTS
                          +----> Interview Brain
                          +----> Evidence Judge
                          +----> VoxRubric / evidence exports
```

## Human + workload identity

Use both trusted identity domains:

```bash
export NORA_AUTH_MODE=oidc+workload

export NORA_OIDC_JWKS_URL=https://id.example/.well-known/jwks.json
export NORA_OIDC_ISSUER=https://id.example/
export NORA_OIDC_AUDIENCE=https://nora.example/human
export NORA_OIDC_ORGANIZATION_ID=acme
export NORA_OIDC_ROLE_MAPPING='{"candidates":"candidate","recruiters":"recruiter","reviewers":"reviewer"}'

export NORA_WORKLOAD_JWKS_URL=https://workload-id.example/.well-known/jwks.json
export NORA_WORKLOAD_ISSUER=https://workload-id.example/
export NORA_WORKLOAD_AUDIENCE=https://nora.example/service
export NORA_WORKLOAD_ORGANIZATION_CLAIM=org_id
```

Human tokens cannot map to Nora's internal service role. Workload tokens are always interpreted as service identities.

## Managed artifact storage

For AWS S3 with SSE-KMS:

```bash
export NORA_ARTIFACT_STORE_MODE=s3
export NORA_ARTIFACT_S3_BUCKET=nora-artifacts
export NORA_ARTIFACT_S3_REGION=us-east-1
export NORA_ARTIFACT_S3_PREFIX=production
export NORA_ARTIFACT_S3_SSE_MODE=aws:kms
export NORA_ARTIFACT_S3_KMS_KEY_ID=<kms-key-id>
export NORA_ARTIFACT_SIGNING_SECRET=<minimum-32-byte-secret>
```

Install:

```bash
pip install -e '.[s3]'
```

Prefer workload/instance/container credentials instead of static S3 access keys.

## Webhooks

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
      "session_completed"
    ]
  }
]'
```

Recommended receivers should:

- verify `X-Nora-Webhook-Signature`;
- deduplicate `X-Nora-Webhook-Idempotency-Key`;
- return 2xx only after durable acceptance;
- avoid logging secrets or full bearer headers.

## Provider resilience

Example interview-brain settings:

```bash
export NORA_LLM_TIMEOUT_SECONDS=20
export NORA_LLM_MAX_ATTEMPTS=2
export NORA_LLM_RETRY_BASE_SECONDS=0.25
export NORA_LLM_FAILURE_THRESHOLD=3
export NORA_LLM_COOLDOWN_SECONDS=20
```

Equivalent suffixes are available for:

```text
NORA_EVIDENCE_JUDGE_*
NORA_RUBRIC_DRAFTER_*
```

Remote sandbox resilience is configured with:

```text
NORA_SANDBOX_REMOTE_TIMEOUT_SECONDS
NORA_SANDBOX_REMOTE_MAX_ATTEMPTS
NORA_SANDBOX_REMOTE_RETRY_BASE_SECONDS
NORA_SANDBOX_REMOTE_FAILURE_THRESHOLD
NORA_SANDBOX_REMOTE_COOLDOWN_SECONDS
```

Operators can inspect:

```text
GET /v1/system/resilience
```

## Evidence export

Authorized clients can export:

```text
GET /v1/sessions/{session_id}/evidence-bundle
```

The portable bundle contains evidence provenance, artifact checksums, audit-chain anchor, VoxRubric trace digest, and bundle digest without exposing backend object-store locations.

## Existing production settings

Keep the v0.5 recommendations for:

- PostgreSQL;
- remote sandbox isolation;
- STT/TTS providers;
- Brain/Judge provider separation;
- edge rate limiting;
- secret management;
- audit access control;
- retention/deletion policy;
- jurisdiction-specific privacy/employment review.

## Secret inventory

Treat these as secrets:

- database credentials;
- artifact signed-access secret;
- S3/KMS credentials where not using workload identity;
- webhook signing secrets;
- sandbox token;
- STT/TTS tokens;
- Brain/Judge/Rubric API keys;
- IdP administrative credentials.

Do not reuse one secret across artifact access, webhooks, or external providers.
