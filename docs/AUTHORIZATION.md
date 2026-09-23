# Authorization Model

Nora separates **authentication** from **authorization**.

Authentication answers:

> Who is making this request?

Authorization answers:

> What is that principal allowed to do to this resource?

The current main branch implements the authorization policy and two principal resolvers.

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

## Production direction

A production resolver should validate an external identity token or session and produce the same internal `Principal` contract.

Possible adapters include:

- OIDC/JWT;
- organization SSO;
- API service credentials;
- signed candidate invitation tokens.

The central `AccessPolicy` does not need to change when authentication providers change.

## WebSocket authorization

WebSockets are authorized before the connection is accepted.

Once connected, Nora still checks event-specific permissions:

- candidate control → `candidate_control`;
- voice events → `use_voice`;
- candidate answer → `run_interview`.

This prevents WebSocket transport from becoming an authorization bypass around protected REST routes.
