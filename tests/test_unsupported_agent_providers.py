"""The agent providers other than copilot refuse every run, naming the one that works."""

import pytest

from reality_check.intelligence.amplifier_agent import AmplifierAgentIntelligence
from reality_check.intelligence.claude import ClaudeIntelligence
from reality_check.intelligence.codex import CodexIntelligence
from reality_check.intelligence.interface import Intelligence
from reality_check.intelligence.schemas import AgentRequest
from reality_check.schemas import RealityCheckError

STUBS: list[tuple[Intelligence, str]] = [
    (AmplifierAgentIntelligence(), "restart"),
    (CodexIntelligence(), "mid-turn"),
    (ClaudeIntelligence(), "queued"),
]


@pytest.mark.parametrize(("intelligence", "steering"), STUBS)
async def test_preflight_and_start_refuse_and_name_copilot(intelligence: Intelligence, steering: str) -> None:
    request = AgentRequest(prompt="Do the work.", model="any", timeout_seconds=60)

    with pytest.raises(RealityCheckError) as preflight:
        intelligence.preflight()
    with pytest.raises(RealityCheckError) as start:
        await intelligence.start(request)

    assert intelligence.steering == steering
    for failure in (preflight.value, start.value):
        assert failure.code == "agent-provider-unsupported"
        assert 'agent_provider="copilot"' in failure.remedy
        assert "--agent-provider copilot" in str(failure)
