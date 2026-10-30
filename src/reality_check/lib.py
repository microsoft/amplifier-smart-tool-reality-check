"""Top level entry point for the Reality Check library."""

from pathlib import Path

from reality_check.capabilities.app import folders as app_folders
from reality_check.capabilities.app import mcp_server as app_server_module
from reality_check.capabilities.app import server as app_module
from reality_check.capabilities.app.mcp_server import AppServer
from reality_check.capabilities.check_software import activity, check, checks, intelligence_models, registry
from reality_check.capabilities.check_software.check import CheckRun
from reality_check.capabilities.computer_use import install
from reality_check.core import manifest
from reality_check.core import skill as skill_module
from reality_check.intelligence.interface import Intelligence
from reality_check.schemas import (
    DEFAULT_CHECKS_DIRECTORY,
    DEFAULT_ORIGIN,
    DEFAULT_TIMEOUT_SECONDS,
    AgentProvider,
    AskFirst,
    CheckActivity,
    CheckDetail,
    CheckEvent,
    CheckReference,
    CheckResult,
    CheckSummary,
    CheckTimeoutError,
    ComputerUseInstall,
    EvidenceFile,
    IntelligenceModels,
    Manifest,
    ReasoningEffort,
)

__all__ = [
    "AppServer",
    "CheckActivity",
    "CheckDetail",
    "CheckEvent",
    "CheckResult",
    "CheckRun",
    "CheckSummary",
    "CheckTimeoutError",
    "ComputerUseInstall",
    "EvidenceFile",
    "IntelligenceModels",
]


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
    timeout_seconds: int | None = DEFAULT_TIMEOUT_SECONDS,
    images: list[Path] | None = None,
    origin: str = DEFAULT_ORIGIN,
    detach: bool = False,
    intelligence: Intelligence | None = None,
) -> CheckRun:
    """Start a check of software as a user uses it, returning its handle as soon as it runs. Model-backed.

    With `detach`, the check runs in a process of its own that outlives this one. With `timeout_seconds` None, it runs
    until its agent ends.
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
    after_event: int | None = None,
    before_event: int | None = None,
    tail_events: int | None = None,
    truncate: bool = True,
    checks_directory: Path = DEFAULT_CHECKS_DIRECTORY,
) -> CheckActivity:
    """A check as it stands and its events, from any process, short as the CLI prints them or whole.

    Args:
        check_id: The check, running or ended.
        after_event: Only events with a larger id, such as the last one an earlier read returned.
        before_event: Only events with a smaller id.
        tail_events: Of those, only the last this many; 0 for none.
        truncate: False for the events as events.jsonl keeps them.
        checks_directory: Where the check is kept.
    """
    return activity.read_check_activity(
        check_id=check_id,
        after_event=after_event,
        before_event=before_event,
        tail_events=tail_events,
        truncate=truncate,
        checks_directory=checks_directory,
    )


def list_checks(checks_directory: Path | None = None) -> list[CheckSummary]:
    """Every check on this machine, newest first, from every project checks were started from; or one checks directory's."""
    return checks.list_checks(checks_directory=checks_directory)


def read_check(check_id: str, checks_directory: Path = DEFAULT_CHECKS_DIRECTORY) -> CheckDetail:
    """A check as it stands: its record, its report with evidence links that work from anywhere, and its evidence."""
    return checks.read_check(check_id=check_id, checks_directory=checks_directory)


def read_check_evidence(check_id: str, path: str, checks_directory: Path = DEFAULT_CHECKS_DIRECTORY) -> EvidenceFile:
    """One file from a check's evidence folder, as `read_check` lists it; nothing outside that folder is read."""
    return checks.read_check_evidence(check_id=check_id, path=path, checks_directory=checks_directory)


def app_server(directory: Path | None = None) -> AppServer:
    """The app's MCP server: the tool that opens the app, the tools its view calls, and the view as an MCP App.

    Serve `AppServer.server` over any MCP transport. `AppServer.open` serves the browser host page, which renders the
    view for agents that cannot embed it and reaches the same server at its own `/mcp`. The view shows every check on
    this machine and only reads them.

    Args:
        directory: A checks directory to add to the projects the app shows, and to open on its newest check.
    """
    focus = None
    if directory is not None:
        project = registry.register_project(directory)
        newest = checks.list_checks(project.checks_directory)
        if newest:
            focus = CheckReference(check_id=newest[0].check_id, checks_directory=project.checks_directory)
    return app_server_module.AppServer(
        skill_module.DISTRIBUTION,
        version(),
        focus,
        list_checks=checks.list_checks,
        read_check=lambda check_id, checks_directory: checks.read_check(check_id, checks_directory),
        read_check_activity=activity.read_check_activity,
        read_check_evidence=checks.read_check_evidence,
        can_open_folders=app_folders.can_open_folders,
        open_folder=app_folders.open_folder,
        register_project=registry.register_project,
        registered_projects=registry.registered_projects,
    )


def app_view() -> str:
    """The app's view, an MCP App: the HTML a host renders inline, and the one the browser host page renders."""
    return app_module.view()


def list_intelligence_models() -> IntelligenceModels:
    """The models a check runs on, each with its reasoning efforts, and what runs when given none."""
    return intelligence_models.list_intelligence_models()


def install_computer_use() -> ComputerUseInstall:
    """Install, once, the pinned cua-driver that checks drive desktop apps with; reports one already there."""
    return install.install_computer_use()


def reaching_software_skill() -> str:
    """The skill for reaching software where it runs: LAN URLs, SSH and Tailscale, universes on another machine."""
    return skill_module.skill("reaching-software-skill")


def using_software_skill() -> str:
    """The skill for seeing and using software as a user: an open browser, computer use, a terminal, testers."""
    return skill_module.skill("using-software-skill")


def using_computer_use_skill() -> str:
    """The skill for driving a desktop app's real UI through cua-driver: screenshots, the accessibility tree, input."""
    return skill_module.skill("using-computer-use-skill")


def gathering_evidence_skill() -> str:
    """The skill for what evidence to gather for each kind of software, and where to put it."""
    return skill_module.skill("gathering-evidence-skill")
