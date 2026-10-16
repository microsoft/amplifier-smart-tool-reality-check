from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, NamedTuple

from pydantic import BaseModel, Field

ReasoningEffort = Literal["low", "medium", "high", "xhigh", "max"]
AgentProvider = Literal["copilot", "amplifier-agent", "codex", "claude"]
# Also the order an agent provider is picked in when none is named.
AGENT_PROVIDERS: tuple[AgentProvider, ...] = ("copilot", "amplifier-agent", "codex", "claude")

DEFAULT_INTELLIGENCE_MODELS: dict[AgentProvider, str] = {
    "copilot": "gpt-6.1-sol",
    "amplifier-agent": "openai/gpt-6-astra",
    "codex": "gpt-6.1-sol",
    "claude": "claude-opus-5-5",
}
DEFAULT_INTELLIGENCE_REASONING_EFFORT: ReasoningEffort = "medium"

SEMVER_PATTERN = r"^\d+\.\d+\.\d+$"
SLUG_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"


class RealityCheckError(Exception):
    """Raised for any failure the library can name and explain how to fix."""

    def __init__(self, code: str, message: str, remedy: str) -> None:
        super().__init__(code, message, remedy)
        self.code = code
        self.message = message
        self.remedy = remedy

    def __str__(self) -> str:
        return f"{self.message} {self.remedy}"


# region: Manifest


class ManifestRequirement(BaseModel):
    """One environment prerequisite; `install` references documentation, never a command."""

    name: str
    purpose: str
    install: str
    optional: bool = False


class Manifest(BaseModel):
    """The structured form of SMART_TOOL.md."""

    smart_tool_format: int
    name: str = Field(pattern=SLUG_PATTERN)
    version: str = Field(pattern=SEMVER_PATTERN)
    description: str
    use_cases: list[str]
    platforms: list[str]
    requires: list[ManifestRequirement] = Field(default_factory=list)
    body: str = Field(description="The Markdown below the frontmatter: the skill `--help` renders")


# endregion

# region: Skill


class Capability(NamedTuple):
    """One capability of the tool: its line in the skill's capability list and its own skill."""

    name: str
    summary: str
    model_backed: bool
    skill: str  # the capability's skill body, a Markdown file relative to the skill directory
    resources: tuple[str, ...] = ()  # the files that skill refers to, relative to the skill directory


# endregion

# region: Check software

# When the agent stops to ask before the work starts.
AskFirst = Literal["when-off", "always", "never"]
CheckStatus = Literal["running", "done", "cancelled"]
CheckEventKind = Literal["started", "progress", "tool", "usage", "steered", "finished", "failed"]
# Relative, so checks are kept beside the project the caller works in.
DEFAULT_CHECKS_DIRECTORY = Path(".agents/reality-check")


class CheckResult(BaseModel):
    """How a check ended. A report that says the software failed is a result, not an error."""

    check_id: str
    status: CheckStatus
    session_id: str | None = Field(description="The agent session a later check resumes")
    agent_provider: AgentProvider
    report: str = Field(description="The agent's final message, its report in Markdown")
    directory: Path
    next: str = Field(description="The exact command that resumes this check")


class CheckTimeoutError(RealityCheckError):
    """A check that ran out of time; `result` is what it had when it was stopped, and its session can be resumed."""

    def __init__(self, message: str, remedy: str, result: CheckResult) -> None:
        super().__init__("check-timeout", message, remedy)
        self.result = result


class CheckEvent(BaseModel):
    """One thing that happened in a check, as one JSON line in the check's events.jsonl and on the CLI's stdout."""

    check_id: str
    time: datetime = Field(default_factory=lambda: datetime.now(UTC))
    kind: CheckEventKind
    text: str = ""
    data: dict[str, Any] = Field(default_factory=dict)


class CheckRecord(BaseModel):
    """A check as its check.json keeps it, so other processes and later checks can find it."""

    check_id: str
    request: str
    target: str | None
    resume: str | None
    previous_checks: list[Path] | None = None
    ask_first: AskFirst
    keep_running: bool
    agent_provider: AgentProvider
    model: str
    reasoning_effort: ReasoningEffort
    session_id: str | None = None
    status: CheckStatus | Literal["failed"] = "running"
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    ended_at: datetime | None = None


# endregion
