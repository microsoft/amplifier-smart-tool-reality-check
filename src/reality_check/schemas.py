from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, NamedTuple, Self, get_args

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
DEFAULT_INTELLIGENCE_REASONING_EFFORT: ReasoningEffort = "high"
# Who started or steered a check when the caller does not say; the tool cannot know, so it never guesses.
DEFAULT_ORIGIN = "unknown"

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

# region: Intelligence models

ALL_EFFORTS: list[ReasoningEffort] = list(get_args(ReasoningEffort))


class IntelligenceModel(BaseModel):
    """One model Reality Check runs its agent on, and the reasoning efforts it takes."""

    agent_provider: AgentProvider
    id: str = Field(description="The agent provider's own model ID")
    label: str
    reasoning_efforts: list[ReasoningEffort] = Field(description="Empty when the model takes none, and none is sent")
    vision: bool = Field(description="Whether the model can be shown images")


# The models Reality Check supports and recommends, not a mirror of what an agent provider offers.
INTELLIGENCE_MODELS: tuple[IntelligenceModel, ...] = (
    IntelligenceModel(
        agent_provider="copilot", id="gpt-6.1-sol", label="GPT-6.1 Sol", reasoning_efforts=ALL_EFFORTS, vision=True
    ),
    IntelligenceModel(
        agent_provider="copilot", id="gpt-6-astra", label="GPT-6 Astra", reasoning_efforts=ALL_EFFORTS, vision=True
    ),
    IntelligenceModel(
        agent_provider="copilot", id="gpt-6-luna", label="GPT-6 Luna", reasoning_efforts=ALL_EFFORTS, vision=True
    ),
    IntelligenceModel(
        agent_provider="copilot",
        id="claude-sonnet-5.5",
        label="Claude Sonnet 5.5",
        reasoning_efforts=ALL_EFFORTS,
        vision=True,
    ),
    IntelligenceModel(
        agent_provider="copilot",
        id="claude-opus-5.5",
        label="Claude Opus 5.5",
        reasoning_efforts=ALL_EFFORTS,
        vision=True,
    ),
    IntelligenceModel(agent_provider="copilot", id="auto", label="Auto", reasoning_efforts=[], vision=False),
    IntelligenceModel(
        agent_provider="amplifier-agent",
        id="openai/gpt-6.1-sol",
        label="GPT-6.1 Sol",
        reasoning_efforts=ALL_EFFORTS,
        vision=True,
    ),
    IntelligenceModel(
        agent_provider="amplifier-agent",
        id="openai/gpt-6-astra",
        label="GPT-6 Astra",
        reasoning_efforts=ALL_EFFORTS,
        vision=True,
    ),
    IntelligenceModel(
        agent_provider="amplifier-agent",
        id="anthropic/claude-sonnet-5-5",
        label="Claude Sonnet 5.5",
        reasoning_efforts=ALL_EFFORTS,
        vision=True,
    ),
    IntelligenceModel(
        agent_provider="amplifier-agent",
        id="anthropic/claude-opus-5-5",
        label="Claude Opus 5.5",
        reasoning_efforts=ALL_EFFORTS,
        vision=True,
    ),
    IntelligenceModel(
        agent_provider="codex", id="gpt-6.1-sol", label="GPT-6.1 Sol", reasoning_efforts=ALL_EFFORTS, vision=True
    ),
    IntelligenceModel(
        agent_provider="codex", id="gpt-6-astra", label="GPT-6 Astra", reasoning_efforts=ALL_EFFORTS, vision=True
    ),
    IntelligenceModel(
        agent_provider="codex", id="gpt-6-luna", label="GPT-6 Luna", reasoning_efforts=ALL_EFFORTS, vision=True
    ),
    IntelligenceModel(
        agent_provider="claude",
        id="claude-sonnet-5-5",
        label="Claude Sonnet 5.5",
        reasoning_efforts=ALL_EFFORTS,
        vision=True,
    ),
    IntelligenceModel(
        agent_provider="claude",
        id="claude-opus-5-5",
        label="Claude Opus 5.5",
        reasoning_efforts=ALL_EFFORTS,
        vision=True,
    ),
)


class IntelligenceChoice(BaseModel):
    """What runs a check's agent: the agent provider, the model, and how hard it thinks."""

    agent_provider: AgentProvider
    model: str
    reasoning_effort: ReasoningEffort | None


class IntelligenceModels(BaseModel):
    """The models a check can run on, each with its reasoning efforts."""

    models: list[IntelligenceModel] = Field(description="Those of the agent providers that are installed")
    default: IntelligenceChoice = Field(description="What `check_software` runs with when given none")


# endregion

# region: Check software

# When the agent stops to ask before the work starts.
AskFirst = Literal["when-off", "always", "never"]
CheckStatus = Literal["running", "done", "cancelled", "timed-out"]
# A check's status as its record and its process tell it: `crashed` is running by its record with its process gone.
CheckState = Literal["running", "crashed", "done", "cancelled", "timed-out", "failed"]
CheckEventKind = Literal["started", "progress", "reasoning", "tool", "usage", "steered", "finished", "failed"]
# The fields of a tool event's data that hold its arguments and result in full.
FULL_FIELDS = ("arguments", "result", "detailed_result")
# Relative, so checks are kept beside the project the caller works in.
DEFAULT_CHECKS_DIRECTORY = Path(".agents/reality-check")
DEFAULT_TIMEOUT_SECONDS = 3600


