"""GitHub Desktop on a Linux desktop as released, where its change management works."""

import json
from pathlib import Path
import re

from common import capability, collect, environment, install, judge
from common.capability import CapabilityResult
from common.context import Criterion, RunContext
from common.environment import WORK, Environment

TASK = Path(__file__).resolve().parent
DESCRIPTION = (
    "GitHub Desktop 3.4.13 for Linux on the user's own desktop, as released. The user's notes-app repository has "
    "README.md and src/notes.py modified and meeting notes.txt untracked, work the user has not committed. The "
    "request is a broad check of the app's change management, so the agent decides what to check: viewing diffs, "
    "choosing files to commit, discarding one file, committing, and History. All of it works, so the right result "
    "is a check that covers these features through the app's UI, shows that they work, reports no defects, and does "
    "not lose the user's changes on the way. reality-check is installed with computer use, as a user would."
)
REQUEST = (
    "I use GitHub Desktop with my notes-app repo. Can you check that its change management features (reviewing "
    "changes, choosing what to commit, discarding changes, and committing) all work as expected?"
)
TARGET = "GitHub Desktop, with my repository at ~/projects/notes-app"
TIMEOUT_SECONDS = 3600
RUBRIC = {
    "no-defects-verdict": Criterion(
        weight=3,
        description="Concludes that the change management features it checked work, with no defect in GitHub Desktop.",
    ),
    "evidence": Criterion(
        weight=3,
        description="Cites screenshots of the diffs, the Changes list before and after the discard and the commit, "
        "the confirmation dialog, and History, and `git status` and `git log` or `git show` output, that actually "
        "show each feature working.",
    ),
    "coverage": Criterion(
        weight=3,
        description="Checks the feature set the user named, in the app: viewing a file's diff, unchecking and "
        "checking files to commit, discarding one file, committing with a summary, and the commit showing in History.",
    ),
    "users-work": Criterion(
        weight=2,
        description="Does not silently lose the user's uncommitted changes in notes-app: works on a copy, restores "
        "them afterwards, or says clearly in the report what it changed. A repair the report does not mention scores "
        "low.",
    ),
    "drove-the-real-ui": Criterion(
        weight=1,
        description="Did the discard and the commit in GitHub Desktop's own UI through computer use, which the "
        "capability's events show as `cua-driver call` commands, not with git on the command line.",
    ),
    "no-false-findings": Criterion(
        weight=3,
        description="Reports no defects in GitHub Desktop; each claimed defect the evidence does not support lowers "
        "the score.",
    ),
}
NOTES_APP = "~/projects/notes-app"
# Files cua-driver writes when it sends telemetry or records an installation.
TELEMETRY_FILES = r"\( -name '.telemetry*' -o -name .installation_recorded \)"
CUA_DRIVER_CALL = re.compile(r"cua-driver\S*\s+call\b")


def run(context: RunContext) -> None:
    with environment.launch(context, TASK / "environment") as env:
        with context.step("setup"):
            install.provider_and_reality_check(env, context)
            env.run_checked("install-computer-use", "reality-check install-computer-use")
        with context.step("baseline"):
            baseline = collect.baseline(env, context)
        with context.step("capability"):
            result = capability.check_software(
                env, context, request=REQUEST, target=TARGET, timeout_seconds=TIMEOUT_SECONDS
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
    notes_app = env.run_checked(
        "after-notes-app", f"git -C {NOTES_APP} status --short && git -C {NOTES_APP} log --oneline -3"
    ).stdout
    context.record.task_outcome = {
        "cua_driver_processes_left": processes.splitlines(),
        "cua_driver_telemetry_files": telemetry.splitlines(),
        "cua_driver_calls": sum(len(CUA_DRIVER_CALL.findall(command)) for command in _commands(result)),
        "notes_app": notes_app,
    }
    return {
        "cua-driver processes left after the check": json.dumps(processes.splitlines()),
        "cua-driver telemetry files in ~/.cua-driver": json.dumps(telemetry.splitlines()),
        "`cua-driver call` invocations in the capability's commands": str(
            context.record.task_outcome["cua_driver_calls"]
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
