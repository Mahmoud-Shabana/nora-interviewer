# Changelog

All notable Nora Interviewer development changes are documented here.

The project is currently alpha-stage. The main branch can contain features that are newer than the latest package metadata.

## 0.6.0 — 2026-09-26

### Managed artifact storage

- Added S3-compatible artifact storage as a production-oriented implementation of the existing ArtifactObjectStore contract.
- Added mandatory server-side encryption with SSE-S3 and SSE-KMS modes.
- Added bucket, prefix, region, endpoint, and KMS-key configuration.
- Added normalized S3 transport/storage failures and distinct not-found handling.
- Added optional `s3` dependency and deployment guidance.

### Workload identity

- Added dedicated service-workload JWT authentication with separate issuer, audience, JWKS, and principal configuration.
- Added optional organization scope for workload identities.
- Added hybrid `oidc+workload` mode for human and machine identity domains in one deployment.
- Prevented workload tokens from choosing candidate, recruiter, or reviewer roles.
- Enforced organization isolation on scoped service principals.

### Outbound webhooks

- Added signed `nora.webhook.v1` lifecycle delivery with HMAC-SHA256 signatures.
- Added deterministic idempotency keys and bounded transient retry behavior.
- Added organization-scoped subscriptions.
- Restricted webhook payloads to privacy-minimized allowlisted lifecycle metadata.
- Added auditable non-recursive `webhook_delivery` events.

### Provider resilience

- Added a reusable provider circuit-breaker contract.
- Added timeout budgets, bounded retries, retry classification, backoff, cooldown, and half-open recovery for OpenAI-compatible providers.
- Added equivalent resilience controls to the remote sandbox.
- Added protected `/v1/system/resilience` circuit-state reporting.
- Added explicit degraded fallback provenance to interview-brain decision reasons.

### Evidence portability

- Added `nora.evidence.bundle.v1` portable evidence exports.
- Added active evidence provenance with grounded quote digests.
- Added artifact ID/media/size/SHA-256 references without exposing backend storage keys.
- Added audit-chain head verification and canonical VoxRubric trace digest.
- Added deterministic bundle digest and organization-scoped export authorization.

### Deployment and architecture

- Added v0.6 production deployment reference.
- Added v0.5 → v0.6 migration guidance.
- Expanded architecture boundaries for workload identity, managed object storage, webhooks, provider resilience, and evidence portability.

### Verification status

- Package, runtime, API, README, changelog, and release-plan metadata are aligned at v0.6.0.
- Runtime tests and GitHub Actions were intentionally not executed during this release pass because of the current account constraint. This entry documents implementation/static-review status and does not claim a fresh runtime test pass.

## 0.5.0 — 2026-09-26

### Organization identity

- Added organization-scoped OIDC authentication with issuer, audience, JWKS, organization-claim, and group-to-role mapping.
- Added organization identity to principals, jobs, rubric drafts, approved jobs, and interview sessions.
- Added cross-organization isolation for session access, review queues, evidence reevaluation, and rubric workflows.
- Prevented organization OIDC from granting Nora's internal service role.

### Encrypted artifacts

- Added a provider-neutral artifact object-store contract.
- Added AES-256-GCM encrypted local artifact storage with hashed filesystem paths.
- Added session-scoped artifact metadata, SHA-256 integrity verification, and auditable create/access/delete lifecycle.
- Added short-lived HMAC-signed artifact access grants.
- Added bounded streaming artifact uploads and retention-time artifact purge.
- Added optional `artifacts` encryption dependency and capability reporting.

### External sandbox

- Added `nora.sandbox.v1` remote execution service support.
- Added explicit CPU, memory, process, timeout, network, filesystem, and privilege policy in remote execution requests.
- Added structured sandbox provider/execution/artifact provenance.
- Made remote sandbox transport/protocol failures degrade to explicit manual review instead of false candidate failure.

### Practical evaluators

- Added structured system-design/case-study, document-analysis, and data-analysis evaluators.
- Added a built-in service-latency data-analysis template.
- Added evaluator ID/version/template provenance to practical evaluations.
- Preserved the human-review boundary for non-coding domain artifacts instead of producing automatic hiring scores.

### Arabic technical interviews

- Added Arabic/English technical vocabulary packs for software engineering, AI/ML, and data engineering.
- Added explicit locale/dialect transcript metadata and Arabic/Latin code-switch detection.
- Added Arabic technical interview ASR preservation fixtures.
- Added VoxRubric-compatible `asr_reference_text`, `asr_critical_terms`, language profiles, and code-switch export fields.
- Kept dialect/accent metadata descriptive and outside hiring evidence.

### Deployment and architecture