class CheckUsage(BaseModel):
    """What a check's agent used, summed over its model calls and counted the same way for every agent provider."""

    model_calls: int = 0
    fresh_input_tokens: int = Field(default=0, description="Input tokens neither read from nor written to a cache")
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = Field(default=0, description="Zero for agent providers that do not report them")
    billing: dict[str, float] = Field(
        default_factory=dict,
        description="What the agent provider bills, by unit such as USD or AIU; empty when it reports none",
    )


class CheckResult(BaseModel):
    """How a check ended. A report that says the software failed is a result, not an error."""

    check_id: str
    status: CheckStatus
    session_id: str | None = Field(description="The agent session a later check resumes")
    agent_provider: AgentProvider
    report: str = Field(description="The agent's final message, its report in Markdown")
    directory: Path
    next: str = Field(description="The exact command that resumes this check")
    timeout_seconds: int | None = Field(description="The check's deadline; None when it had none")
    elapsed_seconds: float
    usage: CheckUsage


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

    def brief(self) -> Self:
        """The event without a tool's full arguments and result, which events.jsonl keeps."""
        if self.kind != "tool":
            return self
        return self.model_copy(
            update={"data": {key: value for key, value in self.data.items() if key not in FULL_FIELDS}}
        )


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
    reasoning_effort: ReasoningEffort | None = Field(description="What was sent; None when the model takes none")
    session_id: str | None = None
    status: CheckStatus | Literal["failed"] = "running"
    timeout_seconds: int | None = Field(
        default=DEFAULT_TIMEOUT_SECONDS, description="The check's deadline; None when it has none"
    )
    usage: CheckUsage = Field(default_factory=CheckUsage, description="Kept with every model call while the check runs")
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    ended_at: datetime | None = None
    pid: int | None = Field(
        default=None, description="The process running the check; a running check whose process is gone has crashed"
    )
    pid_started: float | None = Field(
        default=None,
        description="When that process started, in seconds since boot, so a later process given its pid is not taken for it",
    )
    last_event: datetime | None = None
    origin: str = DEFAULT_ORIGIN
    images: list[Path] | None = Field(
        default=None, description="The images shown to the agent, as copied into the check"
    )
    detached: bool = Field(default=False, description="Whether the check runs in a process of its own")


ActivityKind = Literal["request", "said", "reasoning", "tool", "tool-result", "usage", "steered", "ended"]


class ActivityEntry(BaseModel):
    """One thing in a check's activity: what was asked, what its agent said, thought, and did, and how it ended."""

    time: datetime
    kind: ActivityKind
    text: str
    origin: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class CheckActivity(BaseModel):
    """A check as it stands and its activity, from the start or from an earlier read's cursor."""

    check: CheckRecord
    state: CheckState
    process_log: Path | None = Field(description="What the check's own process printed, for a detached check")
    entries: list[ActivityEntry]
    cursor: int = Field(description="Pass as `after` to read only what comes next")


class Project(BaseModel):
    """A directory checks were started from, and the checks directory they are kept in."""

    root: Path
    checks_directory: Path


class CheckReference(BaseModel):
    """A check another check continues or builds on."""

    check_id: str
    checks_directory: Path


class CheckSummary(BaseModel):
    """One check, as a list of checks shows it."""

    check_id: str
    project: Project
    request: str
    target: str | None
    state: CheckState
    started_at: datetime
    ended_at: datetime | None
    agent_provider: AgentProvider
    model: str
    origin: str
    resume: str | None = Field(description="The check this one continues, in the same checks directory")
    has_report: bool


class EvidenceEntry(BaseModel):
    """One file a check saved as evidence."""

    path: str = Field(description="Relative to the check's directory, such as `evidence/01-home.png`")
    media_type: str
    size: int
    modified_at: datetime
    referenced: bool = Field(description="Whether the report cites it")


class CheckDetail(BaseModel):
    """A check as it stands: its record, its report, and the evidence it has saved so far."""

    check: CheckRecord
    state: CheckState
    project: Project
    directory: Path
    report: str | None = Field(
        description="The report, with every path into this check's evidence folder written as `evidence/<name>`; None "
        "until the check writes one"
    )
    evidence: list[EvidenceEntry]
    resumes: CheckReference | None
    previous_checks: list[CheckReference]


class EvidenceFile(BaseModel):
    """One evidence file's content."""

    path: str
    media_type: str = Field(description="text/plain for HTML and SVG, so a viewer never runs them")
    content: bytes


# endregion

# region: Computer use

# The desktop computer use drives. Under WSL that is the Windows desktop.
ComputerUseTarget = Literal["windows", "wsl", "linux", "macos"]


class ComputerUseInstall(BaseModel):
    """The cua-driver that checks drive desktop apps with."""

    target: ComputerUseTarget
    version: str
    executable: Path
    already_installed: bool = Field(description="Whether it was there already, so nothing was downloaded")
    remaining_step: str | None = Field(description="What the user still has to do by hand before checks can use it")


# endregion
