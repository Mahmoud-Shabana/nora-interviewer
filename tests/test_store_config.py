from nora_interviewer.config import build_store
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
