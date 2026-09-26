# Encrypted Artifact Storage

Nora v0.5 introduces a provider-neutral artifact object-store boundary for candidate artifacts and retained audio objects.

The default remains disabled.

## Goals

The artifact layer is designed to keep binary candidate data outside the interview API state document while retaining auditable metadata in the session.

It provides:

- provider-neutral object storage;
- AES-256-GCM encrypted local storage;
- SHA-256 plaintext integrity metadata;
- signed, expiring bearer access tokens;
- session and organization scoping;
- creation, successful access, and deletion audit events;
- retention integration before session deletion;
- bounded upload size.

## Install

The encrypted local provider uses the optional artifacts dependency:

```bash
pip install -e '.[artifacts]'
```

## Configuration

Enable encrypted local storage:

```bash
export NORA_ARTIFACT_STORE_MODE=encrypted-local
export NORA_ARTIFACT_LOCAL_PATH=.nora/artifacts
export NORA_ARTIFACT_ENCRYPTION_KEY_B64=<base64-encoded-32-byte-key>
export NORA_ARTIFACT_ENCRYPTION_KEY_ID=primary
export NORA_ARTIFACT_SIGNING_SECRET=<at-least-32-byte-secret>
```

Optional limits:

```bash
export NORA_ARTIFACT_MAX_BYTES=52428800
export NORA_ARTIFACT_ACCESS_TTL_SECONDS=300
```

The encryption key must decode to exactly 32 bytes.

The encryption key and signing secret must be supplied by deployment secret management. They are not written beside ciphertext.

## Storage envelope

The encrypted-local provider stores each object as an authenticated AES-GCM envelope.

Object keys are SHA-256 hashed before becoming filesystem paths, so caller-controlled artifact identifiers do not become filesystem paths.

The AES-GCM associated data binds the encrypted object to:

- the Nora artifact storage key;
- the declared content type;
- the versioned Nora artifact envelope domain.

Any authentication failure is treated as storage corruption/tampering and the plaintext is not returned.

## Session metadata

The session stores only artifact metadata:

```text
artifact id
storage key
kind
media type
plaintext byte size
plaintext SHA-256
created timestamp / actor
deleted timestamp / actor / reason
```

Binary payloads are not embedded into the interview session document.

## API flow

Upload raw bytes:

```text
POST /v1/sessions/{session_id}/artifacts?kind=document&media_type=application/pdf
```

The request body is streamed and rejected once it exceeds the configured artifact size limit.

List active artifacts:

```text
GET /v1/sessions/{session_id}/artifacts
```

Issue a short-lived access grant:

```text
POST /v1/sessions/{session_id}/artifacts/{artifact_id}/access
```

The response contains a signed token and expiry timestamp.

Redeem the token:

```text
GET /v1/artifacts/content?token=<signed-token>
```

Successful content access recomputes the plaintext SHA-256 before returning bytes and records an `artifact_accessed` audit event.

Delete an artifact:

```text
DELETE /v1/sessions/{session_id}/artifacts/{artifact_id}
```

Deletion removes the encrypted object and writes deletion provenance into the session audit history.

## Authorization

Artifact permissions remain session-scoped.

Candidate principals can create, read, and delete artifacts only in their own session.

Recruiters can read and delete artifacts within sessions they are authorized to access.

Reviewers have read access for authorized sessions.

The internal service principal retains all permissions.

Organization-scoped OIDC enforcement happens before artifact permissions, so a valid role cannot cross organization boundaries.

## Retention

When session retention is executed with `dry_run=false`, Nora purges active encrypted artifacts before deleting the session record.

If encrypted artifact objects exist but the configured artifact provider is unavailable/disabled, retention does not silently discard the session while leaving unknown binary objects behind.

## Operational constraints

The built-in encrypted-local provider is appropriate for local/single-node deployments and establishes the encryption/provider contract.

Multi-instance production deployments should implement the same object-store interface against managed encrypted object storage with centralized key management.

Signed access tokens are bearer credentials. Keep their TTL short and avoid logging them.
