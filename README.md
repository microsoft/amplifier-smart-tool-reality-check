<h1 align="center">Reality Check Smart Tool</h1>

<p align="center">The most thorough tester you have worked with. It finds what your agent missed, and proves it.</p>

Has your agent ever finished a feature or a bug fix, said it works, and it was still broken?
Reality Check is a [Smart Tool](https://github.com/microsoft/amplifier-smart-tools) that tests your app by using it: in a browser, on the desktop, or in a [Digital Twin Universe](https://github.com/microsoft/amplifier-smart-tool-digital-twin-universe) that it sets up for you. Then it reports what works and what does not, with evidence for each finding.

Use it from the agent you already work in, such as Amplifier, Copilot, Codex, or Claude Code.

## Quickstart

1. Ask your agent:

   > Install https://github.com/microsoft/amplifier-smart-tool-reality-check and its agent skill.

1. Work as usual. When your agent finishes something, it can call Reality Check itself, or you can ask:

   > My app is running locally. Check that a new user can sign up and send a message.

   > I fixed the bug in issue #412 where saving a draft loses the attachments. Check that it is fixed and that nothing near it broke.

   > Set up this repository as if it were deployed, and check that the dashboard loads in under three seconds with no console errors.

   > Click through every settings page and list where the spacing, icons, or wording are not consistent.

1. Get back a report that says what was checked, what passed, and what failed, with screenshots and other evidence for each finding.
   Your agent reads it and suggests what to do next. Ask it before it makes changes. Each check is saved in `.agents/reality-check` by default, so you can come back to it later.

Use it after your agent builds a feature or fixes a bug, or when a scripted test fails and you cannot tell why. It does not replace unit tests, and it is not a release gate or a CI step: a check takes minutes, so keep scripted tests for those.

For manual setup, see [Installation](#installation).

## See your checks

```bash
reality-check app
```

Opens every check on your machine, from every project, in your browser: what is running now, each report with its screenshots and other evidence, and what the check's agent did. The app only shows checks; your agent starts and steers them.

## Command line

```bash
# Start a check and let it run in the background
reality-check check-software --request "Check that a new user can sign up" --target http://localhost:3000 --detach

# Follow what it does, steer it, or stop it
reality-check read-check-activity --check-id CHECK_ID
reality-check steer-check --check-id CHECK_ID --message "Skip the settings pages"
reality-check cancel-check --check-id CHECK_ID

# Continue a previous check, for instance after a new fix
reality-check check-software --request "Check it again" --resume CHECK_ID

# Find earlier checks, from every project, and read one
reality-check list-checks
reality-check read-check --check-id CHECK_ID

# Other
reality-check app   # or mcp, to serve it to an MCP client
reality-check list-intelligence-models
reality-check reaching-software-skill # or using-software-skill, using-computer-use-skill, gathering-evidence-skill
reality-check install-computer-use
```

See the [CLI reference](docs/02-cli.md) for every flag and the [library reference](docs/01-library.md) for the Python surface.

## Installation

Prerequisites:
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- At least one agent provider to run checks:
  - `copilot`: [GitHub CLI](https://cli.github.com/) signed in to an account with a [GitHub Copilot subscription](https://github.com/github/copilot-cli#prerequisites).
  - `amplifier-agent`: the model provider's credentials, for instance `OPENAI_API_KEY` for the default `openai/...` models. See [providers](https://github.com/microsoft/amplifier-agent/blob/v0.23.1/docs/providers.md).
  - `codex`: the [Codex CLI](https://github.com/openai/codex) signed in with ChatGPT or an API key. See [authentication](https://developers.openai.com/codex/auth).
  - `claude`: `ANTHROPIC_API_KEY`, or any of its other supported modes of [authentication](https://code.claude.com/docs/en/agent-sdk/quickstart).

(Optional) Install the Smart Tools skill so your agent knows about Smart Tools: `npx skills add microsoft/amplifier-smart-tools`

To install manually:

```bash
# Install the Agent Skill so your agent knows about it.
npx skills add microsoft/amplifier-smart-tool-reality-check
# Choose the provider(s) you want: [all], [copilot], [amplifier-agent], [codex], or [claude]
uv tool install "reality-check[all] @ git+https://github.com/microsoft/amplifier-smart-tool-reality-check"
```

To use it as a library:

```bash
uv add "reality-check[all] @ git+https://github.com/microsoft/amplifier-smart-tool-reality-check"
```

### Computer use

Checks drive desktop apps through [cua-driver](https://github.com/trycua/cua/tree/main/libs/cua-driver). `reality-check install-computer-use` installs a pinned, hash-checked release once, into reality-check's own folder, with its telemetry and update checks off. Under WSL it installs the Windows build, and checks drive the Windows desktop. Linux needs a desktop session; macOS needs the Accessibility and Screen Recording permissions, which `cua-driver permissions grant` asks for.

To update:

```bash
npx skills update reality-check   # add -g for global installs
uv tool upgrade reality-check
```

To uninstall:

```bash
npx skills remove reality-check   # add -g for global installs
uv tool uninstall reality-check
```

## Contributing

See [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) for details on how to set up your development environment.

> [!NOTE]
> This project is not currently accepting external contributions, but we're actively working toward opening this up. We value community input and look forward to collaborating in the future. For now, feel free to fork and experiment!

Most contributions require you to agree to a
Contributor License Agreement (CLA) declaring that you have the right to, and actually do, grant us
the rights to use your contribution. For details, visit [Contributor License Agreements](https://cla.opensource.microsoft.com).

When you submit a pull request, a CLA bot will automatically determine whether you need to provide
a CLA and decorate the PR appropriately (e.g., status check, comment). Simply follow the instructions
provided by the bot. You will only need to do this once across all repos using our CLA.

This project has adopted the [Microsoft Open Source Code of Conduct](https://opensource.microsoft.com/codeofconduct/).
For more information see the [Code of Conduct FAQ](https://opensource.microsoft.com/codeofconduct/faq/) or
contact [opencode@microsoft.com](mailto:opencode@microsoft.com) with any additional questions or comments.

## Trademarks

This project may contain trademarks or logos for projects, products, or services. Authorized use of Microsoft
trademarks or logos is subject to and must follow
[Microsoft's Trademark & Brand Guidelines](https://www.microsoft.com/legal/intellectualproperty/trademarks/usage/general).
Use of Microsoft trademarks or logos in modified versions of this project must not cause confusion or imply Microsoft sponsorship.
Any use of third-party trademarks or logos are subject to those third-party's policies.
