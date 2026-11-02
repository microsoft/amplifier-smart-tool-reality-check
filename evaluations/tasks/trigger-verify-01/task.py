"""A todo web app in the user's project and a request to check it, to see whether the agent reaches for reality-check."""

from pathlib import Path

from common import capability, collect, environment, install, judge
from common.context import Criterion, RunContext
from common.environment import PROJECT

TASK = Path(__file__).resolve().parent
TODO_APP = TASK.parents[1] / "data" / "todo-app.zip"
DESCRIPTION = (
    "evaluations/data/todo-app.zip, a small todo web app on Python's standard library, placed in ~/project as a repository of "
    "one commit and started with `python3 app.py`. It has one bug: with the Active or Completed filter on, Delete "
    "removes the todo at the same position in the whole list, not the one clicked. The request asks for a check that "
    "people can use the app, without naming reality-check. In an installed run, reality-check's skill and CLI are "
    "there as a user would have them, and the agent should reach for them on its own and tell the user what they "
    "found; the baseline is the control, with neither."
)
# What it evaluates is whether the agent chooses reality-check, which a run of reality-check itself takes as given.
CAPABILITIES = ("installed", "baseline")
REQUEST = "Can you make sure people can add, complete, filter, and delete todos in this app?"
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
