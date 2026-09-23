from __future__ import annotations

from enum import Enum

from pydantic import Field, model_validator

from .models import StrictModel
from .operations import OperationalSnapshot
from .provider_health import ProviderHealthState


class SloStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    BREACHED = "breached"


class SloSignalSeverity(str, Enum):
    WARNING = "warning"
    CRITICAL = "critical"


class OperationalSloPolicy(StrictModel):
    max_http_5xx_ratio: float = Field(
        default=0.05,
        ge=0.0,
        le=1.0,
    )
    min_http_requests_for_error_ratio: int = Field(
        default=20,
        ge=1,
    )
    max_unassigned_review_required: int = Field(
        default=20,
        ge=0,
    )
    max_failed_evidence_runs: int = Field(
        default=5,
        ge=0,
    )

    @model_validator(mode="after")
    def validate_policy(
        self,
    ) -> "OperationalSloPolicy":
        return self


class OperationalSloSignal(StrictModel):
    code: str
    severity: SloSignalSeverity
    summary: str
    value: float
    threshold: float


class OperationalSloAssessment(StrictModel):
    status: SloStatus
    http_requests: int = Field(ge=0)
    http_5xx_requests: int = Field(ge=0)
    http_5xx_ratio: float = Field(ge=0.0, le=1.0)
    signals: list[OperationalSloSignal] = Field(
        default_factory=list
    )


def assess_operational_slo(
    snapshot: OperationalSnapshot,
    policy: OperationalSloPolicy | None = None,
) -> OperationalSloAssessment:
    policy = policy or OperationalSloPolicy()
    signals: list[OperationalSloSignal] = []

    http_requests = sum(
        series.requests
        for series in snapshot.http.series
    )
    http_5xx = sum(
        series.requests
        for series in snapshot.http.series
        if series.status_class == "5xx"
    )
    http_5xx_ratio = (
        http_5xx / http_requests
        if http_requests
        else 0.0
    )

    if (
        http_requests
        >= policy.min_http_requests_for_error_ratio
        and http_5xx_ratio
        > policy.max_http_5xx_ratio
    ):
        signals.append(
            OperationalSloSignal(
                code="http_5xx_ratio",
                severity=SloSignalSeverity.CRITICAL,
                summary=(
                    "HTTP 5xx ratio is above the configured "
                    "operational threshold."
                ),
                value=round(
                    http_5xx_ratio,
                    6,
                ),
                threshold=(
                    policy.max_http_5xx_ratio
                ),
            )
        )

    for provider in snapshot.voice_providers:
        if provider.state is ProviderHealthState.OPEN:
            signals.append(
                OperationalSloSignal(
                    code=(
                        "voice_provider_circuit_open:"
                        + provider.key
                    ),
                    severity=SloSignalSeverity.CRITICAL,
                    summary=(
                        "Voice provider circuit is open "
                        f"for {provider.key}."
                    ),
                    value=(
                        provider
                        .circuit_open_seconds_remaining
                    ),
                    threshold=0.0,
                )
            )
        elif provider.state is ProviderHealthState.DEGRADED:
            signals.append(
                OperationalSloSignal(
                    code=(
                        "voice_provider_degraded:"
                        + provider.key
                    ),
                    severity=SloSignalSeverity.WARNING,
                    summary=(
                        "Voice provider has consecutive "
                        f"failures for {provider.key}."
                    ),
                    value=float(
                        provider.consecutive_failures
                    ),
                    threshold=0.0,
                )
            )

    if (
        snapshot.review.unassigned_review_required
        > policy.max_unassigned_review_required
    ):
        signals.append(
            OperationalSloSignal(
                code="unassigned_review_backlog",
                severity=SloSignalSeverity.WARNING,
                summary=(
                    "Unassigned human-review backlog is "
                    "above the configured threshold."
                ),
                value=float(
                    snapshot.review
                    .unassigned_review_required
                ),
                threshold=float(
                    policy.max_unassigned_review_required
                ),
            )
        )

    if (
        snapshot.review.failed_evidence_runs
        > policy.max_failed_evidence_runs
    ):
        signals.append(
            OperationalSloSignal(
                code="failed_evidence_runs",
                severity=SloSignalSeverity.WARNING,
                summary=(
                    "Failed semantic evidence runs are "
                    "above the configured threshold."
                ),
                value=float(
                    snapshot.review.failed_evidence_runs
                ),
                threshold=float(
                    policy.max_failed_evidence_runs
                ),
            )
        )

    if any(
        signal.severity
        is SloSignalSeverity.CRITICAL
        for signal in signals
    ):
        status = SloStatus.BREACHED
    elif signals:
        status = SloStatus.DEGRADED
    else:
        status = SloStatus.HEALTHY

    return OperationalSloAssessment(
        status=status,
        http_requests=http_requests,
        http_5xx_requests=http_5xx,
        http_5xx_ratio=round(
            http_5xx_ratio,
            6,
        ),
        signals=signals,
    )
