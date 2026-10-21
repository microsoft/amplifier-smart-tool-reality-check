# Evaluations

This directory contains evaluations aimed at evaluating smart-capabilities and reporting/analyzing how each of them do. It contains a set of high-fidelity evaluation tasks. We then capture key metrics like run time, cost, as well as agent trajectories and what was done within the evaluation environment.
Each run puts one task in its own evaluation environment, a universe from the task's `environment/` profile.
That environment is a bare developer machine with a nested Docker daemon, built from `environment/Dockerfile`.
reality-check is installed there the way the README tells a user to, from this checkout, which the environment serves at the repository's GitHub URL.
Then the task runs the capability, collects everything the agent did, and has a judge agent grade the result in the same environment.

```bash
uv run evaluations/run.py list
uv run evaluations/run.py run [--task <name> ...] [--capability reality-check|baseline] [--model <model> ...] [--repeat 1] [--parallel 1] [--max-parallel N] [--keep] [judge options]
uv run evaluations/run.py cleanup   # destroys every evaluation environment, including ones a killed batch left
```

No `--task` runs every task. Tasks always run at the same time as each other. The runs of one task, its models x repeats, run one at a time; `--parallel` sets how many run at the same time. `--max-parallel` caps the runs of the whole batch at the same time; without it there is no cap.

`--capability baseline` gives each task's request, with `Target: <target>` added when the task has one, to the agent provider's own CLI instead of reality-check, with no approvals, in `~/project`, with the task's timeout. Nothing of reality-check is installed before it, and the judge and rubric are the same, so the scores compare. The CLI is the version reality-check's own runtime for the provider uses. Copilot has a baseline; another provider's is an entry in `common/baselines.py`. Every task but desktop-app-03 supports it.

Needs Docker on the host and the credentials of each agent provider used: for copilot, `GH_TOKEN` or `gh auth login`; for amplifier-agent and codex, `OPENAI_API_KEY`; for claude, `ANTHROPIC_API_KEY`.

## Layout

```text
run.py              list, run, cleanup
environment/        the common developer machine; task profiles build their twin from it
common/             optional helpers for tasks
github-desktop/     the twin the desktop-app tasks build: a Linux desktop with GitHub Desktop and a repository in progress
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

`runs/` is gitignored. A batch is `runs/<time>-<id>/` with `batch.json` and one directory per run, `<task>-<provider>-<model>-<repeat>`, or `<task>-baseline-<provider>-<model>-<repeat>` for a baseline. Each run directory has:

```
run.json          spec, status, step timings, capability wall clock, usage and cost as the provider reports it, score
report.md         the capability's report; for a baseline, the agent's last message
grade.json        the judge's score, reason, and files for each criterion
events.jsonl      the capability's events; for a baseline, the CLI's JSON output
check/            reality-check's own record, evidence included; a baseline has none
session/          the agent provider's native session, from check/session/, or from the provider's own folder for a baseline or a check resumed from one made before sessions were kept in the record
changes.json      every file made or changed in the environment; changes/ holds copies of the small ones
installed.diff    packages installed, from packages/before and packages/after
logs/             setup and step logs, the provider's logs, nested containers, DTU state, the nested daemon
judge/            the judge's config, events, result, and session
```

A task adds its own files beside these.
