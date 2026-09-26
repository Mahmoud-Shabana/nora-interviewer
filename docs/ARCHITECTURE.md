# Architecture

Nora is an auditable interview orchestration system composed of replaceable layers. The application keeps interview policy, evidence, persistence, voice transport, practical tools, and external evaluation separate so that one provider or model cannot silently own the whole hiring workflow.

```mermaid
flowchart TB
    Client[Candidate / Recruiter Clients]
    API[FastAPI + WebSocket Transport]
    Session[Interview Session Orchestrator]
    Planner[Dual-Lane Planner]
    Brain[Interview Brain]
    Judge[Independent Evidence Judge]
    Tools[Practical Tool Layer]
    Sandbox[Remote Sandbox / Local Dev Boundary]
    Artifact[Encrypted Artifact Object Store]
    Identity[Organization OIDC / JWT Identity]
    Evidence[Skill Evidence Graph]
    Store[Store: Memory / SQLite / PostgreSQL]
    Audit[Tamper-Evident Event Chain]
    Voice[Realtime Voice Coordinator]
    STT[Streaming STT Provider]
    TTS[Streaming TTS Provider]
    Ops[Operations + SLO]
    Export[VoxRubric Export]
    Vox[VoxRubric]

    Client --> Identity
    Identity --> API
    API --> Session
    Session --> Planner
    Session --> Brain
    Session --> Voice
    Voice --> STT
    Voice --> TTS
    Session --> Tools
    Tools --> Sandbox
    Session --> Judge
    Judge --> Evidence
    Tools --> Evidence
    Session --> Evidence
    Session --> Store
    Session --> Artifact
    Evidence --> Store
    Session --> Audit
    Voice --> Audit
    Tools --> Audit
    Store --> Ops
    Voice --> Ops
    Audit --> Export
    Evidence --> Export
    Export --> Vox
```

## Responsibility boundaries

| Layer | Owns | Does not own |
|---|---|---|
| API / WebSocket transport | authenticated request and realtime transport | interview scoring or hiring decisions |
| Session orchestrator | canonical interview lifecycle and turn graph | provider-specific reasoning |
| Dual-lane planner | anchor/adaptive question balance | persistence or evidence truth |
| Interview brain | proposed next interview action | session IDs, permissions, evidence state, final hiring outcome |
| Evidence Judge | semantic observations grounded in literal candidate evidence | verified evidence from transcript alone |
| Practical tool layer | controlled artifact tasks and evaluation lifecycle | unrestricted code execution |
| Voice coordinator | speech/TTS lifecycle, interruption and fallback state | interview scoring |
| Store | durable canonical state and optimistic concurrency | application policy |
| Audit chain | ordered tamper-evident event history | interpretation of hiring suitability |
| Operations / SLO | bounded operational health signals | candidate-level telemetry labels |
| VoxRubric | external system-behavior evaluation | autonomous hiring authority |

## Interview flow

```text
job + rubric
    |
    v
session creation
    |
    v
anchor/adaptive planning
    |
    v
candidate interaction
    |
    +--> transcript / voice events
    +--> practical artifacts
    +--> candidate controls
    |
    v
evidence graph + audit chain
    |
    v
human review / feedback / appeal
    |
    v
VoxRubric export
```

Candidate controls, transcript corrections, appeals, integrity signals, practical-tool results, semantic-evidence observations, and voice events are modeled as explicit state transitions instead of hidden prompt text.

## Persistence and concurrency

Nora uses a provider-neutral Store contract with:

- in-memory storage for development;
- SQLite for durable single-node deployments;
- PostgreSQL for multi-instance deployments;
- optimistic session versioning;
- REST ETag / If-Match preconditions;
- storage-level stale-writer rejection.

A stale writer must fail rather than overwrite newer interview state.

## Evidence architecture

Evidence is stored as job-scoped provenance, not as an opaque model score.

```text
candidate answer / artifact
          |
          v
literal provenance
          |
          v
EvidenceObservation
          |
          v
Skill Evidence Graph
          |
          +--> recruiter review
          +--> candidate feedback
          +--> VoxRubric export
```

Transcript-only semantic judging is intentionally prevented from upgrading evidence to `verified`. Verification requires a stronger source such as practical work or another trusted process.

## Practical tool boundary

The interview brain may request only templates permitted by the active job policy. Server-owned template definitions control allowed competencies, tool budgets, hidden evaluator state, and execution boundaries.

Candidate code is never executed inside the Nora API process. The local Docker runner is a development/CI isolation option; production hostile-code execution should use a dedicated external sandbox service.

## Realtime voice architecture

Browser audio can stream to Nora's server STT path, while interviewer speech can stream back through server TTS. Both directions are provider-neutral.

Provider health is guarded by a circuit breaker. Repeated failures can degrade or open a provider circuit, and fallback telemetry is written to the audit stream. Browser speech APIs remain a fallback path where available.

Voice lifecycle state is independent from interview evidence state.

## Security and governance boundaries

Nora separates:

- authentication from authorization;
- candidate ownership from recruiter/reviewer permissions;
- interview generation from semantic evidence judging;
- operational health from candidate-level data;
- integrity signals from automatic rejection;
- system evaluation from final hiring decisions.

Prometheus-compatible operational metrics intentionally avoid candidate, session, job, turn, transcript, and artifact identifiers as metric labels.

## Audit and replay

