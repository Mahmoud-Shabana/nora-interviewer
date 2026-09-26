# Workload Identity

Nora v0.6 separates human identity from machine/service identity.

## Dedicated workload JWT mode

```bash
export NORA_AUTH_MODE=workload-jwt
export NORA_WORKLOAD_JWKS_URL=https://workload-id.example/.well-known/jwks.json
export NORA_WORKLOAD_ISSUER=https://workload-id.example/
export NORA_WORKLOAD_AUDIENCE=https://nora.example/service
export NORA_WORKLOAD_PRINCIPAL_CLAIM=sub
```

A successfully validated workload token is mapped directly to Nora's internal `service` role.

The token does not choose its Nora role. Recruiter/candidate/reviewer role claims in a workload token are ignored.

## Organization-scoped workload

To restrict a workload to one organization:

```bash
export NORA_WORKLOAD_ORGANIZATION_CLAIM=org_id
```

If the token contains that claim, Nora carries it into the service principal and enforces organization isolation on session-scoped operations.

An unscoped internal service principal retains cross-organization administrative behavior.

## Human OIDC + workload JWT together

Production deployments can accept both identity domains:

```bash
export NORA_AUTH_MODE=oidc+workload
```

Configure the normal `NORA_OIDC_*` variables for human identities and the `NORA_WORKLOAD_*` variables for machine identities.

Nora attempts each configured trusted identity domain against the bearer token. Tokens that do not validate in either domain are rejected.

This keeps:

- human issuer/audience separate from workload issuer/audience;
- external human groups mapped only to candidate/recruiter/reviewer roles;
- workload identities fixed to service role;
- optional organization scope on workloads.

## Security notes

Use asymmetric JWT algorithms only.

JWKS URLs require HTTPS unless the explicit development-only insecure override is enabled.

Recommended production settings use distinct audiences for:

- human Nora API access;
- workload/service Nora API access.

Do not issue service-workload tokens from the same role-mapping mechanism used for human recruiter groups.
