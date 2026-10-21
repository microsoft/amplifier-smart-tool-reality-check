"""The host side of the standard collection: a baseline before the capability, and what it changed after."""

from pathlib import Path
import shlex
import shutil
import tempfile

from common import collect_in_environment, providers
from common.capability import CapabilityResult
from common.context import RunContext
from common.environment import HOME, WORK, Environment
from pydantic import BaseModel

IN_ENVIRONMENT = Path(collect_in_environment.__file__)


class Baseline(BaseModel):
    """The twin's time before the capability, as seconds since the epoch; the package lists are in the run."""

    since: str


def baseline(env: Environment, context: RunContext) -> Baseline:
    """The time and the installed packages before the capability, kept on the host so nothing hints at them."""
    since = env.run_checked("baseline-time", "date +%s.%N").stdout.strip()
    before = context.directory / "packages" / "before"
    before.mkdir(parents=True, exist_ok=True)
    for name, command in collect_in_environment.PACKAGE_LISTS.items():
        listed = env.run(f"baseline-{name}", f"sudo {shlex.join(command)}")
        (before / name).write_text(listed.stdout, encoding="utf-8")
    return Baseline(since=since)


def standard(env: Environment, context: RunContext, result: CapabilityResult, baseline: Baseline) -> None:
    """Copy what the agent did into the run: its record, session, logs, changed files, packages, and containers."""
    provider = providers.provider(context.spec.agent_provider)
    env.run_checked("work", f"sudo mkdir -p {WORK} && sudo chown user {WORK}")
    env.push(IN_ENVIRONMENT, f"{WORK}/collect.py")
    config = {
        "since": baseline.since,
        "out": f"{WORK}/out",
        "check_directory": result.record_directory,
        "session_id": result.outcome.get("session_id"),
        "sessions": home(provider.sessions),
        "logs": [home(path) for path in provider.logs],
    }
    env.push_json(config, f"{WORK}/collect.json")
    env.run_checked(
        "collect",
        f"sudo python3 {WORK}/collect.py {WORK}/collect.json && sudo chown -R user {WORK}/out",
        timeout_seconds=1800,
    )
    with tempfile.TemporaryDirectory() as scratch:
        collected = Path(scratch) / "out"
        env.pull(f"{WORK}/out", collected)
        for child in collected.iterdir():
            destination = context.directory / child.name
            if destination.is_dir() and child.is_dir():
                shutil.copytree(child, destination, dirs_exist_ok=True)
            else:
                shutil.move(child, destination)
    packages = context.directory / "packages"
    collect_in_environment.installed_diff(packages / "before", packages / "after", context.directory / "installed.diff")
    env.container_logs(context.directory / "logs" / "dockerd.log")
    report = context.directory / "check" / "report.md"
    if report.is_file():
        shutil.copy2(report, context.directory / "report.md")


def home(path: str) -> str:
    """`path` with a leading `~` made the twin user's home."""
    return path.replace("~", HOME, 1) if path.startswith("~") else path
