from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

from pydantic import Field

from .audio_stream_manager import AudioStreamManager
from .http_metrics import (
    HttpMetricsSnapshot,
    HttpRequestMetrics,
)
from .models import StrictModel
from .provider_health import (
    ProviderHealthRegistry,
    ProviderHealthSnapshot,
)
from .review import ReviewDashboardSummary
from .review_service import ReviewService
from .slo import OperationalSloAssessment
from .storage import Store
from .voice_output_bridge import VoiceOutputBridge
from .websocket_metrics import (
    WebSocketMetrics,
    WebSocketMetricsSnapshot,
)


class OperationalSnapshot(StrictModel):
    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    sessions_total: int = Field(ge=0)
    session_statuses: dict[str, int] = Field(
        default_factory=dict
    )
    review: ReviewDashboardSummary
    voice_providers: list[ProviderHealthSnapshot]
    active_audio_streams: int = Field(ge=0)
    tracked_audio_streams: int = Field(ge=0)
    active_tts_streams: int = Field(ge=0)
    session_events_current: int = Field(ge=0)
    voice_events_current: int = Field(ge=0)
    tool_invocations_current: int = Field(ge=0)
    evidence_judge_runs_current: int = Field(ge=0)
    http: HttpMetricsSnapshot = Field(
        default_factory=HttpMetricsSnapshot
    )
    websockets: WebSocketMetricsSnapshot = Field(
        default_factory=WebSocketMetricsSnapshot
    )


class OperationsService:
    """Aggregate privacy-minimized runtime operations data."""

    def __init__(
        self,
        *,
        store: Store,
        review_service: ReviewService,
        provider_health: ProviderHealthRegistry,
        audio_stream_manager: AudioStreamManager,
        tts_bridge: VoiceOutputBridge,
        http_metrics: HttpRequestMetrics | None = None,
        websocket_metrics: WebSocketMetrics | None = None,
    ) -> None:
        self.store = store
        self.review_service = review_service
        self.provider_health = provider_health
        self.audio_stream_manager = audio_stream_manager
        self.tts_bridge = tts_bridge
        self.http_metrics = http_metrics
        self.websocket_metrics = websocket_metrics

    async def snapshot(self) -> OperationalSnapshot:
        sessions = await self.store.list_sessions()
        statuses = Counter(
            session.status.value
            for session in sessions
        )

        session_events = sum(
            len(session.events)
            for session in sessions
        )
        voice_events = sum(
            event.type.value.startswith("voice_")
            for session in sessions
            for event in session.events
        )
        tool_invocations = sum(
            len(session.tools)
            for session in sessions
        )
        judge_runs = sum(
            len(session.evidence_judge_runs)
            for session in sessions
        )

        return OperationalSnapshot(
            sessions_total=len(sessions),
            session_statuses=dict(
                sorted(statuses.items())
            ),
            review=await self.review_service.summary(),
            voice_providers=(
                await self.provider_health.snapshots()
            ),
            active_audio_streams=(
                self.audio_stream_manager
                .active_stream_count()
            ),
            tracked_audio_streams=(
                self.audio_stream_manager
                .tracked_stream_count()
            ),
            active_tts_streams=(
                await self.tts_bridge
                .active_stream_count()
            ),
            session_events_current=session_events,
            voice_events_current=voice_events,
            tool_invocations_current=tool_invocations,
            evidence_judge_runs_current=judge_runs,
            http=(
                await self.http_metrics.snapshot()
                if self.http_metrics is not None
                else HttpMetricsSnapshot()
            ),
            websockets=(
                await self.websocket_metrics.snapshot()
                if self.websocket_metrics is not None
                else WebSocketMetricsSnapshot()
            ),
        )


def _label(value: str) -> str:
    return (
        value
        .replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace('"', '\\"')
    )


