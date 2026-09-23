# Authorization Model

Nora separates **authentication** from **authorization**.

Authentication answers:

> Who is making this request?

Authorization answers:

> What is that principal allowed to do to this resource?

The current main branch implements the authorization policy and three principal resolvers: local disabled mode, development header mode, and production-oriented JWT/JWKS mode.

## Roles

```text
candidate
recruiter
reviewer
service
```

### Candidate

Candidate permissions are intentionally narrow:

- run their own interview;
- use candidate controls;
- correct their own transcript;
- submit an appeal;
- read their own feedback;
- submit a practical artifact;
- read their own session;
- use realtime voice for their own session.

A candidate principal must carry `candidate_ref`, and Nora checks it against the session.

### Recruiter

Recruiter permissions include:

- create jobs;
- create sessions;
- open practical tools;
- read sessions;
- read event/replay data;
- run counterfactual replay;
- export VoxRubric traces.

Recruiters do not impersonate candidate answers through the interview-response endpoint.

### Reviewer

Reviewer permissions include:

- read session/audit data;
- read candidate feedback;
- write explicit evidence observations;
- submit integrity review signals;
- export traces.

Reviewers do not edit candidate transcripts.

### Service

The service role is trusted internal access and currently has all permissions.

## Candidate ownership

For candidate principals, permission checks can include the target `InterviewSession`.

Nora rejects access when:

```text
principal.candidate_ref != session.candidate_ref
```

This ownership check also applies to realtime WebSocket sessions.

## HTTP principal resolvers

### Disabled mode

```bash
NORA_AUTH_MODE=disabled
```

This is the backward-compatible local/demo mode.

Every request is treated as the trusted local service principal.

Do not interpret this mode as production authentication.

### Development header mode

```bash
NORA_AUTH_MODE=dev-header
```

Required headers:

```text
X-Nora-Principal
X-Nora-Role
```

Candidate role additionally requires:

```text
X-Nora-Candidate-Ref
```

Example:

```text
X-Nora-Principal: candidate-user-1
X-Nora-Role: candidate
X-Nora-Candidate-Ref: candidate-123
```

This mode exists for local integration testing only.

Client-controlled role headers are **not** a production authentication mechanism.

## JWT / JWKS mode

For production-oriented Bearer token validation:

```bash
NORA_AUTH_MODE=jwt-jwks
NORA_AUTH_JWKS_URL=https://identity.example/.well-known/jwks.json
NORA_AUTH_ISSUER=https://identity.example/
NORA_AUTH_AUDIENCE=https://api.nora.example
NORA_AUTH_ALGORITHMS=RS256
```

Optional claim mappings:

```bash
NORA_AUTH_PRINCIPAL_CLAIM=sub
NORA_AUTH_ROLE_CLAIM=nora_role
NORA_AUTH_CANDIDATE_REF_CLAIM=candidate_ref
NORA_AUTH_LEEWAY_SECONDS=30
```

Nora validates the JWT signature using the remote JWKS and checks the configured issuer, audience, expiration, and asymmetric signing algorithm.

Security properties:

- algorithms come from Nora configuration, never from token headers;
- HMAC algorithms are rejected in JWKS mode;
- issuer and audience are mandatory;
- JWKS must use HTTPS by default;
- candidate JWTs must include the configured candidate reference claim;
- client-controlled `X-Nora-Role` headers are ignored in JWT mode;
- JWTs cannot obtain the internal `service` role by default.

Service-role JWTs can be enabled only through:

```bash
NORA_AUTH_ALLOW_SERVICE_ROLE=true
```

Local HTTP JWKS endpoints require the explicit development escape hatch:

```bash
NORA_AUTH_ALLOW_INSECURE_JWKS=true
```

Install the optional authentication dependency with:

```bash
pip install -e '.[auth]'
```

## Production direction

The JWT/JWKS resolver provides a production-capable token validation boundary, but deployments still need organization-specific identity lifecycle, key rotation policy, claim issuance, and account administration.

Future adapters can include:

- organization SSO session gateways;
- workload identity/service credentials;
- signed candidate invitation tokens.

The central `AccessPolicy` does not need to change when authentication providers change.

## WebSocket authorization

WebSockets are authorized before the connection is accepted.

Once connected, Nora still checks event-specific permissions:

- candidate control → `candidate_control`;
- voice events → `use_voice`;
- candidate answer → `run_interview`.

This prevents WebSocket transport from becoming an authorization bypass around protected REST routes.
