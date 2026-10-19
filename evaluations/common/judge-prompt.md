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
- Its record of the run, with the evidence it gathered: `$record`
- Its full session, every message and tool call: `$session`
- Every file it made or changed, and what it installed: `$changes`
- The project, as it left it: `$project`
- Digital Twin Universe, to launch the task's universe yourself: `$dtu`$materials

## How to grade

1. Read the report.
2. For each claim the report makes, open the evidence it cites. Look at every screenshot and recording, and read the logs. A claim whose evidence does not show it counts as not shown.
3. Read the session for what the agent actually did, not what it says it did.
4. Where the evidence does not settle a criterion, check it yourself: launch the task's universe, reproduce what the report claims, and destroy what you launched.
5. Score every criterion, with the reason, and the files your score stands on.
6. Call the submit tool once, with every criterion.
