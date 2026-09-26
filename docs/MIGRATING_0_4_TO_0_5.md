# Migrating from Nora v0.4 to v0.5

v0.5 extends v0.4 with organization identity, encrypted artifacts, remote sandbox execution, structured domain evaluators, and Arabic technical-interview metadata.

## Compatibility

Existing v0.4 deployments can remain in:

```bash
NORA_AUTH_MODE=disabled
NORA_ARTIFACT_STORE_MODE=disabled
NORA_SANDBOX_MODE=disabled
```

until the new boundaries are explicitly configured.

Existing unscoped jobs and sessions continue to deserialize because `organization_id` is optional.

## Organization scoping

v0.5 adds optional `organization_id` to:

- principals;
- jobs;
- interview sessions;
- rubric drafts.

When `NORA_AUTH_MODE=oidc` is enabled, organization-scoped identities cannot create sessions for unscoped or differently scoped jobs.

Recommended migration sequence:

1. configure OIDC;
2. create/approve new organization-scoped jobs;
3. create new sessions from those jobs;
4. keep historical v0.4 sessions read-only or migrate them with an explicit administrative process.

Do not silently assign historical sessions to an organization without a trustworthy ownership source.

## Rubric workflows

New rubric drafts created under organization OIDC inherit the authenticated organization. Approved jobs inherit the same scope.

Cross-organization rubric lookup returns not found.

## Artifacts

Binary artifact storage is new in v0.5 and disabled by default.

Install the optional encryption dependency before enabling the local encrypted provider:

```bash
pip install -e '.[artifacts]'
```

Configure a 32-byte encryption key and a separate signed-access secret.

Retention now purges active artifact objects before deleting a matched session.

## Sandbox

`NORA_SANDBOX_MODE=docker` remains available for local development.

Production deployments can use:

```bash
NORA_SANDBOX_MODE=remote
NORA_SANDBOX_REMOTE_URL=https://sandbox.example
```

The remote service must implement `nora.sandbox.v1`.

Sandbox outages degrade coding submissions to explicit manual review rather than a fabricated failure score.

## Practical evaluators

Case-study/system-design, document-analysis, and dataset tasks now receive structured completeness/provenance evaluation by default.

These evaluators intentionally return no automatic hiring score:

```text
passed = null
score = null
review_required = true
```

If a v0.4 integration assumed all non-coding tools were generic manual-review results, consume the new structured evidence fields instead of matching the old summary string.

## Arabic technical interview metadata

`TranscriptEvent` accepts optional:

- locale;
- dialect;
- vocabulary-pack IDs;
- ASR reference text;
- ASR critical terms.

Existing clients sending only `text` and `confidence` remain compatible.

Candidate turn metadata and VoxRubric export now carry language/code-switch profiles when available.

## API version

The v0.5 release line reports API version `0.5.0`.

Review clients that display capability flags should tolerate the additional OIDC/artifact capabilities.

## Verification note

The v0.5 implementation was prepared while runtime test execution and GitHub Actions were intentionally not run because of the current account constraint. The repository contains existing test infrastructure, but this migration document does not claim runtime verification.
