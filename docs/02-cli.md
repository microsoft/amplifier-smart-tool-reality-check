# CLI Reference

The CLI is a thin wrapper over the [library](01-library.md): one command per capability, taking the same arguments under the same names, and doing nothing the library does not. 
What each argument means and what a capability returns or raises is documented there. This page covers only what the CLI adds: the invocation shape, and what reaches stdout, stderr, and the exit code.

Results go to stdout and diagnostics to stderr. A failure the library can name prints its message to stderr and exits 1; a bad invocation exits 2.

`reality-check --version` (or `-V`) prints the distribution name and its installed version.

## Help

```
reality-check -h                 terse summary for a person: the commands, a line each
reality-check --help             the tool's skill, written for an agent driving it
reality-check <command> -h       terse summary of one command: its arguments and defaults
reality-check <command> --help   that command's skill, written for an agent about to call it
```

`--help` on the tool prints what `lib.skill()` returns and on a command what `lib.skill("<command>")` returns; the CLI adds nothing of its own.

## reality-check manifest

```bash
reality-check manifest
```

`lib.load_manifest()`, printed as JSON.

## reality-check check-software

```bash
reality-check check-software --request TEXT [--target TARGET] [--resume CHECK_ID] [--previous-checks PATH ...]
                             [--ask-first when-off|always|never] [--keep-running] [--checks-directory .agents/reality-check]
                             [--agent-provider copilot|amplifier-agent|codex|claude] [--model MODEL]
                             [--reasoning-effort low|medium|high|xhigh|max] [--timeout-seconds 3600, 0 for no limit]
                             [--image PATH ...] [--origin unknown] [--detach]
```

`lib.check_software()`, run to the end. Each `CheckEvent` is printed to stdout as one JSON line as it happens, in the short form `schemas.brief` makes: no `usage` events, a `tool` event without the `arguments`, `result`, and `detailed_result`, and every other string past 500 characters cut, but the report, ending with the line of `events.jsonl` that keeps it whole.

With `--detach`, the check runs in a process of its own: the command prints the `started` event and exits 0, or exits 1 with why the check did not start. An agent then follows it with `read-check-activity --after-event` and the last event `id` it read:

```bash
reality-check check-software --request "Check that a new user can sign up" --target http://localhost:3000 --detach
```

Without it, an agent starts the check in the background with its output in a file, and reads the file as it needs:

```bash
reality-check check-software --request "Check that a new user can sign up" --target http://localhost:3000 > check.jsonl 2> check.log &
```

The output is made for that:

- Every event is one line of UTF-8 JSON, written in one call and flushed at once, so a reader of the file never sees half a line.
- The first line is always `started`, with the `check_id`, the check's directory, and its `files`, each with when to read it.
- The last line is always `finished`, carrying the `CheckResult`, or `failed`, carrying the error. A file that ends without one means the process was killed.

Ctrl+C, SIGTERM, and closing the console all cancel the check the same way; its session can still be resumed. Exits 0 when the check ends `done`, and 1 when it is cancelled, times out, or fails. What the report says about the software never changes the exit code.

## reality-check steer-check

```bash
reality-check steer-check --check-id CHECK_ID --message TEXT [--checks-directory .agents/reality-check] [--origin unknown]
```

`lib.steer_check()`. Prints nothing and exits 0 once the message is written; the check's events show when it is delivered.

## reality-check cancel-check

```bash
reality-check cancel-check --check-id CHECK_ID [--checks-directory .agents/reality-check]
```

`lib.cancel_check()`. Prints nothing and exits 0 once the cancel is written; the check's last event shows when it has stopped.

## reality-check read-check-activity

```bash
reality-check read-check-activity --check-id CHECK_ID [--after-event N] [--before-event N] [--tail-events N] [--no-truncate]
                                  [--checks-directory .agents/reality-check]
```

`lib.read_check_activity()`, printed as one line of JSON. `--no-truncate` is `truncate=False`.

## reality-check list-checks

```bash
reality-check list-checks [--checks-directory PATH]
```

`lib.list_checks()`, printed as a JSON list. Without `--checks-directory`, every registered project's checks.

## reality-check read-check

```bash
reality-check read-check --check-id CHECK_ID [--checks-directory .agents/reality-check]
```

`lib.read_check()`, printed as JSON.

## reality-check app

```bash
reality-check app [--port N] [--directory PATH]
```

`lib.app_server(directory).open(port)`. Prints the app's URL, `http://127.0.0.1:<port>`, and serves until Ctrl+C. A free port is chosen when `--port` is omitted; a held one exits 1.

## reality-check mcp

```bash
reality-check mcp [--directory PATH]
```

Serves `lib.app_server(directory).server` on stdio, for an MCP client that launches it:

```json
{ "mcpServers": { "reality-check": { "command": "reality-check", "args": ["mcp"] } } }
```

It writes only MCP messages to stdout, and exits when the client disconnects.

## reality-check list-intelligence-models

```bash
reality-check list-intelligence-models
```

`lib.list_intelligence_models()`, printed as JSON.

## reality-check install-computer-use

```bash
reality-check install-computer-use
```

`lib.install_computer_use()`, printed as JSON.

## Skills for checking software

```bash
reality-check reaching-software-skill
reality-check using-software-skill
reality-check using-computer-use-skill
reality-check gathering-evidence-skill
```

`lib.<name>_skill()`, printed as text, the same way `--help` prints a capability's skill.

## Adding a command

Each command gets a section here: the invocation shape with its options and defaults, which library function it calls, and what it prints and exits with. Argument meanings belong in the library reference, not here.
