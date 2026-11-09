---
smart_tool_format: 1
name: reality-check
version: 0.8.1
description: >-
  Checks that an app works the way a real user would experience it, on your machine, in a Digital Twin Universe, or in one it sets up for you, and returns evidence for every finding. Use after an agent builds a feature or fix, when passing tests are not enough evidence that a user can do what they came to do
use_cases:
  - Check that a new user can sign up and send a message after a feature or fix, with screenshots, requests, and console messages as evidence
  - Set up a repository as if it were deployed and check that its main pages load quickly with no console errors
  - Click through every page and settings submenu and list what is broken or inconsistent
  - Check an app on another machine from the browser where you are already signed in
  - Find out why a scripted smoke test fails by seeing what a user would see
  - Run an earlier check again against a new branch and list what changed
platforms:
  - linux
  - macos
  - windows
requires:
  - name: gh
    purpose: >-
      Generates the token that signs in to GitHub Copilot, for the copilot agent provider.
      Without it, the model-backed capabilities cannot authenticate through copilot.
    optional: true
    install: https://cli.github.com/
  - name: github-copilot-subscription
    purpose: >-
      A Copilot subscription on the account signed in to gh powers the model-backed
      capabilities, for the copilot agent provider.
    optional: true
    install: https://github.com/github/copilot-cli#prerequisites
  - name: amplifier-agent-provider-credentials
    purpose: >-
      The credentials of the model provider the amplifier-agent agent provider calls, for
      instance OPENAI_API_KEY for its default model. Without them, the model-backed
      capabilities cannot run through amplifier-agent.
    optional: true
    install: https://github.com/microsoft/amplifier-agent/blob/v0.25.0/docs/providers.md
  - name: codex-sign-in
    purpose: >-
      The Codex CLI signed in with ChatGPT or an API key, for the codex agent provider.
      Without it, the model-backed capabilities cannot run through codex.
    optional: true
    install: https://developers.openai.com/codex/auth
  - name: claude-credentials
    purpose: >-
      ANTHROPIC_API_KEY, or a cloud provider's credentials, for the claude agent provider.
      Without them, the model-backed capabilities cannot run through claude.
    optional: true
    install: https://code.claude.com/docs/en/agent-sdk/quickstart
  - name: cua-driver
    purpose: >-
      Drives desktop apps for checks: screenshots, the accessibility tree, and input. It needs
      a desktop session (on Linux, DISPLAY or WAYLAND_DISPLAY) and, on macOS, the Accessibility
      and Screen Recording permissions. Without it, checks of desktop UIs say computer use is
      not enabled.
    optional: true
    install: https://github.com/microsoft/amplifier-smart-tool-reality-check#computer-use
  - name: agent-browser
    purpose: >-
      Drives web apps' UIs headlessly for checks: pages, screenshots, console, and network.
      `reality-check install` installs it and makes sure a headless browser launches.
    optional: true
    install: https://github.com/microsoft/amplifier-smart-tool-reality-check#browser

---

Checks that an app works the way a real user would experience it, on your machine, in a Digital Twin Universe, or in one it sets up for you, and returns evidence for every finding.

**The library is the tool.** `reality_check.lib` holds every capability. The CLI is a thin wrapper over it, so anything you can do from the shell you can also do from Python.
Deterministic capabilities run with no provider configured. Model-backed capabilities go through GitHub Copilot, Amplifier Agent, Codex, or Claude.
Every capability has its own skill. Read `reality-check <command> --help` before calling it: it carries the arguments, a worked invocation, and the result.
The library source beside this file, `lib.py`, carries the signatures. The repository's `docs/01-library.md` and `docs/02-cli.md` have the rest.

## When to reach for it

- An agent built a feature or fixed a bug, and someone needs to know that a user can now do the thing. Run a check as the last step, before saying it works.
- A scripted test fails or is flaky, and it is not clear whether the app, the test, or the environment is at fault.
- A broad pass over an app: every page, every settings submenu, a new user's first run.
- A later check against an earlier one, to see what changed.

