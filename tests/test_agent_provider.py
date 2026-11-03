"""Picks the agent provider and the model with the installed SDKs faked, so it runs on a bare install."""

from importlib.machinery import ModuleSpec
from importlib.metadata import version

import pytest

from reality_check.intelligence import interface
from reality_check.intelligence.interface import AgentRun, resolve_agent_provider, select_intelligence
from reality_check.intelligence.schemas import AgentRequest, Steering
from reality_check.schemas import AGENT_PROVIDERS, DEFAULT_INTELLIGENCE_MODELS, AgentProvider, RealityCheckError

REPOSITORY = f"git+https://github.com/microsoft/amplifier-smart-tool-reality-check@v{version('reality-check')}"


class FakeIntelligence:
    def __init__(self) -> None:
        self.implementation = "fake"
        self.steering: Steering = "mid-turn"

    def preflight(self) -> None:
        pass

    async def start(self, request: AgentRequest) -> AgentRun:
        raise NotImplementedError


def only_installed(monkeypatch: pytest.MonkeyPatch, *agent_providers: AgentProvider) -> None:
    modules = {interface.SDK_MODULES[agent_provider] for agent_provider in agent_providers}

    def find_spec(name: str) -> ModuleSpec | None:
        return ModuleSpec(name, None) if name in modules else None

    monkeypatch.setattr(interface, "find_spec", find_spec)


@pytest.mark.parametrize("first", range(len(AGENT_PROVIDERS)))
def test_without_a_name_the_first_installed_in_order_is_picked(monkeypatch: pytest.MonkeyPatch, first: int) -> None:
    only_installed(monkeypatch, *AGENT_PROVIDERS[first:])

    assert resolve_agent_provider() == AGENT_PROVIDERS[first]


@pytest.mark.parametrize("named", AGENT_PROVIDERS)
def test_a_named_agent_provider_wins_over_the_order(monkeypatch: pytest.MonkeyPatch, named: AgentProvider) -> None:
    only_installed(monkeypatch, *AGENT_PROVIDERS)

    assert resolve_agent_provider(named) == named


@pytest.mark.parametrize(
    ("named", "code", "extra"),
    [
        (None, "no-agent-provider", "all"),
        ("copilot", "agent-provider-not-installed", "copilot"),
        ("amplifier-agent", "agent-provider-not-installed", "amplifier-agent"),
        ("codex", "agent-provider-not-installed", "codex"),
        ("claude", "agent-provider-not-installed", "claude"),
    ],
)
def test_a_missing_agent_provider_names_the_install_command(
    monkeypatch: pytest.MonkeyPatch, named: AgentProvider | None, code: str, extra: str
) -> None:
    only_installed(monkeypatch)

    with pytest.raises(RealityCheckError) as failure:
        resolve_agent_provider(named)

    assert failure.value.code == code
    assert f'uv tool install "reality-check[{extra}] @ {REPOSITORY}"' in failure.value.remedy


def test_an_injected_intelligence_wins_and_needs_no_agent_provider_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    only_installed(monkeypatch)
    fake = FakeIntelligence()

    assert select_intelligence(fake, None, None, DEFAULT_INTELLIGENCE_MODELS) == (
        fake,
        DEFAULT_INTELLIGENCE_MODELS[AGENT_PROVIDERS[0]],
    )
    assert select_intelligence(fake, AGENT_PROVIDERS[-1], None, DEFAULT_INTELLIGENCE_MODELS) == (
        fake,
        DEFAULT_INTELLIGENCE_MODELS[AGENT_PROVIDERS[-1]],
    )
    assert select_intelligence(fake, None, "some-model", DEFAULT_INTELLIGENCE_MODELS) == (fake, "some-model")
