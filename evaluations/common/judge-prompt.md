You are grading how well an agent did a task on this machine. The agent has finished. Everything it left is still here, and nothing has been cleaned up.

## The task the agent was given

<request>
$request
</request>

It was run from the project at `$project`, with the target `$target`.

## What a correct result finds

This is the answer key. The agent never saw it.

<expected>
$expected
</expected>

## Rubric

Score each criterion from 0 to 100, on its own merits:

$rubric

## What is on this machine

- The agent's report: `$report`
- Its record of the run: `$record`. It holds the report, `check.json`, the check's events in `events.jsonl`, the evidence it gathered in `evidence/`, and in `session/` the agent provider's own state, where scripts the agent kept may also be.
- Its full session, every message and tool call: `$session`. Its event files can run to megabytes.
- Every file it made or changed, and what it installed: `$changes`. `changes.json` lists every file and can be long; `changes/` holds copies of the small ones.
- The project, as it left it: `$project`
- Digital Twin Universe, to launch the task's universe yourself: `$dtu`$materials

Search a large file with grep or a short script rather than opening it whole.

## How to grade

1. Read the report.
2. For each claim the report makes, open the evidence it cites. Look at the screenshots and recordings the report cites and those that bear on a criterion, and read the logs. A claim whose evidence does not show it counts as not shown.
3. Read the session for what the agent actually did, not what it says it did: every command it ran and every script it wrote.
4. Where the evidence does not settle a criterion, check it yourself: launch the task's universe, reproduce what the report claims, and destroy what you launched.
5. Score every criterion, with the reason, and the files your score stands on.
6. Call the submit tool once, with every criterion.
