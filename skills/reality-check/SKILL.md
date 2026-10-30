---
name: reality-check
description: >-
  Checks that an app works the way a real user would experience it, on your machine, in a Digital Twin Universe, or in one it sets up for you, and returns evidence for every finding. Use after an agent builds a feature or fix, when passing tests are not enough evidence that a user can do what they came to do. Drive it from the command line as `reality-check`, or from Python through
  `reality_check.lib`. Triggers on "reality-check".
license: MIT
metadata:
  repository: https://github.com/microsoft/amplifier-smart-tool-reality-check
---

# Using reality-check

Checks that an app works the way a real user would experience it, on your machine, in a Digital Twin Universe, or in one it sets up for you, and returns evidence for every finding.

## Install

```bash
# as a CLI, choosing the agent provider(s) you want
uv tool install "reality-check[all | copilot | amplifier-agent | codex | claude] @ git+https://github.com/microsoft/amplifier-smart-tool-reality-check"

# as a library, from another project
uv add "reality-check[all] @ git+https://github.com/microsoft/amplifier-smart-tool-reality-check"

# once, without installing
uvx --from "reality-check[all] @ git+https://github.com/microsoft/amplifier-smart-tool-reality-check" reality-check --help

# once, to check desktop apps
reality-check install-computer-use

# once, to show checks inline: register `reality-check mcp` as a stdio MCP server in the
# client, then reload its MCP servers. `reality-check mcp --help` has the details.
```
## Use it

Run `reality-check --help`. It prints the tool's skill: when to use it, every capability, sharp
edges, and which files to read. Follow it. Then read the capability's own skill with
`reality-check <command> --help` before calling it: it carries the arguments, a worked
invocation, the result, and the failures. Never work from memory.

To show the user their checks, call the MCP tool `open_app` with the check's ID. Hosts that
render MCP Apps show it inline; the rest get a URL to give the user as a browser view. If
`open_app` is not among your tools, the MCP server is not registered or the host has not reloaded
it: `reality-check mcp --help` says how to register it. Without it, start
`reality-check app` in the background, since it serves until stopped, and give them the URL it prints.