Not for release gates, CI steps, or the same assertions on each change:
scripted tests are faster and cheaper there, so say that to the caller instead of starting a check.
Not for unit tests, load testing, or security testing.

## Install

```bash
# as a CLI
uv tool install "reality-check[all] @ git+https://github.com/microsoft/amplifier-smart-tool-reality-check@v0.8.1"

# as a library, from another project
uv add "reality-check[all] @ git+https://github.com/microsoft/amplifier-smart-tool-reality-check@v0.8.1"

# once, without installing
uvx --from "reality-check[all] @ git+https://github.com/microsoft/amplifier-smart-tool-reality-check@v0.8.1" reality-check --help

# once, to give checks everything they can use
reality-check install

# once, if the host renders MCP Apps: register `reality-check mcp` as its MCP server, so checks
# show in the host. `reality-check mcp --help` has the details.
```

`[all]` brings every agent provider the model-backed capabilities run through. Put
`[copilot]`, `[amplifier-agent]`, `[codex]`, or `[claude]` in its place for just one, or drop it for the deterministic
capabilities only.

Verify with `reality-check manifest`, which needs no credentials. Each release is a `v<version>` tag
and an install stays on its tag, so `uv tool upgrade` does not move it. To upgrade, find the newest release:

```bash
git ls-remote --tags --refs --sort=-v:refname https://github.com/microsoft/amplifier-smart-tool-reality-check "v*" | head -1
```

If it is newer than `reality-check --version`, run the install command again with that tag and the extras
`uv tool list --show-extras` reports, or `uv add` again with the new tag for a library. Update the skill with
`npx skills add microsoft/amplifier-smart-tool-reality-check#<tag>`. In a host that renders MCP Apps, also make sure
`reality-check mcp` is registered.

## Prerequisites

Deterministic capabilities need only `uv`. Model-backed capabilities run through an agent
provider, the first installed of `copilot`, `amplifier-agent`, `codex`, and `claude`:

- `copilot`: GitHub Copilot, signed in as the GitHub CLI's user. `gh` must be installed and
  `gh auth login` completed with an account that has a Copilot subscription.
- `amplifier-agent`: [Amplifier Agent](https://github.com/microsoft/amplifier-agent), calling
  the model provider named in the model `<provider>/<model>` with that provider's credentials,
  for instance `OPENAI_API_KEY` for the default `openai/...` models. See its
  [providers](https://github.com/microsoft/amplifier-agent/blob/v0.25.0/docs/providers.md).
- `codex`: [OpenAI Codex](https://github.com/openai/codex), with the user's Codex configuration.
  The Codex CLI must be signed in with ChatGPT or an API key, see
  [authentication](https://developers.openai.com/codex/auth).
- `claude`: the [Claude Agent SDK](https://github.com/anthropics/claude-agent-sdk-python). Needs
  `ANTHROPIC_API_KEY`, or Amazon Bedrock, Claude Platform on AWS, Google Cloud's Agent Platform, or
  Microsoft Foundry credentials in the environment, see
  [authentication](https://code.claude.com/docs/en/agent-sdk/quickstart).

Without one, a model-backed capability fails immediately and names what to configure; it never falls back to a deterministic answer.
Runs on Linux, macOS, and Windows.

## Running Checks

The main capability is `check-software`: it checks software as a user would and ends with a report and its evidence.
Read `reality-check check-software --help` before starting a check.
Run one check when a change is done, with a request that names what changed, not one after each edit, and none for a change no user sees.
A broad request such as "validate my app" works and takes much longer.
A report names the parts next to what it checked that it did not cover, and offers a broader check of them.
Checks that do not depend on each other should be kicked off in parallel. A faster model or lower reasoning effort trades some quality for time and cost.
The other capabilities serve it: follow, steer, or cancel a running check, read or list checks, show them to the person in the app, and list the models a check runs on.
Show a check with `mcp`'s `open_app` in a host that renders MCP Apps, and with `app` in any other host.

## Choosing a surface

Import the library from Python. Shell out to the CLI from anything that cannot import
Python in-process: a shell script, a CI job, or an agent that can run commands but not
load a Python object. Both reach the same capabilities.
