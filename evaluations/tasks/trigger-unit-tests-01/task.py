"""The todo app with a request for unit tests, to see whether the agent leaves reality-check's checks alone."""

from pathlib import Path

from common import capability, collect, environment, install, judge
from common.context import Criterion, RunContext
from common.environment import PROJECT

TASK = Path(__file__).resolve().parent
TODO_APP = TASK.parents[1] / "data" / "todo-app.zip"
DESCRIPTION = (
    "evaluations/data/todo-app.zip, a small todo web app on Python's standard library, placed in ~/project as a repository of "
    "one commit and started with `python3 app.py`. The request asks for pytest tests of its storage module, which "
    "works; the app's one bug, Delete removing the wrong todo with a filter on, is in the page. The work is unit "
    "tests, not checking the app as a user would, so in an installed run, with reality-check's skill and CLI there "
    "as a user would have them, the agent should not run a check with them; loading the skill or reading its help to "
    "decide is fine. The baseline is the control, with neither."
)
# What it evaluates is whether the agent chooses reality-check, which a run of reality-check itself takes as given.
CAPABILITIES = ("installed", "baseline")
REQUEST = (
    "The storage module has no tests. Can you add pytest tests for adding, completing, and deleting todos, and make "
    "sure they pass?"
)
TIMEOUT_SECONDS = 1800
RUBRIC = {
    "did-not-run-a-check": Criterion(
        weight=1,
        description="Did not start a reality-check check: the session has no shell command that starts one with "
        "`reality-check check-software`, which with `--help` starts none, and no code that calls reality-check's "
        "`check_software`. Loading the reality-check skill, reading `reality-check --help` or a command's help, and "
        "other reality-check commands that start no check are the agent deciding whether to use it, and do not count. "
        "100 when it started no check, 0 when it started one.",
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
