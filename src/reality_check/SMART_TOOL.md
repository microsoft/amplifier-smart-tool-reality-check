---
smart_tool_format: 1
name: reality-check
version: 0.6.0
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

---

Checks that an app works the way a real user would experience it, on your machine, in a Digital Twin Universe, or in one it sets up for you, and returns evidence for every finding.

**The library is the tool.** `reality_check.lib` holds every capability. The CLI is a thin
wrapper over it, so anything you can do from the shell you can also do from Python.

## When to reach for it

- An agent built a feature or fixed a bug, and someone needs to know that a user can now do the thing. Run a check as the last step, before saying it works.
- A scripted test fails or is flaky, and it is not clear whether the app, the test, or the environment is at fault.
- A broad pass over an app: every page, every settings submenu, a new user's first run.
- A later check against an earlier one, to see what changed.

Not for release gates, CI steps, or the same assertions on each change: scripted tests are
faster and cheaper there, so say that to the caller instead of starting a check. Not for unit
tests, load testing, or security testing.

## Before writing code

Every capability has its own skill. Read `reality-check <command> --help` before calling it: it
carries the arguments, a worked invocation, and the result. Do not fill gaps
from memory. The library source beside this file, `lib.py`, carries the signatures. The
repository's `docs/01-library.md` and `docs/02-cli.md` carry the rest.

## Install

```bash
# as a CLI
uv tool install "reality-check[all] @ git+https://github.com/microsoft/amplifier-smart-tool-reality-check"

# as a library, from another project
uv add "reality-check[all] @ git+https://github.com/microsoft/amplifier-smart-tool-reality-check"

# once, without installing
uvx --from "reality-check[all] @ git+https://github.com/microsoft/amplifier-smart-tool-reality-check" reality-check --help

# once, to check desktop apps
reality-check install-computer-use

# once, to show checks inline: register `reality-check mcp` as a stdio MCP server in the
# client, then reload its MCP servers. `reality-check mcp --help` has the details.
```

`[all]` brings every agent provider the model-backed capabilities run through. Put
`[copilot]`, `[amplifier-agent]`, `[codex]`, or `[claude]` in its place for just one, or drop it for the deterministic
capabilities only.

Verify with `reality-check manifest`, which needs no credentials.

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

Without one, a model-backed capability fails immediately and names what to configure; it
never falls back to a deterministic answer.

Every agent provider runs with its telemetry turned off.

Runs on Linux, macOS, and Windows.

## Straight and smart paths

Deterministic capabilities run with no provider configured. Model-backed capabilities go
through GitHub Copilot, Amplifier Agent, Codex, or Claude, and say so in their help text.

## Output and failure contract

Results go to stdout, diagnostics to stderr. A failure prints a message naming what went
wrong and how to fix it, and exits non-zero: 1 for a failure the tool can name, 2 for a
bad invocation. Never treat an empty result as success.

`check-software` runs for minutes: start it with `--detach`, which prints its `started` event
and exits, then follow it with `read-check-activity --after-event <last id>` until a `finished` or
`failed` event. `list-intelligence-models` lists the models it runs on.

## After a check

The report is the check's final message, also saved as `report.md` in the check's directory.
It gives a verdict per item asked about (pass, fail, or not checked) and the evidence files
each stands on, relative to that directory. Not checked is never a pass. Give the caller the
verdicts and each failure's step, action, and what was recorded. The report's Next steps section
guides the calling agent on possible investigation, fixes, and rechecks. Use it within the
caller's authorized scope; ask before actions that need further approval. After
a fix, check again with `--resume <check_id>`, the command the result's `next` names.

To find an earlier check without its ID, `list-checks` lists every check on this machine. For the
person you work for, the app shows every check with its report and evidence. With the MCP server
registered, call its `open_app` tool with the check's ID: hosts that render MCP Apps show
it inline. Without it, `reality-check app` shows it in their browser. `mcp --help` says how to
register the server.

## Choosing a surface

Import the library from Python. Shell out to the CLI from anything that cannot import
Python in-process: a shell script, a CI job, or an agent that can run commands but not
load a Python object. Both reach the same capabilities.
