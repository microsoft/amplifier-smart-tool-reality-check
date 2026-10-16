"""Amplifier Agent in the intelligence interface; it refuses every run."""

from reality_check.intelligence.interface import AgentRun, unsupported
from reality_check.intelligence.schemas import AgentRequest, Steering
from reality_check.schemas import DEFAULT_INTELLIGENCE_MODELS


class AmplifierAgentIntelligence:
    """Stands in for Amplifier Agent; every run fails, naming the agent provider that works."""

    def __init__(self, model: str = DEFAULT_INTELLIGENCE_MODELS["amplifier-agent"]) -> None:
        self.implementation = "amplifier-agent"
        self.steering: Steering = "restart"
        self.model = model

    def preflight(self) -> None:
        raise unsupported("amplifier-agent")

    async def start(self, request: AgentRequest) -> AgentRun:
        raise unsupported("amplifier-agent")
