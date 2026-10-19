"""Top level entry point for the Reality Check library."""

from pathlib import Path

from reality_check.capabilities.check_software import activity, check, intelligence_models
from reality_check.capabilities.check_software.check import CheckRun
from reality_check.core import manifest
from reality_check.core import skill as skill_module
from reality_check.intelligence.interface import Intelligence
from reality_check.schemas import (
    DEFAULT_CHECKS_DIRECTORY,
    DEFAULT_ORIGIN,
    AgentProvider,
    AskFirst,
    CheckActivity,
    CheckEvent,
    CheckResult,
    CheckTimeoutError,
    IntelligenceModels,
    Manifest,
    ReasoningEffort,
)

__all__ = ["CheckActivity", "CheckEvent", "CheckResult", "CheckRun", "CheckTimeoutError", "IntelligenceModels"]


def load_manifest() -> Manifest:
    """The tool's manifest as structured data, read from the SMART_TOOL.md shipped inside the package."""
    return manifest.load_manifest()


def skill(capability: str | None = None) -> str:
    """The tool's skill, or the named capability's own skill, wrapped so a reader knows where the tool's files are."""
    return skill_module.skill(capability)


def version() -> str:
    """The installed package's version, from its metadata."""
    return skill_module.version()


async def check_software(
    request: str,
    target: str | None = None,
    resume: str | None = None,
    previous_checks: list[Path] | None = None,
    ask_first: AskFirst = "when-off",
    keep_running: bool = False,
    checks_directory: Path = DEFAULT_CHECKS_DIRECTORY,
    agent_provider: AgentProvider | None = None,
    model: str | None = None,
    reasoning_effort: ReasoningEffort | None = None,
    timeout_seconds: int = 3600,
    images: list[Path] | None = None,
    origin: str = DEFAULT_ORIGIN,
    detach: bool = False,
    intelligence: Intelligence | None = None,
) -> CheckRun:
    """Start a check of software as a user uses it, returning its handle as soon as it runs. Model-backed.

    With `detach`, the check runs in a process of its own that outlives this one.
    """
    return await check.check_software(
        request=request,
        target=target,
        resume=resume,
        previous_checks=previous_checks,
        ask_first=ask_first,
        keep_running=keep_running,
        checks_directory=checks_directory,
        agent_provider=agent_provider,
        model=model,
        reasoning_effort=reasoning_effort,
        timeout_seconds=timeout_seconds,
        images=images,
        origin=origin,
        detach=detach,
        intelligence=intelligence,
    )


def steer_check(
    check_id: str, message: str, checks_directory: Path = DEFAULT_CHECKS_DIRECTORY, origin: str = DEFAULT_ORIGIN
) -> None:
    """Send a message to a running check's agent, from any process; the check's events show when it lands."""
    check.steer_check(check_id=check_id, message=message, checks_directory=checks_directory, origin=origin)


def cancel_check(check_id: str, checks_directory: Path = DEFAULT_CHECKS_DIRECTORY) -> None:
    """Cancel a running check, from any process; its session can still be resumed."""
    check.cancel_check(check_id=check_id, checks_directory=checks_directory)


def read_check_activity(
    check_id: str,
    after: int | None = None,
    tool_call_id: str | None = None,
    checks_directory: Path = DEFAULT_CHECKS_DIRECTORY,
) -> CheckActivity:
    """A check as it stands and what its agent said, thought, and did, from any process; `after` reads on from a cursor."""
    return activity.read_check_activity(
        check_id=check_id, after=after, tool_call_id=tool_call_id, checks_directory=checks_directory
    )


def list_intelligence_models() -> IntelligenceModels:
    """The models a check runs on, each with its reasoning efforts, and what runs when given none."""
    return intelligence_models.list_intelligence_models()


def reaching_software_skill() -> str:
    """The skill for reaching software where it runs: LAN URLs, SSH and Tailscale, universes on another machine."""
    return skill_module.skill("reaching-software-skill")


def using_software_skill() -> str:
    """The skill for seeing and using software as a user: an open browser, computer use, a terminal, testers."""
    return skill_module.skill("using-software-skill")


def gathering_evidence_skill() -> str:
    """The skill for what evidence to gather for each kind of software, and where to put it."""
    return skill_module.skill("gathering-evidence-skill")