Material state changes are recorded as ordered events with a SHA-256 hash chain. Replay verifies ordering and integrity before reconstructing state. The VoxRubric export contains sufficient canonical audit information for independent chain verification.

## External evaluation

Nora exports a provider-neutral trace to VoxRubric. VoxRubric evaluates orchestration behavior, evidence grounding, governance, practical-tool integrity, voice behavior, ASR preservation benchmarks, and regression fixtures independently from Nora's interview brain.

This separation is intentional: the system that conducts the interview should not be the only system judging whether the interview process behaved correctly.

## Deployment replacement points

The following components are deliberately replaceable:

- InterviewBrain
- semantic Evidence Judge
- STT provider
- TTS provider
- Store backend
- sandbox / practical evaluator
- authentication principal resolver
- object/audio storage
- external evaluation pipeline

Production deployments should additionally provide encrypted object storage, dedicated hostile-code sandboxing, secret management, rate limiting, audit-access controls, jurisdiction-specific retention policy, and organization-specific identity integration.


## Threat boundaries

Nora v0.6 maintains the v0.5 trust boundaries and adds explicit integration, workload, resilience, and portability boundaries.

### Identity boundary

OIDC/JWT verification authenticates a principal, while `AccessPolicy` authorizes operations. Organization identity is carried into jobs, rubric drafts, and sessions. A valid role from one organization does not authorize access to another organization's session.

The internal `service` role is not grantable through organization OIDC.

### Artifact boundary

Binary candidate artifacts are separated from the session document through `ArtifactObjectStore`.

The built-in local provider encrypts objects with AES-256-GCM and binds storage key/content type as associated data. Session state stores metadata/checksums, not plaintext binary payloads. Signed access tokens are short-lived bearer credentials and are separate from the encryption key.

### Sandbox boundary

Candidate code is not executed by the FastAPI process. Production-oriented deployments use `nora.sandbox.v1` to dispatch to an independent sandbox service with explicit CPU, memory, process, timeout, network, filesystem, and privilege policy.

A sandbox transport failure becomes a manual-review state, not a candidate failure.

### Model boundary

The Interview Brain proposes interview actions but does not own IDs, authorization, session persistence, evidence state, tool policy, or the final hiring decision.

The Evidence Judge is independently configurable and cannot upgrade transcript-only evidence to verified evidence.

### Language boundary

Arabic dialect and code-switch metadata describe transcript behavior only. Nora does not treat dialect, accent, nationality, or language prestige as hiring evidence.

### Operational boundary

Operations/SLO metrics intentionally avoid high-cardinality candidate, session, turn, transcript, or artifact identifiers in metric labels.

### Human-decision boundary

Structured practical evaluators may validate deliverables and record provenance, but document/data/system-design evaluators do not produce an automatic hiring score. Integrity signals also remain human-review inputs.

## v0.5 data flow

```mermaid
flowchart LR
    IdP[OIDC Identity Provider] --> API[Nora API]
    API --> DB[(PostgreSQL / Store)]
    API --> Obj[Encrypted Artifact Store]
    API --> SB[Remote Sandbox]
    API --> STT[STT Provider]
    API --> TTS[TTS Provider]
    API --> Brain[Interview Brain]
    API --> Judge[Evidence Judge]
    DB --> Export[VoxRubric Trace]
    Obj -. provenance .-> DB
    SB -. execution provenance .-> DB
    STT -. language metadata .-> DB
    Export --> Vox[VoxRubric]
```


## v0.6 integration boundaries

### Workload identity boundary

Human OIDC and service workload JWTs use distinct issuer/audience configuration. Human group mapping cannot grant the internal service role. A service workload can carry an organization scope; when present, that scope is enforced on session access.

### Managed object-store boundary

The S3-compatible artifact provider preserves Nora's object-store abstraction while requiring server-side encryption on writes. The API never derives authorization from bucket/object keys, and portable evidence exports do not expose storage keys.

### Webhook boundary

Outbound webhooks are emitted only for an allowlisted event set. Raw audit payloads, transcript text, candidate answers, artifact contents, evidence quotes, candidate references, and integrity details are not copied into webhook bodies.

Webhook signing secrets are independent from artifact access/encryption secrets.

### Provider resilience boundary

Brain/Judge/Rubric completion providers and the remote sandbox have bounded timeout/retry/circuit contracts. Circuit state is observable without exposing provider credentials or prompt content.

Fallback decisions retain degraded-mode provenance so provider failure is visible in audit/export metadata.

### Evidence portability boundary

`nora.evidence.bundle.v1` exports active evidence provenance plus cryptographic anchors to artifacts, the audit chain, and VoxRubric output. Backend object locations remain private.

## v0.6 data flow

```mermaid
flowchart LR
    Human[Human Client] --> OIDC[Organization OIDC]
    Workload[Service Workload] --> WID[Workload JWT]
    OIDC --> API[Nora API]
    WID --> API
    API --> DB[(PostgreSQL / Store)]
    API --> S3[S3-compatible Artifact Store]
    API --> Sandbox[Remote Sandbox]
    API --> Providers[Brain / Judge / Rubric Providers]
    DB --> Hooks[Signed Webhooks]
    DB --> Bundle[Portable Evidence Bundle]
    DB --> Vox[VoxRubric Trace]
    Providers --> Resilience[Retry / Circuit State]
    Sandbox --> Resilience
    Resilience --> Ops[System Resilience Endpoint]
```
