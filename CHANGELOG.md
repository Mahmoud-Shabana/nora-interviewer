# Changelog

All notable Nora Interviewer development changes are documented here.

The project is currently alpha-stage. The main branch can contain features that are newer than the latest package metadata.

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