- Added a v0.5 deployment reference for OIDC, PostgreSQL, artifact storage, remote sandbox, voice providers, and model providers.
- Added v0.4 → v0.5 migration guidance.
- Expanded architecture documentation with explicit identity, artifact, sandbox, model, language, operational, and human-decision threat boundaries.

### Verification status

- Package, runtime, API, README, changelog, and release-plan metadata are aligned at v0.5.0.
- Runtime tests and GitHub Actions were intentionally not executed during this release pass because of the current account constraint. This entry documents implementation/static review status and does not claim a fresh runtime test pass.

## 0.4.0 — 2026-09-26

### Interview orchestration

- Added dual-lane standardized anchor + adaptive interview planning.
- Added explicit question budgeting and closing-turn handling.
- Added structured candidate controls: repeat, clarify, thinking time, resume, answer correction, and candidate questions.
- Added teacher-forced counterfactual decision replay for policy/model comparison.

### Evidence

- Added the Skill Evidence Graph with claimed, demonstrated, verified, contradicted, and insufficient-evidence states.
- Added evidence provenance back to transcript and artifact turns.
- Added independent semantic Evidence Judge support.
- Added strict literal quote grounding.
- Prevented transcript-only semantic judges from emitting verified evidence.
- Added non-fatal evidence-judge failure audit events.
- Added independently configurable judge-provider credentials.

### Candidate rights and governance

- Added transcript correction while preserving revision history.
- Added candidate appeals tied to exact turns.
- Added candidate-facing evidence feedback.
- Added progressive integrity modes.
- Kept integrity signals explicitly human-review-only.

### Practical tools

- Added provider-neutral interview tool registry.
- Added job-scoped trusted tool-template policy.
- Added coding, case-study, whiteboard, document, and dataset tool types.
- Added hidden-test separation for coding tasks.
- Added constrained local Docker sandbox execution.
- Added artifact provenance and post-tool reasoning follow-ups.
- Added practical-tool outcomes to the evidence graph without automatically upgrading to verified evidence.

### Realtime voice

- Added provider-neutral voice lifecycle state machine.
- Added partial/final transcript events.
- Added TTS lifecycle events.
- Added barge-in and TTS cancellation semantics.
- Added separate speech-to-final, final-to-response, and response-to-TTS timing.
- Exported realtime voice audit events to VoxRubric.

### Authorization

- Added candidate, recruiter, reviewer, and service roles.
- Added centralized permission policy.
- Added candidate session-ownership checks.
- Added development principal resolver using X-Nora-* headers.
- Protected REST interview, tool, evidence, governance, replay, export, retention, and voice routes.
- Protected WebSocket connections and per-event realtime actions.

### Persistence and lifecycle

- Introduced provider-neutral Store protocol.
- Added durable SQLite local backend with WAL mode.
- Added configurable memory/SQLite store selection.
- Added session creation and completion timestamps.
- Added backend-neutral session listing/deletion primitives.
- Added dry-run-first retention manager.
- Added service-only retention API.
- Added candidate-scoped retention previews.

### Operations

- Added protected system capabilities endpoint.
- Added capability reporting for storage, auth resolver, interview brain, semantic judge, sandbox, voice, tools, replay, retention, and VoxRubric export.
- Expanded environment configuration documentation.

### Web experience

- Added built-in interview room.
- Added candidate control toolbar.
- Added practical tool workbench.
- Added browser voice lifecycle integration.
- Added barge-in behavior for browser speech demo.
- Added recruiter-side practical-tool policy selection.

### Documentation

- Added interview protocol documentation.
- Added candidate-rights baseline.
- Added realtime voice protocol.
- Added Evidence Judge design.
- Added authorization model.
- Added storage backend design.
- Added retention lifecycle documentation.
- Redesigned README as a full project landing page.

### Release hardening

- Added PostgreSQL multi-instance persistence with optimistic compare-and-swap.
- Added REST ETag / If-Match concurrency protection.
- Added explicit cancelled-session lifecycle with practical-tool and realtime-voice cleanup.
- Added signed JWT/JWKS authentication and authorization boundaries.
- Added tamper-evident SHA-256 audit-chain sealing and independent export verification.
- Added server streaming STT/TTS, browser STT reconnect/resume, VAD endpointing, and provider circuit breakers.
- Added audited server/browser voice fallback telemetry.
- Added privacy-minimized operational snapshots, Prometheus-compatible metrics, and operational SLO assessment.
- Added Job & Rubric Studio with AI-assisted drafts and explicit recruiter approval.
- Added deterministic end-to-end release-flow and failure/recovery regression coverage.
- Synchronized release architecture and project status documentation for v0.4.0.

## 0.3.0

- Provider-neutral FastAPI interview orchestration.
- Rule-based and OpenAI-compatible interview brains.
- Deterministic fallback brain.
- Browser interview room and WebSocket flow.
- Initial VoxRubric trace export.
- Initial Docker development setup.
