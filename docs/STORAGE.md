# Storage Backends

Nora uses a small asynchronous `Store` protocol so interview orchestration is not coupled to one persistence implementation.

## Store contract

```python
class Store(Protocol):
    async def put_job(self, job: JobSpec) -> None: ...
    async def get_job(self, job_id: str) -> JobSpec | None: ...
    async def put_session(self, session: InterviewSession) -> None: ...
    async def get_session(self, session_id: str) -> InterviewSession | None: ...
    async def list_sessions(self) -> list[InterviewSession]: ...
    async def delete_session(self, session_id: str) -> bool: ...
    async def close(self) -> None: ...
```

The complete session document contains transcript turns, evidence, candidate-rights state, practical artifacts, review signals, realtime voice audit events, and the tamper-evident event chain.

## Optimistic session versioning

All current stores implement the same session version contract.

```text
load v7
  |
another writer saves v8
  |
attempt to save stale v7
  |
StoreConflictError
```

The REST layer can add an earlier stale-client check through ETags. See [Session Concurrency & ETags](CONCURRENCY.md).

## Memory mode

```bash
NORA_STORE_MODE=memory
```

Characteristics:

- zero configuration;
- process-local;
- deep-copy reads;
- optimistic session versioning;
- state disappears on restart.

This remains the default development mode.

## SQLite mode

```bash
NORA_STORE_MODE=sqlite
NORA_SQLITE_PATH=.nora/nora.db
```

Characteristics:

- durable local database;
- Python standard-library `sqlite3`;
- WAL journaling;
- job/candidate indexes;
- canonical Pydantic JSON payloads;
- atomic version-checked session updates;
- safe migration of legacy Nora session tables;
- single-process/local deployment focus.

SQLite is useful for development, demonstrations, and smaller deployments.

## PostgreSQL mode

Install the optional dependency:

```bash
pip install -e '.[postgres]'
```

Configure:

```bash
NORA_STORE_MODE=postgres
NORA_POSTGRES_DSN=postgresql://nora:password@postgres.example/nora
NORA_POSTGRES_MIN_SIZE=1
NORA_POSTGRES_MAX_SIZE=10
NORA_POSTGRES_TIMEOUT_SECONDS=30
```

Characteristics:

- Psycopg 3 asynchronous connections;
- `AsyncConnectionPool`;
- pool opening is lazy rather than import-time;
- schema initialization is automatic and idempotent;
- JSONB job/session documents;
- indexed job and candidate references;
- database-level optimistic compare-and-swap;
- concurrent Nora application instances can share the same store;
- graceful pool shutdown through the FastAPI lifespan.

The session update path uses:

```sql
UPDATE nora_sessions
SET version = :next_version, ...
WHERE id = :id
  AND version = :expected_version
RETURNING version
```

If no row is returned, Nora raises `StoreConflictError` instead of overwriting a newer session.

## PostgreSQL integration test

Unit tests do not require a live database.

A live PostgreSQL regression can be enabled explicitly with:

```bash
export NORA_TEST_POSTGRES_DSN=postgresql://...
pytest tests/test_postgres_integration.py
```

This keeps the ordinary development suite zero-infrastructure while still defining a production-store verification path.

## Operational notes

Production deployments should additionally define:

- PostgreSQL backup and restore procedures;
- TLS/database certificate policy;
- database credentials through a secret manager;
- least-privilege database roles;
- database migration/change-management policy;
- monitoring for pool saturation and connection errors;
- retention/deletion policy;
- encrypted artifact/audio object storage outside the session JSON document.

## Configuration

`.env.example` documents current settings.

The orchestration, review, retention, voice, and evidence layers depend on the `Store` contract instead of checking which backend is active.
