from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

from pydantic import Field

from .audio_stream_manager import AudioStreamManager
from .models import StrictModel
from .provider_health import (
    ProviderHealthRegistry,
    ProviderHealthSnapshot,
)
from .review import ReviewDashboardSummary
from .review_service import ReviewService
from .storage import Store
from .voice_output_bridge import VoiceOutputBridge


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
    ) -> None:
        self.store = store
        self.review_service = review_service
        self.provider_health = provider_health
        self.audio_stream_manager = audio_stream_manager
        self.tts_bridge = tts_bridge

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

    return "\n".join(lines) + "\n"
