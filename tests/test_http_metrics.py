import asyncio

from nora_interviewer.http_metrics import HttpRequestMetrics
from nora_interviewer.operations import (
    OperationalSnapshot,
    render_prometheus,
)
from nora_interviewer.review import ReviewDashboardSummary


class FakeClock:
    def __init__(self) -> None:
        self.value = 10.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def run(coro):
    return asyncio.run(coro)


def test_http_metrics_use_route_templates_and_status_classes():
    async def scenario():
        clock = FakeClock()
        metrics = HttpRequestMetrics(
            latency_buckets_seconds=(
                0.1,
                0.5,
                1.0,
            ),
            clock=clock,
        )

        await metrics.request_started()
        started = metrics.start_timer()
        clock.advance(0.4)
        await metrics.request_finished(
            method="get",
            route="/v1/sessions/{session_id}",
            status_code=200,
            started_at=started,
        )

        await metrics.request_started()
        started = metrics.start_timer()
        clock.advance(0.8)
        await metrics.request_finished(
            method="GET",
            route="/v1/sessions/{session_id}",
            status_code=404,
            started_at=started,
        )

        snapshot = await metrics.snapshot()
        assert snapshot.requests_total == 2
        assert snapshot.in_flight == 0
        assert len(snapshot.series) == 2

        success = next(
            item
            for item in snapshot.series
            if item.status_class == "2xx"
        )
        assert success.method == "GET"
        assert success.route == "/v1/sessions/{session_id}"
        assert success.requests == 1
        assert success.duration_seconds_sum == 0.4
        assert success.duration_buckets == {
            "0.1": 0,
            "0.5": 1,
            "1": 1,
            "+Inf": 1,
        }

        missing = next(
            item
            for item in snapshot.series
            if item.status_class == "4xx"
        )
        assert missing.duration_buckets["0.5"] == 0
        assert missing.duration_buckets["1"] == 1

    run(scenario())


def test_prometheus_http_labels_never_need_concrete_resource_ids():
    async def scenario():
        metrics = HttpRequestMetrics()
        await metrics.request_started()
        started = metrics.start_timer()
        await metrics.request_finished(
            method="POST",
            route="/v1/sessions/{session_id}/responses",
            status_code=200,
            started_at=started,
        )
        http = await metrics.snapshot()

        snapshot = OperationalSnapshot(
            sessions_total=0,
            session_statuses={},
            review=ReviewDashboardSummary(
                total_sessions=0,
                review_required=0,
                pending_appeals=0,
                pending_integrity_signals=0,
                unresolved_tools=0,
                stale_evidence_runs=0,
                failed_evidence_runs=0,
                completed_sessions=0,
            ),
            voice_providers=[],
            active_audio_streams=0,
            tracked_audio_streams=0,
            active_tts_streams=0,
            session_events_current=0,
            voice_events_current=0,
            tool_invocations_current=0,
            evidence_judge_runs_current=0,
            http=http,
        )
        text = render_prometheus(snapshot)

        assert (
            'route="/v1/sessions/{session_id}/responses"'
            in text
        )
        assert "candidate-123" not in text
        assert "session-abc" not in text
        assert (
            "nora_http_request_duration_seconds_bucket"
            in text
        )

    run(scenario())


def test_aborted_requests_are_counted_as_server_errors():
    async def scenario():
        metrics = HttpRequestMetrics()
        await metrics.request_started()
        started = metrics.start_timer()
        await metrics.request_aborted(
            method="POST",
            route="<exception>",
            started_at=started,
        )

        snapshot = await metrics.snapshot()
        assert snapshot.requests_total == 1
        assert snapshot.in_flight == 0
        assert snapshot.series[0].status_class == "5xx"
        assert snapshot.series[0].route == "<exception>"

    run(scenario())
