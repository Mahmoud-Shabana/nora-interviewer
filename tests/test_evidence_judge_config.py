import os

from nora_interviewer.config import build_evidence_judge
from nora_interviewer.evidence_ensemble import EvidenceJudgeEnsemble
from nora_interviewer.evidence_judge import (
    DisabledEvidenceJudge,
    LLMEvidenceJudge,
)


def test_evidence_judge_is_disabled_by_default(monkeypatch):
    for name in [
        "NORA_EVIDENCE_JUDGE_MODE",
        "NORA_EVIDENCE_JUDGE_BASE_URL",
        "NORA_EVIDENCE_JUDGE_MODEL",
        "NORA_EVIDENCE_JUDGE_API_KEY",
    ]:
        monkeypatch.delenv(name, raising=False)

    judge = build_evidence_judge()
    assert isinstance(judge, DisabledEvidenceJudge)
    assert judge.judge_id == "disabled"


def test_evidence_judge_requires_separate_provider_settings(monkeypatch):
    monkeypatch.setenv(
        "NORA_EVIDENCE_JUDGE_MODE",
        "openai-compatible",
    )
    monkeypatch.delenv(
        "NORA_EVIDENCE_JUDGE_BASE_URL",
        raising=False,
    )
    monkeypatch.delenv(
        "NORA_EVIDENCE_JUDGE_MODEL",
        raising=False,
    )

    try:
        build_evidence_judge()
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "NORA_EVIDENCE_JUDGE_BASE_URL" in str(exc)


def test_evidence_judge_can_use_independent_model(monkeypatch):
    monkeypatch.setenv(
        "NORA_EVIDENCE_JUDGE_MODE",
        "openai-compatible",
    )
    monkeypatch.setenv(
        "NORA_EVIDENCE_JUDGE_BASE_URL",
        "https://judge.example/v1",
    )
    monkeypatch.setenv(
        "NORA_EVIDENCE_JUDGE_MODEL",
        "judge-model-v1",
    )
    monkeypatch.setenv(
        "NORA_EVIDENCE_JUDGE_API_KEY",
        "secret",
    )

    judge = build_evidence_judge()
    assert isinstance(judge, LLMEvidenceJudge)
    assert judge.judge_id == "openai-compatible:judge-model-v1"


def test_evidence_judge_ensemble_builds_multiple_models(monkeypatch):
    monkeypatch.setenv(
        "NORA_EVIDENCE_JUDGE_MODE",
        "ensemble",
    )
    monkeypatch.setenv(
        "NORA_EVIDENCE_JUDGE_BASE_URL",
        "https://judge.example/v1",
    )
    monkeypatch.setenv(
        "NORA_EVIDENCE_JUDGE_MODELS",
        "judge-a, judge-b,judge-c",
    )
    monkeypatch.setenv(
        "NORA_EVIDENCE_JUDGE_API_KEY",
        "secret",
    )
    monkeypatch.setenv(
        "NORA_EVIDENCE_JUDGE_AGREEMENT_THRESHOLD",
        "0.67",
    )

    judge = build_evidence_judge()

    assert isinstance(judge, EvidenceJudgeEnsemble)
    assert [item.judge_id for item in judge.judges] == [
        "openai-compatible:judge-a",
        "openai-compatible:judge-b",
        "openai-compatible:judge-c",
    ]
    assert judge.agreement_threshold == 0.67


def test_evidence_judge_ensemble_requires_two_unique_models(monkeypatch):
    monkeypatch.setenv(
        "NORA_EVIDENCE_JUDGE_MODE",
        "ensemble",
    )
    monkeypatch.setenv(
        "NORA_EVIDENCE_JUDGE_BASE_URL",
        "https://judge.example/v1",
    )
    monkeypatch.setenv(
        "NORA_EVIDENCE_JUDGE_MODELS",
        "judge-a,judge-a",
    )

    try:
        build_evidence_judge()
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "unique model ids" in str(exc)
