---
smart_tool_format: 1
name: reality-check
version: 0.4.0
description: >-
  Checks that an app works the way a real user would experience it, on your machine, in a Digital Twin Universe, or in one it sets up for you, and returns evidence for every finding
use_cases:
  - >-
    Checks that an app works the way a real user would experience it, on your machine, in a Digital Twin Universe, or in one it sets up for you, and returns evidence for every finding
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
    install: https://github.com/microsoft/amplifier-agent/blob/v0.23.1/docs/providers.md
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

- Checks that an app works the way a real user would experience it, on your machine, in a Digital Twin Universe, or in one it sets up for you, and returns evidence for every finding.

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
  [providers](https://github.com/microsoft/amplifier-agent/blob/v0.23.1/docs/providers.md).
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
and exits, then follow it with `read-check-activity` until an `ended` entry. `list-intelligence-models`
lists the models it runs on.

## Choosing a surface

Import the library from Python. Shell out to the CLI from anything that cannot import
Python in-process: a shell script, a CI job, or an agent that can run commands but not
load a Python object. Both reach the same capabilities.
