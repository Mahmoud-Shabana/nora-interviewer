import os

from nora_interviewer.config import build_evidence_judge
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