def render_prometheus(
    snapshot: OperationalSnapshot,
    slo: OperationalSloAssessment | None = None,
) -> str:
    """Render a bounded-label Prometheus 0.0.4 text exposition."""

    lines = [
        "# HELP nora_sessions_current Current interview sessions retained by Nora.",
        "# TYPE nora_sessions_current gauge",
        f"nora_sessions_current {snapshot.sessions_total}",
    ]

    for status, count in snapshot.session_statuses.items():
        lines.append(
            'nora_sessions_by_status{status="'
            + _label(status)
            + f'"}} {count}'
        )

    review = snapshot.review
    gauges = {
        "nora_review_required_sessions": review.review_required,
        "nora_pending_appeals": review.pending_appeals,
        "nora_pending_integrity_signals": (
            review.pending_integrity_signals
        ),
        "nora_unresolved_tool_reviews": (
            review.unresolved_tools
        ),
        "nora_stale_evidence_runs": (
            review.stale_evidence_runs
        ),
        "nora_failed_evidence_runs": (
            review.failed_evidence_runs
        ),
        "nora_assigned_reviews": (
            review.assigned_reviews
        ),
        "nora_unassigned_review_required": (
            review.unassigned_review_required
        ),
        "nora_active_audio_streams": (
            snapshot.active_audio_streams
        ),
        "nora_tracked_audio_streams": (
            snapshot.tracked_audio_streams
        ),
        "nora_active_tts_streams": (
            snapshot.active_tts_streams
        ),
        "nora_session_events_current": (
            snapshot.session_events_current
        ),
        "nora_voice_events_current": (
            snapshot.voice_events_current
        ),
        "nora_tool_invocations_current": (
            snapshot.tool_invocations_current
        ),
        "nora_evidence_judge_runs_current": (
            snapshot.evidence_judge_runs_current
        ),
    }

    for name, value in gauges.items():
        lines.extend([
            f"# TYPE {name} gauge",
            f"{name} {value}",
        ])

    for provider in snapshot.voice_providers:
        labels = (
            f'key="{_label(provider.key)}",'
            f'provider_id="{_label(provider.provider_id)}",'
            f'state="{_label(provider.state.value)}"'
        )
        lines.append(
            f"nora_voice_provider_info{{{labels}}} 1"
        )
        lines.append(
            "nora_voice_provider_consecutive_failures"
            f'{{key="{_label(provider.key)}"}} '
            f"{provider.consecutive_failures}"
        )
        lines.append(
            "nora_voice_provider_total_failures"
            f'{{key="{_label(provider.key)}"}} '
            f"{provider.total_failures}"
        )
        lines.append(
            "nora_voice_provider_total_successes"
            f'{{key="{_label(provider.key)}"}} '
            f"{provider.total_successes}"
        )
        lines.append(
            "nora_voice_provider_circuit_open_seconds"
            f'{{key="{_label(provider.key)}"}} '
            f"{provider.circuit_open_seconds_remaining:g}"
        )

    http = snapshot.http
    lines.extend([
        "# HELP nora_http_requests_total HTTP requests by bounded route template and status class.",
        "# TYPE nora_http_requests_total counter",
        "# HELP nora_http_requests_in_flight HTTP requests currently being processed.",
        "# TYPE nora_http_requests_in_flight gauge",
        f"nora_http_requests_in_flight {http.in_flight}",
        "# HELP nora_http_request_duration_seconds HTTP request duration by bounded route template.",
        "# TYPE nora_http_request_duration_seconds histogram",
    ])

    for series in http.series:
        base_labels = (
            f'method="{_label(series.method)}",'
            f'route="{_label(series.route)}",'
            f'status_class="{_label(series.status_class)}"'
        )
        lines.append(
            f"nora_http_requests_total{{{base_labels}}} "
            f"{series.requests}"
        )
        for upper_bound, count in (
            series.duration_buckets.items()
        ):
            labels = (
                base_labels
                + f',le="{_label(upper_bound)}"'
            )
            lines.append(
                "nora_http_request_duration_seconds_bucket"
                f"{{{labels}}} {count}"
            )
        lines.append(
            "nora_http_request_duration_seconds_sum"
            f"{{{base_labels}}} "
            f"{series.duration_seconds_sum:g}"
        )
        lines.append(
            "nora_http_request_duration_seconds_count"
            f"{{{base_labels}}} {series.requests}"
        )

    ws = snapshot.websockets
    lines.extend([
        "# HELP nora_websocket_connections_active Active accepted WebSocket connections by bounded channel.",
        "# TYPE nora_websocket_connections_active gauge",
        "# HELP nora_websocket_connections_opened_total Accepted WebSocket connections by bounded channel.",
        "# TYPE nora_websocket_connections_opened_total counter",
        "# HELP nora_websocket_connections_closed_total Closed accepted WebSocket connections by bounded channel.",
        "# TYPE nora_websocket_connections_closed_total counter",
        "# HELP nora_websocket_errors_total WebSocket application failures by bounded channel.",
        "# TYPE nora_websocket_errors_total counter",
        "# HELP nora_websocket_connection_duration_seconds_sum Aggregate accepted WebSocket connection duration.",
        "# TYPE nora_websocket_connection_duration_seconds_sum counter",
    ])
    for channel in ws.channels:
        label = (
            f'channel="{_label(channel.channel)}"'
        )
        lines.append(
            f"nora_websocket_connections_active{{{label}}} "
            f"{channel.active}"
        )
        lines.append(
            f"nora_websocket_connections_opened_total{{{label}}} "
            f"{channel.opened_total}"
        )
        lines.append(
            f"nora_websocket_connections_closed_total{{{label}}} "
            f"{channel.closed_total}"
        )
        lines.append(
            f"nora_websocket_errors_total{{{label}}} "
            f"{channel.errors_total}"
        )
        lines.append(
            "nora_websocket_connection_duration_seconds_sum"
            f"{{{label}}} {channel.duration_seconds_sum:g}"
        )

    if slo is not None:
        lines.extend([
            "# HELP nora_operational_slo_status Current operational SLO state.",
            "# TYPE nora_operational_slo_status gauge",
        ])
        for status in (
            "healthy",
            "degraded",
            "breached",
        ):
            lines.append(
                "nora_operational_slo_status"
                f'{{status="{status}"}} '
                f"{1 if slo.status.value == status else 0}"
            )

        lines.extend([
            "# HELP nora_operational_slo_signal Active bounded operational SLO signals.",
            "# TYPE nora_operational_slo_signal gauge",
        ])
        for signal in slo.signals:
            labels = (
                f'code="{_label(signal.code)}",'
                f'severity="{_label(signal.severity.value)}"'
            )
            lines.append(
                f"nora_operational_slo_signal{{{labels}}} 1"
            )

        lines.extend([
            "# TYPE nora_http_5xx_ratio gauge",
            f"nora_http_5xx_ratio {slo.http_5xx_ratio:g}",
        ])

    return "\n".join(lines) + "\n"
