from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

import nora_interviewer.api as api
from nora_interviewer.authn import DevHeaderPrincipalResolver
from nora_interviewer.models import InterviewSession
from nora_interviewer.retention import RetentionManager
from nora_interviewer.storage import InMemoryStore


NOW = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)

SERVICE = {
    "X-Nora-Principal": "internal-service",
    "X-Nora-Role": "service",
}
RECRUITER = {
    "X-Nora-Principal": "recruiter",
    "X-Nora-Role": "recruiter",
}


def test_retention_endpoint_is_service_only_and_dry_run_first(monkeypatch):
    store = InMemoryStore()
    session = InterviewSession(
        id="expired-session",
        job_id="job",
        candidate_ref="candidate",
        locale="en",
        created_at=NOW - timedelta(days=120),
        completed_at=NOW - timedelta(days=100),
    )

    import asyncio
    asyncio.run(store.put_session(session))

    monkeypatch.setattr(
        api,
        "principal_resolver",
        DevHeaderPrincipalResolver(),
    )
    monkeypatch.setattr(
        api,
        "retention",
        RetentionManager(
            store,
            now=lambda: NOW,
        ),
    )

    client = TestClient(api.app)

    denied = client.post(
        "/v1/system/retention/run",
        headers=RECRUITER,
        json={
            "max_age_days": 90,
            "dry_run": True,
        },
    )
    assert denied.status_code == 403

    preview = client.post(
        "/v1/system/retention/run",
        headers=SERVICE,
        json={
            "max_age_days": 90,
        },
    )
    assert preview.status_code == 200
    payload = preview.json()
    assert payload["dry_run"] is True
    assert payload["deleted_session_ids"] == []
    assert payload["matched"][0]["session_id"] == "expired-session"

    execute = client.post(
        "/v1/system/retention/run",
        headers=SERVICE,
        json={
            "max_age_days": 90,
            "dry_run": False,
        },
    )
    assert execute.status_code == 200
    assert execute.json()["deleted_session_ids"] == [
        "expired-session"
    ]
