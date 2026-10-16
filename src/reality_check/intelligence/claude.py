"""Claude Agent SDK in the intelligence interface; it refuses every run."""

from reality_check.intelligence.interface import AgentRun, unsupported
from reality_check.intelligence.schemas import AgentRequest, Steering


class ClaudeIntelligence:
    """Stands in for Claude; every run fails, naming the agent provider that works."""

    def __init__(self) -> None:
        self.implementation = "claude"
        self.steering: Steering = "queued"

    def preflight(self) -> None:
        raise unsupported("claude")

    async def start(self, request: AgentRequest) -> AgentRun:
        raise unsupported("claude")
