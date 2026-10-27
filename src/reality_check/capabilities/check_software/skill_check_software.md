`check-software` checks software the way a real user would. An agent investigates the request,
reaches and uses the software, gathers evidence such as screenshots, requests, console messages,
and timings, and ends with a Markdown report: a verdict per item asked about, with the evidence
files each one stands on. A check runs for minutes. It streams events while it works, can be
steered or cancelled from any process, and can be resumed with a follow-up.

The report starts with a short summary, then Needs attention, Observations, What was checked,
Next steps, and Run details. Relevant screenshots are embedded beside findings. Next steps
guide the calling agent on possible actions and rechecks, within the caller's authorized scope.

Use it to check a feature or fix as a user would, or to find out why a scripted test fails. Do
not use it as a release gate or a CI step, or to run the same assertions again on each change.
Scripted tests are faster and cheaper there. Say that to the caller instead of starting a check.

A check runs longer than most shell timeouts, so start it with `--detach`: it runs in a process of
its own, and the command prints the `started` event and exits. Follow it with `read-check-activity`:

```bash
reality-check check-software --request "Check that a new user can sign up and send a message" \
  --target http://localhost:3000 --detach --origin claude-code:<session id>
reality-check read-check-activity --check-id 20261013-142501-3f9a1c   # again with --after <cursor> until ended
reality-check steer-check --check-id 20261013-142501-3f9a1c --message "Use the test account in notes.md"
reality-check cancel-check --check-id 20261013-142501-3f9a1c
```

Without `--detach`, the command runs the check to its end and prints every event; run it in the
background with its output in a file (`> check.jsonl 2> check.log &`) and read the file.

```python
from reality_check.lib import check_software

run = await check_software("Check that a new user can sign up", target="http://localhost:3000")
async for event in run.events():
    print(event.kind, event.text)
result = await run.result()
result.status, result.report, result.next
```

When the check stops to ask, its report says what it needs. Answer with a new check that
resumes it, which continues the same agent session:

```bash
reality-check check-software --resume 20261013-142501-3f9a1c --request "I signed in; go on" --detach
```

A check whose process died, a `crashed` state in `read-check-activity`, is resumed the same way.

Desktop apps need computer use. When it is not installed, the check's agent installs it with
`reality-check install-computer-use` and goes on; when the install fails, the agent says why.

## Arguments

- `--request TEXT`: what to check, in plain words. Required. It may name files, read relative to
  the working directory; a Markdown file is ordinary context. On `--resume`, the next message.
- `--target TARGET`: where the software is: a URL, a universe id, a profile, a path, or a
  description. Leave it out when the request says.
- `--resume CHECK_ID`: an earlier check to continue, in the same agent session on the same agent
  provider. It must have ended `done`, `cancelled`, or `timed-out`.
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

Each event is one JSON line on stdout, written whole and flushed: `check_id`, `time`, `kind`,
`text`, and `data`. The kinds:

- `started`: always first; `data` has the check's `directory` and the whole request.
- `progress`: what the agent is doing, in its words.
- `reasoning`: what the agent thought, when the model thinks.
- `tool`: a tool the agent called (`data.phase` `call`) or its result (`result`), shortened on
  stdout; `read-check-activity --tool-call-id` has it in full.
- `usage`: one model call's tokens in `data`, with `fresh_input_tokens`, and what it is billed in
  `billing` when the agent provider reports it.
- `steered`: a steering message was delivered.
- `finished`: always last when the check ends; `data` is the result.
- `failed`: always last when the check fails; `data` has `code`, `message`, and `remedy`.

A file that ends without `finished` or `failed` means the process was killed.

The result: `check_id`, `status` (`done`, `cancelled`, or `timed-out`), `session_id`,
`agent_provider`, `report` (the agent's final message, in Markdown), `directory`, `next`, the exact
command that resumes the check, `timeout_seconds`, `elapsed_seconds`, and `usage`: `model_calls`,
`fresh_input_tokens`, `cache_read_tokens`, `cache_write_tokens`, `output_tokens`,
`reasoning_tokens`, and `billing` by unit, such as `USD` or `AIU`. A check that times out ends with
`failed`, code `check-timeout`, whose `data.result` is the result. The check's directory, `<checks-directory>/<check_id>/`, keeps
`check.json`, `events.jsonl`, `report.md`, the agent's `session/`, the `images/` it was shown, and,
when detached, `process.log`.

A report that says the software failed is a result: exits 0 on `done`, 1 on
`cancelled`, `timed-out`, or a failure. Ctrl+C, SIGTERM, and closing the console cancel the check; its session
can still be resumed.
