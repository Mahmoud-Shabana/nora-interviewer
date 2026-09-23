import pytest

from nora_interviewer.config import (
    build_rubric_drafter,
)
from nora_interviewer.rubric_drafting import (
    DisabledRubricDrafter,
    LLMRubricDrafter,
)


def clear_env(monkeypatch):
    for key in (
        "NORA_RUBRIC_DRAFTER_MODE",
        "NORA_RUBRIC_DRAFTER_BASE_URL",
        "NORA_RUBRIC_DRAFTER_MODEL",
        "NORA_RUBRIC_DRAFTER_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)


def test_rubric_drafter_is_disabled_by_default(monkeypatch):
    clear_env(monkeypatch)
    assert isinstance(
        build_rubric_drafter(),
        DisabledRubricDrafter,
    )


def test_openai_compatible_rubric_drafter_config(monkeypatch):
    clear_env(monkeypatch)
    monkeypatch.setenv(
        "NORA_RUBRIC_DRAFTER_MODE",
        "openai-compatible",
    )
    monkeypatch.setenv(
        "NORA_RUBRIC_DRAFTER_BASE_URL",
        "https://provider.example/v1",
    )
    monkeypatch.setenv(
        "NORA_RUBRIC_DRAFTER_MODEL",
        "rubric-model",
    )
    monkeypatch.setenv(
        "NORA_RUBRIC_DRAFTER_API_KEY",
        "secret",
    )

    drafter = build_rubric_drafter()

    assert isinstance(
        drafter,
        LLMRubricDrafter,
    )
    assert (
        drafter.drafter_id
        == "openai-compatible:rubric-model"
    )
    assert (
        drafter.provider.base_url
        == "https://provider.example/v1"
    )
    assert drafter.provider.model == "rubric-model"


def test_rubric_drafter_requires_provider_coordinates(monkeypatch):
    clear_env(monkeypatch)
    monkeypatch.setenv(
        "NORA_RUBRIC_DRAFTER_MODE",
        "openai-compatible",
    )

    with pytest.raises(
        RuntimeError,
        match="BASE_URL",
    ):
        build_rubric_drafter()
