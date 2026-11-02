# Evaluations

These evaluations run reality-check, or an agent CLI as a baseline, on realistic tasks and record each run's time, cost, agent trajectory, and changes, with a judge's score.
Each run puts one task in its own evaluation environment, a universe from the task's `environment/` profile.
That environment is a bare developer machine with a nested Docker daemon, built from `environment/Dockerfile`.
reality-check is installed there the way the README tells a user to, from this checkout, which the environment serves at the repository's GitHub URL.
Then the task runs the capability, collects everything the agent did, and has a judge agent grade the result in the same environment.

```bash
uv run evaluations/run.py list
uv run evaluations/run.py run [--task <name> ...] [--capability reality-check|baseline|installed]
    [--agent-provider copilot] [--model <model> ...] [--reasoning-effort high]
    [--repeat 1] [--parallel 1] [--max-parallel N] [--keep]
    [--judge-agent-provider copilot] [--judge-model <model>] [--judge-reasoning-effort high] [--judge-timeout-seconds 1800]
uv run evaluations/run.py waiting [BATCH]
uv run evaluations/run.py stop <run> [--batch BATCH] [--force]
uv run evaluations/run.py cleanup   # destroys every evaluation environment, including ones a killed batch left
```

No `--task` runs every task. Tasks always run at the same time as each other. The runs of one task, its models x repeats, run one at a time; `--parallel` sets how many run at the same time. `--max-parallel` caps the runs of the whole batch at the same time; without it there is no cap.

`--capability baseline` gives each task's request, with `Target: <target>` added when the task has one, to the agent provider's own CLI instead of reality-check, with no approvals, in `~/project`, with the task's timeout. Nothing of reality-check is installed before it, and the judge and rubric are the same, so the scores compare. The CLI is the version reality-check's own runtime for the provider uses. Copilot and claude, which is Claude Code, have a baseline; another provider's is an entry in `common/baselines.py`. Every task but desktop-app-03 supports it.

`--capability installed` gives the same request to the same CLI, with reality-check installed as a user has it: copilot's prerequisites and reality-check with the copilot extra, so its checks run on copilot whatever the CLI, then the CLI, then the skill copied to where the CLI loads a user's skills, `~/.agents/skills/reality-check` for Copilot and `~/.claude/skills/reality-check` for Claude Code. The agent decides whether to use reality-check, and the run is never stopped when it does. Only the `trigger-` tasks support it: they ask whether it reaches for reality-check when it should and runs no check when it should not, with the baseline as the control.

An agent can leave a background process, such as `reality-check app`, that keeps its CLI running until the task's timeout. `run.py waiting` shows, for each running baseline or installed run, whether its agent has ended its turn and what still runs under its CLI. `run.py stop <run>` then writes the stop to the run's `stopped.json` and sends SIGTERM to the CLI alone, never the processes under it. The capability time ends at the agent's last event.

Needs Docker on the host and the credentials of each agent provider used: for copilot, `GH_TOKEN` or `gh auth login`; for amplifier-agent and codex, `OPENAI_API_KEY`; for claude, `ANTHROPIC_API_KEY`. An installed run also needs copilot's, for reality-check's checks.

## Layout

```text
run.py              list, run, waiting, stop, cleanup
environment/        the common developer machine; task profiles build their twin from it
common/             optional helpers for tasks
data/               what tasks share, used as it is
  github-desktop/   the twin the desktop-app tasks build: a Linux desktop with GitHub Desktop and a repository in progress
  todo-app.zip      the small todo web app the trigger tasks place in ~/project
tasks/<name>/
  task.py           the whole task
  expected.md       the answer key
  environment/      the task's profile, and anything it builds
  ...               whatever else the task uses
runs/               gitignored
```

## Tasks

A task is `tasks/<name>/task.py`, which defines:

```python
DESCRIPTION: str                       # what the task is and how it is set up, for a person reading its results
def run(context: RunContext) -> None:  # one run, start to end, including any build or cache it needs
CAPABILITIES: tuple[Capability, ...]   # optional: the capabilities it supports, every one when omitted
```

A batch skips the tasks that do not support its capability, and says so.

`run.py` makes each run's directory, keeps `run.json` current, records a failure in `logs/harness-error.txt`, destroys running environments on Ctrl+C, and writes `batch.json`. Everything else is the task's.

- A task is the code in its directory. It does what its scenario needs, in the way that suits it.
- `common/` is a set of helpers, not a framework. A task calls a helper when the helper fits. When it does not, the task copies the code into its own directory and changes it there, or writes its own. Repeated code across tasks is fine.
- A change to `common/` is made only when it is right for every task that uses it. A task never bends its scenario to fit a helper.
- Caching and image builds belong to the task. A task that keeps a cache on the host keeps it in a gitignored `.cache/` in its directory. A task run with `--parallel` above 1 makes its builds safe for that itself.
- A task's profile is named `reality-check-evaluation-<name>`, so `cleanup` finds what it launched.
- `expected.md` and the rubric never enter the environment before the capability has finished. Nothing of the evaluation's own enters it before then either: `collect.baseline`'s data is kept on the host and the capability's events are read from its stdout.

`tasks/excalidraw-01/task.py` is a complete task that uses every helper:

1. `environment.launch`: start the task's evaluation environment, and destroy it at the end unless the run has `--keep`.
2. `install.setup`: install what the run's capability needs, as a user does: the agent provider's prerequisites, then reality-check from this checkout, with computer use when the task asks; for a baseline, only the provider's CLI.
3. Place the task's files in `~/project` and its images in the nested Docker daemon.
4. `collect.baseline`: record the time and the installed packages. The host keeps this data.
5. `capability.run`: run the capability in `~/project`. The host reads its events from stdout.
6. `collect.standard`: copy what the agent did to the host: its record, session, logs, changed files, packages, and containers.
7. `judge.grade`: copy the answer key into the environment, and after a baseline, install what the judge needs. A judge agent gives each criterion a score from 0 to 100, and the score is their weighted mean. Facts the task collected itself reach the judge as `materials`.

## Runs

`runs/` is gitignored. A batch is `runs/<time>-<id>/` with `batch.json` and one directory per run, `<task>-<provider>-<model>-<repeat>`, or `<task>-<capability>-<provider>-<model>-<repeat>` for a baseline or installed run. Each run directory has:

```
run.json          spec, status, step timings, capability wall clock, usage and cost as the provider reports it, score;
                  in an installed run, `usage.capability` is the agent's own and `usage.agent_checks` its reality-check checks'
report.md         the capability's report; for a baseline, the agent's last message
stopped.json      when `run.py stop` stopped the CLI: by whom, when, how long the agent had been idle, and what ran under it
grade.json        the judge's score, reason, and files for each criterion
events.jsonl      the capability's events; for a baseline, the CLI's JSON output
check/            reality-check's own record, evidence included; a baseline has none
checks/           in an installed run, the record of each check the agent ran with reality-check itself
session/          the agent provider's native session, from check/session/, or from the provider's own folder for a baseline or a check resumed from one made before sessions were kept in the record
changes.json      every file made or changed in the environment; changes/ holds copies of the small ones
installed.diff    packages installed, from packages/before and packages/after
logs/             setup and step logs, the provider's logs, nested containers, DTU state, the nested daemon
judge/            the judge's config, events, result, and session
```

A task adds its own files beside these.
