---
name: reality-check
description: >-
  Checks that an app works the way a real user would experience it and returns evidence for every finding. Drive it from the command line as `reality-check`, or from Python through `reality_check.lib`.
  Use whenever a fix or capability needs to be validated: once you have fixed a bug, or built or changed a feature, run a check of what changed before you report the work as done, so the report says what a user can actually do, not only what the code or tests suggest.
  Also use when asked to check, verify, or make sure an app works, and when the user mentions "reality check" directly.
license: MIT
metadata:
  repository: https://github.com/microsoft/amplifier-smart-tool-reality-check
---

# Using reality-check

Checks that an app works the way a real user would experience it, on your machine, in a Digital Twin Universe, or in one it sets up for you, and returns evidence for every finding.

## Install

```bash
# as a CLI, choosing the agent provider(s) you want
uv tool install "reality-check[all | copilot | amplifier-agent | codex | claude] @ git+https://github.com/microsoft/amplifier-smart-tool-reality-check@v0.9.2"

# as a library, from another project
uv add "reality-check[all] @ git+https://github.com/microsoft/amplifier-smart-tool-reality-check@v0.9.2"

# once, without installing
uvx --from "reality-check[all] @ git+https://github.com/microsoft/amplifier-smart-tool-reality-check@v0.9.2" reality-check --help

# once, to give checks everything they can use
reality-check install

# once, if the host renders MCP Apps: register `reality-check mcp` as its MCP server, so checks
# show in the host. `reality-check mcp --help` has the details.
```
## Use it

Run `reality-check --help`.
It prints the tool's skill: when to use it, every capability, which files to read, etc.
Read each capability's own skill with `reality-check <command> --help` before calling it:
it carries the arguments, a worked invocation, the result, etc.
The main smart capability is `reality-check check-software --request "Check that a new user can sign up and send a message"`,
which uses an Agent SDK like Copilot SDK or Amplifier Agent to validate software.
Checks take at least a few minutes, with more complex or generic asks possibly taking much longer. `reality-check check-software --help` has the details.

Show the user their checks in the best way the host allows:

1. The host renders MCP Apps, such as Codex Desktop or Amplifier Unified: call the MCP tool `open_app` with the check's ID.
   If the server is not registered or not loaded yet, register it as `reality-check mcp --help` says,
   use the next way for now, and tell the user the app shows in the host after the host reloads its MCP servers.
2. The host can open a page for the user, in its own browser or preview or in the user's browser:
   start `reality-check app` in the background, since it serves until stopped, and open the URL it prints.
3. Otherwise, start `reality-check app` the same way and give the user its URL.

Do not register the MCP server in a host that does not render MCP Apps.

## Keep it current

Keep the tool up to date for the user by default if the permission mode allows it.
Each release is a `v<version>` tag and an install stays on its tag, so `uv tool upgrade` does not move it.
Find the newest release:

```bash
git ls-remote --tags --refs --sort=-v:refname https://github.com/microsoft/amplifier-smart-tool-reality-check "v*" | head -1
```

If it is newer than `reality-check --version`, run the install command again with that tag and the extras
`uv tool list --show-extras` reports. For a library, run `uv add` again with the new tag.
Update the skill with `npx skills add microsoft/amplifier-smart-tool-reality-check#<tag>`, adding `-g` for global installs.
In a host that renders MCP Apps, also make sure `reality-check mcp` is registered, whether or not there was a newer release.
Do not try to get around restrictions or operate against the user's preferences to update tools (or skills).
