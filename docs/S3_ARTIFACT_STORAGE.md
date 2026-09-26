# S3-Compatible Artifact Storage

Nora v0.6 adds a managed object-store provider for S3-compatible services.

## Install

```bash
pip install -e '.[s3]'
```

## AWS S3 with SSE-S3

```bash
export NORA_ARTIFACT_STORE_MODE=s3
export NORA_ARTIFACT_S3_BUCKET=nora-artifacts
export NORA_ARTIFACT_S3_REGION=us-east-1
export NORA_ARTIFACT_S3_PREFIX=production
export NORA_ARTIFACT_S3_SSE_MODE=AES256
export NORA_ARTIFACT_SIGNING_SECRET=<minimum-32-byte-secret>
```

AWS credentials are resolved through the normal boto3 credential chain. Do not place access keys in source control.

## AWS S3 with SSE-KMS

```bash
export NORA_ARTIFACT_STORE_MODE=s3
export NORA_ARTIFACT_S3_BUCKET=nora-artifacts
export NORA_ARTIFACT_S3_REGION=us-east-1
export NORA_ARTIFACT_S3_PREFIX=production
export NORA_ARTIFACT_S3_SSE_MODE=aws:kms
export NORA_ARTIFACT_S3_KMS_KEY_ID=<kms-key-arn-or-id>
export NORA_ARTIFACT_SIGNING_SECRET=<minimum-32-byte-secret>
```

When `aws:kms` is selected, a KMS key id is required.

## Other S3-compatible services

Set a custom endpoint:

```bash
export NORA_ARTIFACT_S3_ENDPOINT_URL=https://objects.example
```

Plain HTTP endpoints are rejected unless:

```bash
export NORA_ARTIFACT_S3_ALLOW_INSECURE=true
```

That override is for controlled development environments only.

## Storage semantics

The S3 adapter implements the same `ArtifactObjectStore` contract as encrypted-local storage:

- put;
- get;
- delete.

The session remains the source of artifact metadata and SHA-256 plaintext integrity state.

Nora requires server-side encryption on every uploaded object. The supported modes are:

- `AES256` — SSE-S3;
- `aws:kms` — SSE-KMS.

The provider records itself as `s3` in system capabilities and reports encrypted-at-rest support.

## Object keys

Nora constructs logical object keys from:

```text
organization/session/artifact
```

An optional deployment prefix is added before the logical key.

The S3 adapter never derives authorization from the object key. Session and organization authorization remains inside Nora before access grants are issued.

## Failure behavior

S3 service/network failures are normalized to Nora artifact-storage errors.

Missing objects are reported distinctly as not found where the provider supplies a recognizable not-found code.

Artifact reads still verify the session's SHA-256 checksum before returning plaintext to the caller.

## Credentials and IAM

Prefer workload/instance/container credentials over static access keys.

The Nora workload should have only the bucket actions it needs for its configured prefix:

- PutObject;
- GetObject;
- DeleteObject.

For SSE-KMS, grant only the required KMS permissions for the configured key.

Bucket policy should deny unencrypted writes that do not meet your deployment policy.
