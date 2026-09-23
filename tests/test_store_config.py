from nora_interviewer.config import build_store
from nora_interviewer.postgres_store import PostgresStore
from nora_interviewer.sqlite_store import SqliteStore
from nora_interviewer.storage import InMemoryStore


def test_store_defaults_to_memory(monkeypatch):
    monkeypatch.delenv(
        "NORA_STORE_MODE",
        raising=False,
    )
    store = build_store()
    assert isinstance(store, InMemoryStore)


def test_store_can_build_sqlite_backend(monkeypatch, tmp_path):
    path = tmp_path / "configured.db"
    monkeypatch.setenv(
        "NORA_STORE_MODE",
        "sqlite",
    )
    monkeypatch.setenv(
        "NORA_SQLITE_PATH",
        str(path),
    )

    store = build_store()
    assert isinstance(store, SqliteStore)
    assert path.exists()


def test_sqlite_store_rejects_empty_path(monkeypatch):
    monkeypatch.setenv(
        "NORA_STORE_MODE",
        "sqlite",
    )
    monkeypatch.setenv(
        "NORA_SQLITE_PATH",
        "",
    )

    try:
        build_store()
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "cannot be empty" in str(exc)


def test_store_can_build_postgres_backend_without_connecting(monkeypatch):
    monkeypatch.setenv(
        "NORA_STORE_MODE",
        "postgres",
    )
    monkeypatch.setenv(
        "NORA_POSTGRES_DSN",
        "postgresql://nora:secret@db.example/nora",
    )
    monkeypatch.setenv(
        "NORA_POSTGRES_MIN_SIZE",
        "0",
    )
    monkeypatch.setenv(
        "NORA_POSTGRES_MAX_SIZE",
        "12",
    )

    store = build_store()
    assert isinstance(store, PostgresStore)
    assert store.min_size == 0
    assert store.max_size == 12
    assert store._opened is False


def test_postgres_store_requires_dsn(monkeypatch):
    monkeypatch.setenv(
        "NORA_STORE_MODE",
        "postgres",
    )
    monkeypatch.delenv(
        "NORA_POSTGRES_DSN",
        raising=False,
    )

    try:
        build_store()
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "NORA_POSTGRES_DSN" in str(exc)
