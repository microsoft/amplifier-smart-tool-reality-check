"""The models a check's agent runs on, and the reasoning efforts each takes."""

from pathlib import Path

from reality_check.intelligence.interface import installed
from reality_check.schemas import (
    AGENT_PROVIDERS,
    ALL_EFFORTS,
    DEFAULT_INTELLIGENCE_MODELS,
    DEFAULT_INTELLIGENCE_REASONING_EFFORT,
    INTELLIGENCE_MODELS,
    AgentProvider,
    IntelligenceChoice,
    IntelligenceModels,
    RealityCheckError,
    ReasoningEffort,
)


def list_intelligence_models() -> IntelligenceModels:
    """The models of the installed agent providers, each with its reasoning efforts, and what runs when given none."""
    # The one `check_software` picks when given no agent provider.
    provider = next((candidate for candidate in AGENT_PROVIDERS if installed(candidate)), AGENT_PROVIDERS[0])
    model = DEFAULT_INTELLIGENCE_MODELS[provider]
    return IntelligenceModels(
        models=[candidate for candidate in INTELLIGENCE_MODELS if installed(candidate.agent_provider)],
        default=IntelligenceChoice(
            agent_provider=provider, model=model, reasoning_effort=default_effort(provider, model)
        ),
    )


def default_effort(agent_provider: AgentProvider, model: str) -> ReasoningEffort | None:
    listed = next(
        (entry for entry in INTELLIGENCE_MODELS if entry.agent_provider == agent_provider and entry.id == model), None
    )
    return None if listed is not None and not listed.reasoning_efforts else DEFAULT_INTELLIGENCE_REASONING_EFFORT


def require_allowed(
    agent_provider: AgentProvider, model: str, reasoning_effort: str | None, images: list[Path]
) -> ReasoningEffort | None:
    """The reasoning effort to send, after raising unless the model is one Reality Check runs on and takes it as asked."""
    allowed = [entry for entry in INTELLIGENCE_MODELS if entry.agent_provider == agent_provider]
    listed = next((entry for entry in allowed if entry.id == model), None)
    if listed is None:
        raise RealityCheckError(
            code="model-not-allowed",
            message=f"{model} is not one of the models Reality Check runs on {agent_provider}.",
            remedy=f"Pick one of: {', '.join(entry.id for entry in allowed)}. "
            "`reality-check list-intelligence-models` lists them with their reasoning efforts.",
        )
    efforts = listed.reasoning_efforts
    if reasoning_effort is not None and reasoning_effort not in efforts:
        raise RealityCheckError(
            code="bad-reasoning-effort",
            message=f"{model} does not take the reasoning effort {reasoning_effort!r}"
            + (f"; it takes {', '.join(efforts)}." if efforts else "; it takes none."),
            remedy="Pass one it takes, or leave the reasoning effort out for its default.",
        )
    if images and not listed.vision:
        raise RealityCheckError(
            code="model-without-vision",
            message=f"{model} cannot be shown images.",
            remedy=f"Pick one that can: {', '.join(entry.id for entry in allowed if entry.vision)}, or leave the "
            "images out.",
        )
    if not efforts:
        return None
    return DEFAULT_INTELLIGENCE_REASONING_EFFORT if reasoning_effort is None else _effort(reasoning_effort)


def _effort(reasoning_effort: str) -> ReasoningEffort:
    """The effort as its literal type, since a caller outside Python can pass any string."""
    for effort in ALL_EFFORTS:
        if effort == reasoning_effort:
            return effort
    raise RealityCheckError(
        code="bad-reasoning-effort",
        message=f"{reasoning_effort!r} is not a reasoning effort.",
        remedy=f"Pass one of: {', '.join(ALL_EFFORTS)}.",
    )
