# Changelog

## Unreleased

## 0.9.2 (2026-11-14)

- `check-software` accepts an optional caller-generated request key. Repeating the same submission recovers its existing check after a lost reply or caller restart, without starting another agent. A changed request under the same key is refused; a crashed or unconfirmed check is never restarted by recovery.

## 0.9.1 (2026-11-12)

- The checking agent's prompt states the machine's CPUs, free memory, and room for more processes and threads. Also added instructions to be more aware of resource usage, particularly when running in parallel.
- When a check's agent fails, `agent-failed` now gives its last message, its session, its evidence so far, and the command to resume, and writes no `report.md`.
- On the `claude` agent provider, usage counts each model call, including calls made before a crash, which are marked incomplete.
- When a check ends, however it ends, it closes the browser sessions its agent opened and stops the processes its agent left running; with `--keep-running` it only lists the processes. The check's `cleanup.json` records both and anything that could not be cleaned up.
- A checks directory, such as the default `.agents/reality-check`, gets a `.gitignore` that keeps its checks out of git when it has none and holds nothing but checks.

## 0.9.0 (2026-11-09)

- The skill and `--help` tell callers to register `reality-check mcp` on install and update, but only in hosts that render MCP Apps. `reality-check mcp --help` has steps for Codex Desktop and Amplifier Unified.
- The output of `check-software` should include what the check did not cover. Then, next steps are written so the calling agent can either continue with those things that were not covered or ask the user if they want to do them.
- Checks now have no timeout by default. `--timeout-seconds` must be at least 1 when given, and `DEFAULT_TIMEOUT_SECONDS` is removed.
- `check-software` will punt back requests to write, fix, run the project's own tests, to be a release gate, etc.
- `check-software` is encouraged to use what the project already has to start and drive the app, such as its start scripts, seed data, test accounts, Digital Twin Universe profile, and end-to-end tests. `check-software --help` asks callers to name them in the request.

## 0.8.1 (2026-11-06)

- On Linux arm64, `reality-check install --component browser` downloads a pinned Chrome for Testing and installs Chromium's system libraries when running as root or sudo needs no password.
- When agent-browser's default socket path would be too long for its sessions, every agent-browser process gets a private `AGENT_BROWSER_SOCKET_DIR` under `/tmp`.
- An agent-browser daemon that does not start now fails the browser install with `browser-daemon-failed` rather than a browser download that cannot fix it.

## 0.8.0 (2026-11-04)

- Checks run with `medium` reasoning effort when none is given, rather than `high`, on every agent provider.
- A new check's agent gets the five newest checks in its checks directory, each with its state and the start of its request, and starts from one that asked for something similar.
- The checking agent is encouraged to checks independent items in parallel, through sub-agents or within one agent.
- The checking agent is encouraged to writes scripts for flows, keeps them in the check's evidence folder
- `reality-check --help` and `check-software --help` now say how to manage the time and cost of checks
- `gpt-6.1-terra` and Copilot Fusion are now supported for their respective providers.

## 0.7.1 (2026-11-03)

- Initial tag.
