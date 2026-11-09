# Changelog

## Unreleased

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
