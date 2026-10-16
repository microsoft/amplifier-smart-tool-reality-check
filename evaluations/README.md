# Evaluations

This directory contains evaluations aimed at evaluating smart-capabilities and reporting/analyzing how each of them do. It contains a set of high-fidelity evaluation tasks. We then capture key metrics like run time, cost, as well as agent trajectories and what was done within the evaluation environment.
Each run puts one task in its own evaluation environment, a universe from `environment/`. 
That environment is a bare developer machine with a nested Docker daemon. 
The harness installs reality-check there the way the README tells a user to, from this checkout, which the environment serves at the repository's GitHub URL. 
Then it runs the task's capability, collects everything the agent did, and has a judge agent grade the result in the same environment.

```bash
uv run evaluations/run.py run --task excalidraw-01 --model gpt-6.1-sol --repeat 3 --parallel 3
uv run evaluations/run.py cleanup   # destroys every evaluation environment, including ones a killed batch left
```

Needs Docker on the host and the credentials of each agent provider used: for copilot, `GH_TOKEN` or `gh auth login`.

## How a run works

First, the host builds the images of each task. Then each run does the steps below in its own environment. `--parallel` sets how many runs occur at the same time.

1. Start an evaluation environment from `environment/`.
2. Install what the agent provider needs. Then install reality-check from this checkout, as a user does.
3. Copy the task files into `~/project`. Load the task images into the Docker daemon of the environment.
4. Record the time and the installed packages. The host keeps this data.
5. Run the capability in `~/project`. The host reads its events from stdout.
6. Copy what the agent did to the host: its record, session, logs, changed files, packages, and containers.
7. Copy the answer key into the environment. A judge agent gives each criterion a score from 0 to 100.
8. Destroy the environment, unless the run has `--keep`.
9. Dashboards/reports are only created on an adhoc basis.

## Tasks

A task is a directory under `tasks/` with a `task.yaml` and an `expected.md`. `expected.md` and the rubric never enter the environment before the capability has finished. Nothing of the harness's own enters it before then either: the baseline is kept on the host and the capability's events are read from its stdout.

```yaml
capability: check-software
description: what the task is and how it is set up, for a person reading its results
request: what the user asks, in their words
target: .agents/digital-twin-universe/excalidraw   # optional
files:                                             # task directory path -> path in the user's project
  profile: .agents/digital-twin-universe/excalidraw
images:                                            # built on the host and loaded into the nested daemon, so the build never enters the environment
  - build: image
    tag: excalidraw-app:0.18.1
timeout_seconds: 3600
rubric:                                            # each criterion is scored 0 to 100; the score is their weighted mean
  found-the-defect:
    weight: 4
    description: ...
```

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
