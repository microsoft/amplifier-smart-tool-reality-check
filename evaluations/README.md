# Evaluations

This directory contains evaluations aimed at evaluating smart-capabilities and reporting/analyzing how each of them do. It contains a set of high-fidelity evaluation tasks. We then capture key metrics like run time, cost, as well as agent trajectories and what was done within the evaluation environment.
Each run puts one task in its own evaluation environment, a universe from the task's `environment/` profile.
That environment is a bare developer machine with a nested Docker daemon, built from `environment/Dockerfile`.
reality-check is installed there the way the README tells a user to, from this checkout, which the environment serves at the repository's GitHub URL.
Then the task runs the capability, collects everything the agent did, and has a judge agent grade the result in the same environment.

```bash
uv run evaluations/run.py list
uv run evaluations/run.py run [--task <name> ...] [--model <model> ...] [--repeat 1] [--parallel 1] [--keep] [judge options]
uv run evaluations/run.py cleanup   # destroys every evaluation environment, including ones a killed batch left
```

No `--task` runs every task. Tasks always run at the same time as each other. The runs of one task, its models x repeats, run one at a time; `--parallel` sets how many run at the same time.

Needs Docker on the host and the credentials of each agent provider used: for copilot, `GH_TOKEN` or `gh auth login`.

## Layout

```text
run.py              list, run, cleanup
environment/        the common developer machine; task profiles build their twin from it
common/             optional helpers for tasks
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
```

`run.py` makes each run's directory, keeps `run.json` current, records a failure in `logs/harness-error.txt`, destroys running environments on Ctrl+C, and writes `batch.json`. Everything else is the task's.

- A task is the code in its directory. It does what its scenario needs, in the way that suits it.
- `common/` is a set of helpers, not a framework. A task calls a helper when the helper fits. When it does not, the task copies the code into its own directory and changes it there, or writes its own. Repeated code across tasks is fine.
- A change to `common/` is made only when it is right for every task that uses it. A task never bends its scenario to fit a helper.
- Caching and image builds belong to the task. A task that keeps a cache on the host keeps it in a gitignored `.cache/` in its directory. A task run with `--parallel` above 1 makes its builds safe for that itself.
- A task's profile is named `reality-check-evaluation-<name>`, so `cleanup` finds what it launched.
- `expected.md` and the rubric never enter the environment before the capability has finished. Nothing of the evaluation's own enters it before then either: the baseline is kept on the host and the capability's events are read from its stdout.

`tasks/excalidraw-01/task.py` is a complete task that uses every helper:

1. `environment.launch`: start the task's evaluation environment, and destroy it at the end unless the run has `--keep`.
2. `install.provider_and_reality_check`: install what the agent provider needs, then reality-check from this checkout, as a user does.
3. Place the task's files in `~/project` and its images in the nested Docker daemon.
4. `collect.baseline`: record the time and the installed packages. The host keeps this data.
5. `capability.check_software`: run the capability in `~/project`. The host reads its events from stdout.
6. `collect.standard`: copy what the agent did to the host: its record, session, logs, changed files, packages, and containers.
7. `judge.grade`: copy the answer key into the environment. A judge agent gives each criterion a score from 0 to 100, and the score is their weighted mean. Facts the task collected itself reach the judge as `materials`.

## Runs

`runs/` is gitignored. A batch is `runs/<time>-<id>/` with `batch.json` and one directory per run. Each run directory has:

```
run.json          spec, status, step timings, capability wall clock, usage and cost as the provider reports it, score
report.md         the capability's report
grade.json        the judge's score, reason, and files for each criterion
events.jsonl      the capability's events
check/            the capability's own record, evidence included
session/          the agent provider's native session
changes.json      every file made or changed in the environment; changes/ holds copies of the small ones
installed.diff    packages installed, from packages/before and packages/after
logs/             setup and step logs, the provider's logs, nested containers, DTU state, the nested daemon
judge/            the judge's config, events, result, and session
```

A task adds its own files beside these.
