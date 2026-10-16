"""The contract every model-backed capability runs through, so the implementation is swappable."""

from collections.abc import AsyncIterator
from importlib.util import find_spec
from typing import Protocol

from reality_check.core.skill import DISTRIBUTION, repository_url
from reality_check.intelligence.schemas import AgentEvent, AgentRequest, AgentResult, Steering
from reality_check.schemas import AGENT_PROVIDERS, AgentProvider, RealityCheckError

# The import each agent provider's SDK answers to; its extra is named after the agent provider.
SDK_MODULES: dict[AgentProvider, str] = {
    "copilot": "copilot",
    "amplifier-agent": "amplifier_agent",
    "codex": "openai_codex",
    "claude": "claude_agent_sdk",
}


class AgentRun(Protocol):
    """One running agent: what it does as it happens, a way to talk to it, and how it ended."""

    @property
    def session_id(self) -> str | None:
        """The session a later run resumes, once the agent provider has made it; None before."""
        ...

    def events(self) -> AsyncIterator[AgentEvent]:
        """Every event from the start, then live ones until the run ends with `terminal`."""
        ...

    async def steer(self, message: str) -> None:
        """Send a message to the agent while it works; the implementation's `steering` says how it lands."""
        ...

    async def cancel(self) -> None:
        """End the run and drain it, so its session can still be resumed."""
        ...

    async def result(self) -> AgentResult:
        """Wait for the run to end.

        When the request carries an output schema, the result either holds a conforming
        `output` or an `error`; retry mechanics are the implementation's own business.
        """
        ...


class Intelligence(Protocol):
    """Runs agents against models; the library depends on this contract, never on an SDK."""

    implementation: str
    steering: Steering

    def preflight(self) -> None:
        """Raise RealityCheckError naming exactly what to configure when the implementation cannot run."""
        ...

    async def start(self, request: AgentRequest) -> AgentRun:
        """Start one agent and return once it runs; failures after that end the run with `AgentResult.error`."""
        ...


def installed(agent_provider: AgentProvider) -> bool:
    """Whether the agent provider's SDK is importable, without importing it."""
    return find_spec(SDK_MODULES[agent_provider]) is not None


def resolve_agent_provider(agent_provider: AgentProvider | None = None) -> AgentProvider:
    """The named agent provider when it is installed, else the first installed one in `AGENT_PROVIDERS` order."""
    if agent_provider is not None:
        if not installed(agent_provider):
            raise RealityCheckError(
                code="agent-provider-not-installed",
                message=f"The {agent_provider} agent provider is not installed.",
                remedy=f"Install reality-check with it: `uv tool install {_install_source(agent_provider)}`, or "
                f"`uv add {_install_source(agent_provider)}` in a project that uses the library.",
            )
        return agent_provider
    for candidate in AGENT_PROVIDERS:
        if installed(candidate):
            return candidate
    raise RealityCheckError(
        code="no-agent-provider",
        message="Model-backed capabilities need an agent provider and none is installed.",
        remedy=f"Install reality-check with every one: `uv tool install {_install_source('all')}`, or put "
        + " or ".join(f"[{candidate}]" for candidate in AGENT_PROVIDERS)
        + " in place of [all] for just one. Use `uv add` instead of `uv tool install` in a project that uses the "
        "library.",
    )


def resolve_intelligence(agent_provider: AgentProvider | None = None, model: str | None = None) -> Intelligence:
    """The shipped implementation for the agent provider `resolve_agent_provider` picks.

    `model` is what its preflight checks, when the implementation can check one before a run.
    """
    match resolve_agent_provider(agent_provider):
        case "copilot":
            from reality_check.intelligence.copilot import CopilotIntelligence

            return CopilotIntelligence()
        case "amplifier-agent":
            from reality_check.intelligence.amplifier_agent import AmplifierAgentIntelligence

            return AmplifierAgentIntelligence() if model is None else AmplifierAgentIntelligence(model)
        case "codex":
            from reality_check.intelligence.codex import CodexIntelligence

            return CodexIntelligence()
        case "claude":
            from reality_check.intelligence.claude import ClaudeIntelligence

            return ClaudeIntelligence()


def select_intelligence(
    intelligence: Intelligence | None,
    agent_provider: AgentProvider | None,
    model: str | None,
    default_models: dict[AgentProvider, str],
) -> tuple[Intelligence, str]:
    """The intelligence a capability runs through and the model it asks for.

    An injected intelligence wins over `agent_provider`, which then only picks the default model; with neither
    named, that default is the first agent provider's, since nothing about an injected implementation says which
    agent provider it speaks for.
    """
    if intelligence is None:
        agent_provider = resolve_agent_provider(agent_provider)
        model = default_models[agent_provider] if model is None else model
        return resolve_intelligence(agent_provider, model), model
    return intelligence, default_models[agent_provider or AGENT_PROVIDERS[0]] if model is None else model


def unsupported(agent_provider: AgentProvider) -> RealityCheckError:
    """The failure of an agent provider whose implementation refuses every run."""
    return RealityCheckError(
        code="agent-provider-unsupported",
        message=f"Checks run only on the copilot agent provider, and {agent_provider} was asked for.",
        remedy='Pass agent_provider="copilot" to the library, or --agent-provider copilot on the command line.',
    )


def _install_source(extra: str) -> str:
    url = repository_url()
    return f'"{DISTRIBUTION}[{extra}] @ git+{url}"' if url else f'"{DISTRIBUTION}[{extra}]"'
