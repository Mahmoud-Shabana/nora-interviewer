from __future__ import annotations

import math
from collections import Counter

from .evidence_judge import (
    EvidenceJudge,
    EvidenceJudgeError,
    GroundedEvidenceGate,
    JudgeFinding,
    JudgeResponse,
)
from .models import EvidenceState, JobSpec, Turn


class EvidenceJudgeEnsemble:
    """Combine independent semantic judges without hiding disagreement."""

    def __init__(
        self,
        judges: list[EvidenceJudge],
        *,
        agreement_threshold: float = 0.67,
    ) -> None:
        if len(judges) < 2:
            raise ValueError(
                "EvidenceJudgeEnsemble requires at least two judges"
            )
        ids = [judge.judge_id for judge in judges]
        if len(ids) != len(set(ids)):
            raise ValueError(
                "EvidenceJudgeEnsemble judge ids must be unique"
            )
        if not 0.5 < agreement_threshold <= 1.0:
            raise ValueError(
                "agreement_threshold must be in (0.5, 1.0]"
            )

        self.judges = list(judges)
        self.agreement_threshold = agreement_threshold

    @property
    def judge_id(self) -> str:
        return "ensemble:" + "+".join(
            judge.judge_id for judge in self.judges
        )

    async def evaluate(
        self,
        *,
        question: Turn,
        answer: Turn,
        job: JobSpec,
        competency_ids: list[str],
    ) -> JudgeResponse:
        findings_by_judge: dict[
            str,
            dict[str, JudgeFinding],
        ] = {}
        failures: list[dict[str, str]] = []

        for judge in self.judges:
            try:
                response = await judge.evaluate(
                    question=question,
                    answer=answer,
                    job=job,
                    competency_ids=competency_ids,
                )
                GroundedEvidenceGate.validate(
                    answer=answer,
                    response=response,
                    judge_id=judge.judge_id,
                )

                mapped: dict[str, JudgeFinding] = {}
                for finding in response.findings:
                    if finding.competency_id in mapped:
                        raise EvidenceJudgeError(
                            "judge returned duplicate findings "
                            f"for competency {finding.competency_id!r}"
                        )
                    mapped[finding.competency_id] = finding
                findings_by_judge[judge.judge_id] = mapped
            except Exception as exc:
                failures.append({
                    "judge_id": judge.judge_id,
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:1000],
                })
                findings_by_judge[judge.judge_id] = {}

        required_votes = math.ceil(
            self.agreement_threshold
            * len(self.judges)
        )
        consensus_findings: list[JudgeFinding] = []
        competency_audit: list[dict] = []

        for competency_id in competency_ids:
            votes: list[dict[str, str]] = []
            state_findings: dict[
                EvidenceState,
                list[JudgeFinding],
            ] = {}

            for judge in self.judges:
                finding = findings_by_judge[
                    judge.judge_id
                ].get(competency_id)
                if finding is None:
                    votes.append({
                        "judge_id": judge.judge_id,
                        "state": "no_finding",
                    })
                    continue

                votes.append({
                    "judge_id": judge.judge_id,
                    "state": finding.state.value,
                })
                state_findings.setdefault(
                    finding.state,
                    [],
                ).append(finding)

            counts = Counter(
                vote["state"]
                for vote in votes
                if vote["state"] != "no_finding"
            )
            state_by_value = {
                state.value: state
                for state in EvidenceState
            }

            consensus_state: EvidenceState | None = None
            agreement_count = 0
            if counts:
                state_value, agreement_count = max(
                    counts.items(),
                    key=lambda item: (
                        item[1],
                        item[0],
                    ),
                )
                consensus_state = state_by_value[
                    state_value
                ]

            agreement_ratio = (
                agreement_count / len(self.judges)
            )
            threshold_met = (
                consensus_state is not None
                and agreement_count >= required_votes
            )

            if threshold_met:
                agreeing = state_findings[
                    consensus_state
                ]
                confidence = sum(
                    finding.confidence
                    for finding in agreeing
                ) / len(agreeing)

                quote: str | None = None
                rationale_source = max(
                    agreeing,
                    key=lambda finding: finding.confidence,
                )
                if consensus_state in {
                    EvidenceState.DEMONSTRATED,
                    EvidenceState.CONTRADICTED,
                }:
                    quote = rationale_source.quote

                consensus_findings.append(
                    JudgeFinding(
                        competency_id=competency_id,
                        state=consensus_state,
                        confidence=round(
                            confidence,
                            4,
                        ),
                        quote=quote,
                        rationale=(
                            f"Consensus from {agreement_count}/"
                            f"{len(self.judges)} semantic judges. "
                            f"{rationale_source.rationale}"
                        ),
                    )
                )
            else:
                consensus_findings.append(
                    JudgeFinding(
                        competency_id=competency_id,
                        state=EvidenceState.INSUFFICIENT,
                        confidence=round(
                            agreement_ratio,
                            4,
                        ),
                        quote=None,
                        rationale=(
                            "No semantic evidence state reached "
                            f"the ensemble threshold of "
                            f"{required_votes}/{len(self.judges)} judges."
                        ),
                    )
                )

            competency_audit.append({
                "competency_id": competency_id,
                "votes": votes,
                "agreement_count": agreement_count,
                "agreement_ratio": round(
                    agreement_ratio,
                    4,
                ),
                "required_votes": required_votes,
                "threshold_met": threshold_met,
                "consensus_state": (
                    consensus_state.value
                    if threshold_met
                    and consensus_state is not None
                    else None
                ),
            })

        return JudgeResponse(
            findings=consensus_findings,
            audit={
                "kind": "evidence_judge_ensemble",
                "judge_ids": [
                    judge.judge_id
                    for judge in self.judges
                ],
                "agreement_threshold": (
                    self.agreement_threshold
                ),
                "required_votes": required_votes,
                "failures": failures,
                "competencies": competency_audit,
            },
        )
