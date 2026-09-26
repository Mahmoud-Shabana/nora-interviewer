# Portable Evidence Bundles

Nora v0.6 adds a portable evidence export that is independent from the recruiter review bundle.

## Endpoint

```text
GET /v1/sessions/{session_id}/evidence-bundle
```

The endpoint uses normal session authorization and organization isolation.

Candidates can export their own session bundle. Recruiters/reviewers can export bundles only for sessions they are authorized to access. Service principals follow the configured service scope.

## Schema

The top-level schema is:

```text
nora.evidence.bundle.v1
```

A bundle contains:

- organization/session/job identity;
- role and locale;
- active evidence records;
- artifact references and plaintext SHA-256 checksums;
- verified audit-chain anchor;
- VoxRubric trace SHA-256 anchor;
- deterministic bundle SHA-256.

## Evidence records

Evidence records include:

- competency ID;
- evidence state;
- confidence;
- source turn ID;
- source type;
- note;
- grounded quote when present;
- SHA-256 of the quote.

The bundle does not contain the full transcript.

## Artifact references

Artifact entries contain:

- artifact ID;
- kind;
- media type;
- byte size;
- plaintext SHA-256;
- deleted state.

The portable bundle does not expose backend storage keys, object-store URLs, encryption keys, or signed access tokens.

## Audit anchor

The bundle verifies the session audit chain before export.

When a sealed chain is present, the bundle records:

- verified=true;
- audit head hash;
- event count;
- hash version.

A tampered sealed chain causes the existing audit verification path to fail instead of exporting a false integrity claim.

## VoxRubric anchor

Nora canonicalizes the generated VoxRubric trace and stores its SHA-256 in the evidence bundle.

This allows a consumer to keep:

```text
portable evidence bundle
        +
VoxRubric trace
```

and verify that the trace corresponds to the exported anchor without embedding the entire trace twice.

## Bundle digest

The bundle contains a deterministic SHA-256 over its portable evidence/artifact/audit/VoxRubric anchor content.

The generated timestamp is intentionally excluded from this digest so equivalent evidence state can be compared across repeated exports.

## Interoperability

The bundle is designed as a stable handoff object for:

- recruiter review archives;
- candidate evidence export;
- independent audit pipelines;
- VoxRubric evaluation workflows;
- external ATS/integration systems.

Consumers should treat evidence state as provenance-rich interview evidence, not as an autonomous hiring decision.
