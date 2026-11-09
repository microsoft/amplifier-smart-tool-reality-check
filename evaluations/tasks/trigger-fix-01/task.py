"""The todo app with a user's bug report and a request to fix it, to see whether the agent checks the fix."""

from pathlib import Path

from common import capability, collect, environment, install, judge
from common.context import Criterion, RunContext
from common.environment import PROJECT

TASK = Path(__file__).resolve().parent
TODO_APP = TASK.parents[1] / "data" / "todo-app.zip"
DESCRIPTION = (
    "evaluations/data/todo-app.zip, a small todo web app on Python's standard library, placed in ~/project as a repository of "
    "one commit and started with `python3 app.py`. It has one bug: with the Active or Completed filter on, Delete "
    "removes the todo at the same position in the whole list, not the one clicked. The request passes on the users' "
    "report and asks only for a fix. reality-check's skill says to use it after a fix, so in an installed run, with "
    "its skill and CLI there as a user would have them, the agent should check its fix with reality-check on its own "
    "and tell the user the result; the baseline is the control, with neither."
)
# What it evaluates is whether the agent chooses reality-check, which a run of reality-check itself takes as given.
CAPABILITIES = ("installed", "baseline")
REQUEST = "Users say that deleting a todo sometimes removes a different one. Can you fix it?"
TIMEOUT_SECONDS = 1800
RUBRIC = {
    "used-reality-check": Criterion(
        weight=1,
        description="Loaded the reality-check skill or ran `reality-check` on its own, which the session shows as a "
        "skill load of reality-check, a `skill.invoked` event for Copilot or a `Skill` tool call for Claude Code, or "
        "a shell command that runs `reality-check`. 100 when it did, 0 when it did not.",
    ),
    "reported-result": Criterion(
        weight=1,
        description="After the check, told the user its result in its last message: what was checked and what was "
        "found.",
    ),
    "offered-broader-check": Criterion(
        weight=1,
        description="In its last message, named in the user's terms parts of the app next to the fix that the check "
        "did not cover, and offered to check them, without starting that check unasked. 100 when it did both, 50 "
        "when it named them but made no offer, 0 when it did neither.",
    ),
}
STAGED = "/var/tmp/todo-app.zip"
# A fixed identity and date make the commit the same on every run.
COMMIT = (
    "git init -q --initial-branch main && git add --all && GIT_AUTHOR_DATE=2026-10-01T09:00:00Z "
    "GIT_COMMITTER_DATE=2026-10-01T09:00:00Z git -c user.name='Dana Tester' -c user.email=dana@example.com "
    "commit -q -m 'Todo app'"
)


def run(context: RunContext) -> None:
    with environment.launch(context, TASK / "environment") as env:
        with context.step("setup"):
            install.setup(env, context)
        with context.step("place"):
            env.push(TODO_APP, STAGED)
            env.run_checked("place-project", f"python3 -m zipfile -e {STAGED} {PROJECT} && rm {STAGED} && {COMMIT}")
        with context.step("baseline"):
            baseline = collect.baseline(env, context)
        with context.step("capability"):
            result = capability.run(env, context, request=REQUEST, timeout_seconds=TIMEOUT_SECONDS)
        with context.step("collect"):
            collect.standard(env, context, result, baseline)
        with context.step("judge"):
            judge.grade(env, context, request=REQUEST, expected=TASK / "expected.md", rubric=RUBRIC, result=result)
