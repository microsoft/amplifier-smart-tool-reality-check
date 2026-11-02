`check-software` checks software the way a real user would.
An agent investigates the request, reaches and uses the software, gathers evidence such as screenshots, requests, console messages, and timings, and ends with a Markdown report.
A check runs for minutes, often longer than an agent's shell timeout, and prints every event as it goes.

Use it to check a feature or fix as a user would, or to find out why a scripted test fails.
Do not use it as a release gate or a CI step, or to run the same assertions again on each change.
Scripted tests are faster and cheaper there. Say that to the caller instead of starting a check.

Start it with `--detach`: the check runs in a process of its own that outlives yours, and the command prints the `started` event and exits.
Follow it with `read-check-activity`, whose `--help` says how to read only what you need, and steer or cancel it from any process:

```bash
reality-check check-software --request "Check that a new user can sign up and send a message" \
  --target http://localhost:3000 --detach --origin claude-code:<session id>
reality-check read-check-activity --check-id 20261013-142501-3f9a1c --tail-events 3
reality-check read-check-activity --check-id 20261013-142501-3f9a1c --after-event 48   # again until it ends
reality-check steer-check --check-id 20261013-142501-3f9a1c --message "Use the test account in notes.md"
reality-check cancel-check --check-id 20261013-142501-3f9a1c
```

Leave out `--detach` when the check should stop when your process does, or when a script needs the exit code to say how the check ended.
check-software's stdout is every event, tens of kilobytes for a short check and far more for a long one.
That is why it is best to run it in the background with its output in a file:

```bash
reality-check check-software --request "Check that a new user can sign up" --target http://localhost:3000 \
  > check.jsonl 2> check.log &
```

A script gets the exit code with `wait $!`.

The file's first line has the `check_id`: follow the check with `read-check-activity` as above, or read only the file's new lines.
Either way, read the end: the last line is `finished`, carrying the whole report and the result, or `failed`.
A file that ends without one means the process was killed.

```python
from reality_check.lib import check_software

run = await check_software("Check that a new user can sign up", target="http://localhost:3000")
async for event in run.events():
    print(event.kind, event.text)
result = await run.result()
result.status, result.report, result.next
```

Desktop apps need computer use. When it is not installed, the check's agent installs it with
`reality-check install-computer-use` and goes on; when the install fails, the agent says why.

## Arguments

- `--request TEXT`: what to check, in plain words. Required. It may name files, read relative to
  the working directory; a Markdown file is ordinary context. On `--resume`, the next message.
- `--target TARGET`: where the software is: a URL, a universe id, a profile, a path, or a
  description. Leave it out when the request says.
- `--resume CHECK_ID`: an earlier check to continue, in the same agent session on the same agent
  provider. Any check that is not running: `done`, `cancelled`, `timed-out`, or `crashed`.
- `--previous-checks PATH`: an earlier check's directory, repeatable. The agent gets the paths,
  also on `--resume`; the request says what to do with them, such as "compare against the earlier
  check".
- `--ask-first when-off|always|never`: when the agent stops to ask before the work. `when-off`,
  the default, stops only when something seems off, such as computer use not enabled or a tester
  not installed. `always` stops and shows what it will check and how. `never` goes on as far as it
  can and notes what was off in the report.
- `--keep-running`: leave running what the check started, such as a universe, for later checks.
  Without it, the agent destroys what it launched. It never destroys what it did not start.
- `--checks-directory PATH`: where checks are kept, default `.agents/reality-check` relative to
  the working directory.
- `--agent-provider copilot|amplifier-agent|codex|claude`: the first installed when omitted,
  `copilot` first; on `--resume`, the resumed check's.
- `--model MODEL`: the agent provider's default when omitted. Only the models
  `reality-check list-intelligence-models` lists run.
- `--reasoning-effort low|medium|high|xhigh|max`: `high` when omitted, and none for a model that
  takes none, such as `auto`.
- `--timeout-seconds N`: how long the check may run, default 3600; `0` for no limit. Be generous:
  testing is slow, and a check stopped early often has no report. Give about an hour for a focused
  request, several hours for a broad one, and `0` for a long checklist. At 85% of it, the agent is
  told how much time is left and to stop testing and report.
- `--image PATH`: an image shown to the agent with the request, such as a screenshot of the bug;
  repeatable. PNG, JPEG, GIF, or WebP, on a model with `vision`.
- `--origin TEXT`: who starts the check, such as `app` or `claude-code:<session id>`, kept in
  `check.json` and on its events; default `unknown`.
- `--detach`: run the check in a process of its own that outlives this one; print the `started`
  event and exit 0, or exit 1 with why it did not start.
- Library: `check_software(request, target=None, resume=None, previous_checks=None, ask_first="when-off",
  keep_running=False, checks_directory=Path(".agents/reality-check"), agent_provider=None,
  model=None, reasoning_effort=None, timeout_seconds=3600 (None for no limit), images=None, origin="unknown",
  detach=False, intelligence=None)`, which returns a `CheckRun` with `check_id`, `directory`,
  `events()`, `steer(message)`, `cancel()`, and `result()`.

## Result

Each event is one JSON line: `id`, `check_id`, `time`, `kind`, `text`, and `data`.
The `id` is its line in the check's `events.jsonl`, which keeps every event whole and adds a `usage` event per model call.
Stdout has the short form: a string longer than 500 characters is cut and says where it is whole, such as `...[cut at 500 of 3,319 chars; full: line 64 of events.jsonl]`.
The kinds:

- `started`: always first; `data` has the check's `directory`, its request, and `files`, each path with when to read it.
- `progress`: what the agent is doing, in its words.
- `reasoning`: what the agent thought, when the model thinks.
- `tool`: a tool call (`data.phase` `call`) or its result (`result`), paired by `data.tool_call_id`; the full arguments and result are in `events.jsonl`.
- `steered`: a steering message was delivered.
- `finished`: always last when the check ends; `data` is the result.
- `failed`: always last when the check fails; `data` has `code`, `message`, and `remedy`. A timeout is `check-timeout`, with the result in `data.result`.

The result: `check_id`, `status` (`done`, `cancelled`, or `timed-out`), `session_id`, `agent_provider`, `report` (Markdown, never cut), `directory`, `next` (the exact command that resumes the check), `timeout_seconds`, `elapsed_seconds`, and `usage` (tokens and billing, summed over model calls).

Exits 0 on `done`, even when the report says the software failed, and 1 on `cancelled`, `timed-out`, or a failure.
Without `--detach`, Ctrl+C, SIGTERM, and closing the console cancel the check; its session can still be resumed.
A detached check does not get them: stop it with `cancel-check`.

## After the check

The report starts with a short summary, then Needs attention, Observations, What was checked, Next steps, and Run details.
It gives a verdict per item asked about, pass, fail, or not checked, with the evidence files each stands on, relative to the check's directory.
Not checked is never a pass.
Tell the user what the check found, not only what you changed: the verdicts, each failure's step, action, and what was recorded, and the report's path.
Next steps suggest investigations, fixes, and rechecks; act on them within the caller's authorized scope, and ask before anything that needs further approval.

When the check stopped to ask, its report says what it needs.
Answer it, or check again after a fix, with the command the result's `next` names; it continues the same agent session:

```bash
reality-check check-software --resume 20261013-142501-3f9a1c --request "I signed in; go on" --detach
```

`list-checks` finds an earlier check without its ID.
