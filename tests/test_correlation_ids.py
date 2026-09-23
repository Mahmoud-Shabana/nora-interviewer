from fastapi.testclient import TestClient

import nora_interviewer.api as api
from nora_interviewer.audit import append_event
from nora_interviewer.models import (
    EventType,
    InterviewSession,
)
from nora_interviewer.trace_context import (
    reset_correlation_id,
    resolve_correlation_id,
    set_correlation_id,
)


def test_http_request_id_is_propagated_and_invalid_values_are_replaced():
    with TestClient(api.app) as client:
        supplied = client.get(
            "/health",
            headers={
                "X-Request-ID": "client-trace-1234",
            },
        )
        assert supplied.status_code == 200
        assert (
            supplied.headers["x-request-id"]
            == "client-trace-1234"
        )

        generated = client.get(
            "/health",
            headers={
                "X-Request-ID": "not valid because spaces",
            },
        )
        assert generated.status_code == 200
        request_id = generated.headers["x-request-id"]
        assert request_id.startswith("req_")
        assert request_id != "not valid because spaces"


def test_audit_event_inherits_active_correlation_id_without_mutating_input():
    session = InterviewSession(
        id="session",
        job_id="job",
        candidate_ref="candidate",
        locale="en",
    )
    payload = {"purpose": "test"}

    token = set_correlation_id(
        "client-trace-5678"
    )
    try:
        event = append_event(
            session,
            EventType.SESSION_CREATED,
            payload=payload,
        )
    finally:
        reset_correlation_id(token)

    assert payload == {"purpose": "test"}
    assert event.payload["purpose"] == "test"
    assert event.payload["_trace"] == {
        "correlation_id": "client-trace-5678",
    }


def test_resolver_bounds_untrusted_ids():
    assert (
        resolve_correlation_id(
            "safe-trace-0001",
        )
        == "safe-trace-0001"
    )

    generated = resolve_correlation_id(
        "x" * 200,
        prefix="ws",
    )
    assert generated.startswith("ws_")
    assert len(generated) < 64
