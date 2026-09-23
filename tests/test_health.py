from fastapi.testclient import TestClient

import nora_interviewer.api as api


def test_liveness_and_readiness_are_distinct():
    with TestClient(api.app) as client:
        live = client.get("/health")
        ready = client.get("/health/ready")

    assert live.status_code == 200
    assert live.json() == {"status": "ok"}
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"
    assert ready.json()["storage"]
    assert ready.json()["api_version"] == api.API_VERSION


def test_readiness_returns_503_when_storage_probe_fails(monkeypatch):
    original = api.store

    class BrokenStore:
        async def ping(self):
            raise RuntimeError("database unavailable")

        async def close(self):
            return None

    monkeypatch.setattr(api, "store", BrokenStore())

    try:
        with TestClient(api.app) as client:
            response = client.get("/health/ready")

        assert response.status_code == 503
        assert response.json()["detail"] == "Storage backend is not ready"
        assert "database unavailable" not in response.text
    finally:
        monkeypatch.setattr(api, "store", original)
