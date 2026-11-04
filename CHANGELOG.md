# Changelog

## Unreleased

## 0.8.0 (2026-11-04)

- Checks run with `medium` reasoning effort when none is given, rather than `high`, on every agent provider.
- A new check's agent gets the five newest checks in its checks directory, each with its state and the start of its request, and starts from one that asked for something similar.
- The checking agent is encouraged to checks independent items in parallel, through sub-agents or within one agent.
- The checking agent is encouraged to writes scripts for flows, keeps them in the check's evidence folder
- `reality-check --help` and `check-software --help` now say how to manage the time and cost of checks
- `gpt-6.1-terra` and Copilot Fusion are now supported for their respective providers.

## 0.7.1 (2026-11-03)

- Initial tag.
