"""OpenAI Codex in the intelligence interface; it refuses every run."""

from reality_check.intelligence.interface import AgentRun, unsupported
from reality_check.intelligence.schemas import AgentRequest, Steering


class CodexIntelligence:
    """Stands in for Codex; every run fails, naming the agent provider that works."""

    def __init__(self) -> None:
        self.implementation = "codex"
        self.steering: Steering = "mid-turn"

    def preflight(self) -> None:
        raise unsupported("codex")

    async def start(self, request: AgentRequest) -> AgentRun:
        raise unsupported("codex")
