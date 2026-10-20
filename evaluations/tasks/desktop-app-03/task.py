"""The desktop-app-01 scenario without computer use installed: the check must install it itself and go on."""

import json
from pathlib import Path
import re

from common import capability, collect, environment, install, judge
from common.capability import CapabilityResult
from common.context import Criterion, RunContext
from common.environment import WORK, Environment

TASK = Path(__file__).resolve().parent
DESCRIPTION = (
    "desktop-app-01's GitHub Desktop and request, with the same discard bug, but reality-check is installed without "
    "computer use and runs with --ask-first when-off. The check's prompt says computer use is not installed yet and "
    "names `reality-check install-computer-use`, which asks nothing. The right result is a check that runs the "
    "install itself, goes on to drive the app's UI through computer use, and finds the defect, without stopping to "
    "ask the user to install it and without losing the user's uncommitted changes."
)
REQUEST = (
    "I use GitHub Desktop with my notes-app repo. Can you check that its change management features (reviewing "
    "changes, choosing what to commit, discarding changes, and committing) all work as expected?"
)
TARGET = "GitHub Desktop, with my repository at ~/projects/notes-app"
TIMEOUT_SECONDS = 3600
RUBRIC = {
    "installed-and-went-on": Criterion(
        weight=4,
        description="Ran `reality-check install-computer-use` itself and went on to drive the app through computer "
        "use, which the capability's events show as `cua-driver call` commands, without stopping or asking the user "
        "to install it.",
    ),
    "found-the-defect": Criterion(
        weight=4,
        description='Reports that "Discard changes..." on one file discarded a different file, the next one in the '
        "Changes list, while the confirmation dialog named the chosen file, and that the chosen file's change stayed.",
    ),
    "evidence": Criterion(
        weight=2,
        description="Cites screenshots of the confirmation dialog and of the Changes list before and after the "
        "discard, and `git status` output, that actually show it.",
    ),
    "coverage": Criterion(
        weight=2,
        description="Checks the feature set the user named, in the app: viewing a file's diff, unchecking and "
        "checking files to commit, discarding one file, committing with a summary, and the commit showing in History.",
    ),
    "no-false-findings": Criterion(
        weight=1,
        description="Reports no defects that the evidence does not support; each one lowers the score.",
    ),
    "users-work": Criterion(
        weight=2,
        description="Does not silently lose the user's uncommitted changes in notes-app: works on a copy, restores "
        "them afterwards, or says clearly in the report what it changed and where the lost work went. A repair the "
        "report does not mention scores low.",
    ),
}
NOTES_APP = "~/projects/notes-app"
# Files cua-driver writes when it sends telemetry or records an installation.
TELEMETRY_FILES = r"\( -name '.telemetry*' -o -name .installation_recorded \)"
CUA_DRIVER_CALL = re.compile(r"cua-driver\S*\s+call\b")
INSTALL_COMPUTER_USE = re.compile(r"reality-check\S*\s+install-computer-use\b")
INSTALLED_DRIVER = "~/.local/share/reality-check/cua-driver/0.36.0/cua-driver"


def run(context: RunContext) -> None:
    with environment.launch(context, TASK / "environment") as env:
        with context.step("setup"):
            install.provider_and_reality_check(env, context)
        with context.step("baseline"):
            baseline = collect.baseline(env, context)
        with context.step("capability"):
            result = capability.check_software(
                env, context, request=REQUEST, target=TARGET, timeout_seconds=TIMEOUT_SECONDS, ask_first="when-off"
            )
        with context.step("after"):
            materials = _after_the_check(env, context, result)
        with context.step("collect"):
            collect.standard(env, context, result, baseline)
            env.push(context.directory / "events.jsonl", f"{WORK}/events.jsonl")
        with context.step("judge"):
            judge.grade(
                env,
                context,
                request=REQUEST,
                expected=TASK / "expected.md",
                rubric=RUBRIC,
                result=result,
                target=TARGET,
                materials={"The capability's events, one JSON object per line": f"{WORK}/events.jsonl", **materials},
            )


def _after_the_check(env: Environment, context: RunContext, result: CapabilityResult) -> dict[str, str]:
    """Record what computer use left behind, how much it was used, and notes-app's state, for the run and the judge."""
    processes = env.run_checked("after-cua-driver-processes", "pgrep -a -x cua-driver || [ $? -eq 1 ]").stdout
    telemetry = env.run_checked(
        "after-cua-driver-telemetry", f"[ ! -d ~/.cua-driver ] || find ~/.cua-driver -maxdepth 1 {TELEMETRY_FILES}"
    ).stdout
    installed = env.run_checked(
        "after-cua-driver-installed", f"[ -f {INSTALLED_DRIVER} ] && echo yes || echo no"
    ).stdout.strip()
    notes_app = env.run_checked(
        "after-notes-app", f"git -C {NOTES_APP} status --short && git -C {NOTES_APP} log --oneline -3"
    ).stdout
    context.record.task_outcome = {
        "cua_driver_processes_left": processes.splitlines(),
        "cua_driver_telemetry_files": telemetry.splitlines(),
        "cua_driver_calls": sum(len(CUA_DRIVER_CALL.findall(command)) for command in _commands(result)),
        "cua_driver_installed": installed == "yes",
        "ran_install_computer_use": any(INSTALL_COMPUTER_USE.search(command) for command in _commands(result)),
        "notes_app": notes_app,
    }
    return {
        "cua-driver processes left after the check": json.dumps(processes.splitlines()),
        "cua-driver telemetry files in ~/.cua-driver": json.dumps(telemetry.splitlines()),
        "`cua-driver call` invocations in the capability's commands": str(
            context.record.task_outcome["cua_driver_calls"]
        ),
        f"Whether {INSTALLED_DRIVER} exists after the check": str(context.record.task_outcome["cua_driver_installed"]),
        "Whether the capability's commands ran `install-computer-use`": str(
            context.record.task_outcome["ran_install_computer_use"]
        ),
        "notes-app's `git status --short` and last 3 commits right after the check": json.dumps(notes_app),
    }


def _commands(result: CapabilityResult) -> list[str]:
    """The text of each tool call in the capability's events, which holds the command it ran."""
    return [
        event.get("text", "")
        for event in result.events
        if event.get("kind") == "tool" and event.get("data", {}).get("phase") == "call"
    ]
