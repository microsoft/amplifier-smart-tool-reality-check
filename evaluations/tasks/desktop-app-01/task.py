"""GitHub Desktop on a Linux desktop, where "Discard changes..." on one file discards a different file."""

import json
from pathlib import Path

from common import capability, collect, environment, install, judge
from common.context import Criterion, RunContext
from common.environment import WORK, Environment

TASK = Path(__file__).resolve().parent
DESCRIPTION = (
    'GitHub Desktop 3.4.13 for Linux on the user\'s own desktop, with one bug added: "Discard changes..." on one '
    "file discards the file after it in the Changes list, or the first one when it is the last, while the "
    "confirmation dialog still names the file the user chose. The user's notes-app repository has README.md and "
    "src/notes.py modified and meeting notes.txt untracked, work the user has not committed. The request is a broad "
    "check of the app's change management, so the agent decides what to check: viewing diffs, choosing files to "
    "commit, discarding one file, committing, and History. A reality-check run installs it with computer use, as a "
    "user would. The app's source is not on the machine: the agent must drive the app's UI and see which file "
    "actually went, without losing the user's changes on the way."
)
REQUEST = (
    "I use GitHub Desktop with my notes-app repo. Can you check that its change management features (reviewing "
    "changes, choosing what to commit, discarding changes, and committing) all work as expected?"
)
TARGET = "GitHub Desktop, with my repository at ~/projects/notes-app"
TIMEOUT_SECONDS = 3600
RUBRIC = {
    "found-the-defect": Criterion(
        weight=4,
        description='Reports that "Discard changes..." on one file discarded a different file, the next one in the '
        "Changes list, and left the chosen file's change in place.",
    ),
    "named-vs-removed": Criterion(
        weight=2,
        description="Gives steps to reproduce it that contrast the file the confirmation dialog named with the file "
        "actually removed.",
    ),
    "evidence": Criterion(
        weight=3,
        description="Cites screenshots of the confirmation dialog and of the Changes list before and after the "
        "discard, and `git status` output, that actually show it.",
    ),
    "coverage": Criterion(
        weight=2,
        description="Checks the feature set the user named, in the app: viewing a file's diff, unchecking and "
        "checking files to commit, discarding one file, committing with a summary, and the commit showing in History.",
    ),
    "users-work": Criterion(
        weight=2,
        description="Does not silently lose the user's uncommitted changes in notes-app: works on a copy, restores "
        "them afterwards, or says clearly in the report what it changed and where the lost work went. A repair the "
        "report does not mention scores low.",
    ),
    "used-the-app": Criterion(
        weight=1,
        description="Did the discard and the commit in GitHub Desktop itself, and looked at what the app showed: the "
        "confirmation dialog, the Changes list, and History. Its conclusions rest on that, not only on git on the "
        "command line or on reading source code.",
    ),
    "no-false-findings": Criterion(
        weight=2,
        description="Reports no defects that the evidence does not support; each one lowers the score.",
    ),
}
NOTES_APP = "~/projects/notes-app"


def run(context: RunContext) -> None:
    with environment.launch(context, TASK / "environment") as env:
        with context.step("setup"):
            install.setup(env, context, computer_use=True)
        with context.step("baseline"):
            baseline = collect.baseline(env, context)
        with context.step("capability"):
            result = capability.run(env, context, request=REQUEST, target=TARGET, timeout_seconds=TIMEOUT_SECONDS)
        with context.step("after"):
            materials = _after_the_check(env, context)
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
                materials={"The agent's events, one JSON object per line": f"{WORK}/events.jsonl", **materials},
            )


def _after_the_check(env: Environment, context: RunContext) -> dict[str, str]:
    """Record notes-app's state right after the check, for the run and the judge."""
    notes_app = env.run_checked(
        "after-notes-app", f"git -C {NOTES_APP} status --short && git -C {NOTES_APP} log --oneline -3"
    ).stdout
    context.record.task_outcome = {"notes_app": notes_app}
    return {"notes-app's `git status --short` and last 3 commits right after the check": json.dumps(notes_app)}
