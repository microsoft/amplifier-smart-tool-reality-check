# Reality Check Smart Tool

Checks that an app works the way a real user would experience it, on your machine, in a Digital Twin Universe, or in one it sets up for you, and returns evidence for every finding.

## Quick Start

```bash
# Install the Agent Skill so your agent knows about it.
npx skills add microsoft/amplifier-smart-tool-reality-check
# Install the tool, choosing the provider(s) you want
uv tool install "reality-check[all | copilot | amplifier-agent | codex | claude] @ git+https://github.com/microsoft/amplifier-smart-tool-reality-check"
```

This is a [Smart Tool](https://github.com/microsoft/amplifier-smart-tools) which is a library with a thin CLI over it and model-backed capabilities sit behind an interface so many providers can be used.
We support [GitHub Copilot SDK](https://github.com/github/copilot-sdk), [Amplifier Agent](https://github.com/microsoft/amplifier-agent), the [OpenAI Codex SDK](https://github.com/openai/codex/tree/main/sdk/python), and the [Claude Agent SDK](https://github.com/anthropics/claude-agent-sdk-python).

## Installation

Prerequisites:
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- For the model-backed capabilities, one of:
  - `copilot` agent provider: [GitHub CLI](https://cli.github.com/) signed in to an account with a [GitHub Copilot subscription](https://github.com/github/copilot-cli#prerequisites).
  - `amplifier-agent` agent provider: the model provider's credentials, for instance `OPENAI_API_KEY` for the default `openai/...` models. See [providers](https://github.com/microsoft/amplifier-agent/blob/v0.22.0/docs/providers.md).
  - `codex` agent provider: the [Codex CLI](https://github.com/openai/codex) signed in with ChatGPT or an API key. See [authentication](https://developers.openai.com/codex/auth).
  - `claude` agent provider: `ANTHROPIC_API_KEY`, or any of its other supported modes of [authentication](https://code.claude.com/docs/en/agent-sdk/quickstart).
- (Optional) Install the Smart Tools skill so your agent knows about Smart Tools: `npx skills add microsoft/amplifier-smart-tools`

To use it as a library:

```bash
uv add "reality-check[all] @ git+https://github.com/microsoft/amplifier-smart-tool-reality-check"
```

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

## Interface

```bash
reality-check manifest

reality-check check-software --request "Check that a new user can sign up" --target http://localhost:3000 --detach

reality-check read-check-activity --check-id CHECK_ID [--after CURSOR] [--tool-call-id ID]

reality-check steer-check --check-id CHECK_ID --message "Skip the settings pages"

reality-check cancel-check --check-id CHECK_ID

reality-check list-intelligence-models

reality-check reaching-software-skill # or using-software-skill, gathering-evidence-skill
```

See the [CLI reference](docs/02-cli.md) for every flag and the [library reference](docs/01-library.md) for the Python surface.

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
