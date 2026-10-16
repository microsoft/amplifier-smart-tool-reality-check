`check-software` checks software the way a real user would. An agent investigates the request,
reaches and uses the software, gathers evidence such as screenshots, requests, console messages,
and timings, and ends with a Markdown report: a verdict per item asked about, with the evidence
files each one stands on. A check runs for minutes. It streams events while it works, can be
steered or cancelled from any process, and can be resumed with a follow-up.

A check runs longer than most shell timeouts, so start it in the background with its output in a
file, and read the file as you need:

```bash
reality-check check-software --request "Check that a new user can sign up and send a message" \
  --target http://localhost:3000 > check.jsonl 2> check.log &
tail -n 1 check.jsonl                       # the latest event; the check ended when it is finished or failed
reality-check steer-check --check-id 20261013-142501-3f9a1c --message "Use the test account in notes.md"
reality-check cancel-check --check-id 20261013-142501-3f9a1c
```

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
reality-check check-software --resume 20261013-142501-3f9a1c --request "I signed in; go on" > check.jsonl 2> check.log &
```

## Arguments

- `--request TEXT`: what to check, in plain words. Required. It may name files, read relative to
  the working directory; a Markdown file is ordinary context. On `--resume`, the next message.
- `--target TARGET`: where the software is: a URL, a universe id, a profile, a path, or a
  description. Leave it out when the request says.
- `--resume CHECK_ID`: an earlier check to continue, in the same agent session on the same agent
  provider. It must have ended `done` or `cancelled`.
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
- `--model MODEL`: the agent provider's default when omitted.
- `--reasoning-effort low|medium|high|xhigh|max`: default `medium`.
- `--timeout-seconds N`: default 3600.
- Library: `check_software(request, target=None, resume=None, previous_checks=None, ask_first="when-off",
  keep_running=False, checks_directory=Path(".agents/reality-check"), agent_provider=None,
  model=None, reasoning_effort="medium", timeout_seconds=3600, intelligence=None)`, which returns
  a `CheckRun` with `check_id`, `directory`, `events()`, `steer(message)`, `cancel()`, and
  `result()`.

## Result

Each event is one JSON line on stdout, written whole and flushed: `check_id`, `time`, `kind`,
`text`, and `data`. The kinds:

- `started`: always first; `data.directory` is the check's directory.
- `progress`: what the agent is doing, in its words.
- `tool`: a tool the agent called (`data.phase` `call`) or its result (`result`), shortened.
- `usage`: one model call's tokens in `data`, and its cost when the agent provider reports one.
- `steered`: a steering message was delivered.
- `finished`: always last when the check ends; `data` is the result.
- `failed`: always last when the check fails; `data` has `code`, `message`, and `remedy`.

A file that ends without `finished` or `failed` means the process was killed.

The result: `check_id`, `status` (`done` or `cancelled`), `session_id`, `agent_provider`,
`report` (the agent's final message, in Markdown), `directory`, and `next`, the exact command
that resumes the check. The check's directory, `<checks-directory>/<check_id>/`, keeps
`check.json`, `events.jsonl`, and `report.md`.

A report that says the software failed is a result: exits 0 on `done`, 1 on
`cancelled` or a failure. Ctrl+C, SIGTERM, and closing the console cancel the check; its session
can still be resumed.
