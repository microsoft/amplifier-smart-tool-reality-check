"""The models a check runs on, listed and checked with no agent provider signed in."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reality_check import lib
from reality_check.capabilities.check_software.intelligence_models import require_allowed
from reality_check.cli import app
from reality_check.schemas import ALL_EFFORTS, INTELLIGENCE_MODELS, AgentProvider, RealityCheckError

runner = CliRunner()


def test_the_list_is_the_allowlist_with_its_efforts_and_the_default() -> None:
    models = lib.list_intelligence_models()

    assert models.models == list(INTELLIGENCE_MODELS)
    sol = next(model for model in models.models if model.id == "gpt-6.1-sol")
    auto = next(model for model in models.models if model.id == "auto")
    assert (sol.reasoning_efforts, sol.vision) == (ALL_EFFORTS, True)
    assert "none" not in sol.reasoning_efforts
    assert (auto.reasoning_efforts, auto.vision) == ([], False)
    assert models.default.model_dump() == {
        "agent_provider": "copilot",
        "model": "gpt-6.1-sol",
        "reasoning_effort": "medium",
    }


@pytest.mark.parametrize(
    ("model", "effort", "images", "expected"),
    [
        ("gpt-6.1-sol", None, [], "medium"),
        ("claude-opus-5.5", "high", [Path("shot.png")], "high"),
        ("auto", None, [], None),
        ("auto", "medium", [], "bad-reasoning-effort"),
        ("gpt-6.1-sol", "none", [], "bad-reasoning-effort"),
        ("auto", None, [Path("shot.png")], "model-without-vision"),
        ("no-such-model-xyz", None, [], "model-not-allowed"),
    ],
)
def test_require_allowed_returns_the_effort_to_send_or_names_the_problem(
    model: str, effort: str | None, images: list[Path], expected: str | None
) -> None:
    if expected is None or expected in ALL_EFFORTS:
        assert require_allowed("copilot", model, effort, images) == expected
        return
    with pytest.raises(RealityCheckError) as failure:
        require_allowed("copilot", model, effort, images)
    assert failure.value.code == expected


def test_the_cli_prints_the_list_as_json() -> None:
    result = runner.invoke(app, ["list-intelligence-models"])

    assert result.exit_code == 0
    assert json.loads(result.stdout) == lib.list_intelligence_models().model_dump(mode="json")


@pytest.mark.parametrize(
    ("agent_provider", "model", "expected"),
    [
        ("amplifier-agent", "openai/gpt-6.1-sol", "medium"),
        ("amplifier-agent", "gpt-6.1-sol", "model-not-allowed"),
        ("codex", "gpt-6.1-sol", "medium"),
        ("claude", "claude-sonnet-5-5", "medium"),
        ("claude", "claude-sonnet-5.5", "model-not-allowed"),
    ],
)
def test_every_agent_provider_runs_only_its_listed_models(
    agent_provider: AgentProvider, model: str, expected: str
) -> None:
    if expected in ALL_EFFORTS:
        assert require_allowed(agent_provider, model, None, []) == expected
        return
    with pytest.raises(RealityCheckError) as failure:
        require_allowed(agent_provider, model, None, [])
    assert failure.value.code == expected
