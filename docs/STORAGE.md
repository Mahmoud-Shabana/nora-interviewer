# Storage Backends

Nora uses a small `Store` protocol so interview orchestration is not coupled to one persistence implementation.

## Store contract

```python
class Store(Protocol):
    async def put_job(self, job: JobSpec) -> None: ...
    async def get_job(self, job_id: str) -> JobSpec | None: ...
    async def put_session(self, session: InterviewSession) -> None: ...
    async def get_session(self, session_id: str) -> InterviewSession | None: ...
```

The complete session model contains:

- transcript turns;
- evidence graph;
- transcript revisions;
- appeals;
- integrity signals;
- practical tools;
- tool submissions/evaluations;
- event log;
- voice audit metadata.

## Memory mode

```bash
NORA_STORE_MODE=memory
```

Characteristics:

- zero configuration;
- fastest test/demo startup;
- process-local;
- all state disappears on restart.

This remains the default.

## SQLite mode

```bash
NORA_STORE_MODE=sqlite
NORA_SQLITE_PATH=.nora/nora.db
```

Characteristics:

- durable local database;
- standard-library `sqlite3`;
- WAL journaling;
- indexed job and candidate references;
- whole Pydantic models persisted as canonical JSON;
- process-local asyncio write lock;
- upsert semantics.

SQLite is useful for local development, demonstrations, and simple single-process deployments.

## Concurrency boundary

The current SQLite backend stores a session as one JSON document.

This preserves the complete event/evidence state cleanly, but it does not implement optimistic row versioning for multiple Nora application instances.

Production multi-instance persistence should add:

- transactional updates;
- optimistic concurrency/version columns;
- explicit migrations;
- connection pooling;
- backup/restore procedures;
- encryption and access-control policy.

PostgreSQL remains the intended production-class backend direction.

## Configuration

`.env.example` documents all current settings.

The API creates its persistence backend with `build_store()`, while the orchestration and voice layers depend only on the `Store` protocol.
