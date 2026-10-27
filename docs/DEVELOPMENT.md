# Reality Check Development

## Development Setup

### Prerequisites

Install:

- [Git](https://git-scm.com/)
- [uv](https://docs.astral.sh/uv/getting-started/installation/): Manages Python environments
- [prek](https://github.com/j178/prek): Used for precommit hooks. Recommended to install through PyPI/uv with `uv tool install prek`. Use `uv tool upgrade prek` to update it.
- [GitHub CLI](https://cli.github.com/) for intelligence features with GitHub Copilot.
- [GitHub Copilot subscription](https://github.com/github/copilot-cli#prerequisites) for intelligent features through the `copilot` agent provider.
- [Model provider credentials](https://github.com/microsoft/amplifier-agent/blob/v0.23.1/docs/providers.md), such as `OPENAI_API_KEY`, for intelligent features through the `amplifier-agent` agent provider.
- [Codex CLI](https://github.com/openai/codex) [signed in](https://developers.openai.com/codex/auth) with ChatGPT or an API key, for intelligent features through the `codex` agent provider.
- [`ANTHROPIC_API_KEY` or a cloud provider's credentials](https://code.claude.com/docs/en/agent-sdk/quickstart), for intelligent features through the `claude` agent provider.
- [Docker](https://docs.docker.com/get-started/get-docker/), for [evaluations](../evaluations/README.md).
- [Node 22+](https://nodejs.org/) and [pnpm](https://pnpm.io/installation), only to change the app.

### Initial Setup

1. Clone this repository and change into it.

1. Run the development installation script (sets up the uv env, precommit hooks, and the `reference/` clones):

   ```bash
   uv run setup-for-dev.py
   ```

### Essential Development Commands

*Commands should be run from the repository root, unless otherwise specified.*

#### Precommit hooks

Setup precommit hooks:

```bash
prek install
```

Run precommit hooks manually:

```bash
prek run --all-files
```

#### Python Library Development

Create uv virtual environment and install dependencies:

```bash
uv sync --frozen --all-extras --all-groups
```

To update dependencies and the lock file:

```bash
uv sync -U --all-extras --all-groups
```

Lint code:

```bash
uv run ruff check --fix --config pyproject.toml
```

Format code (also formats code blocks in .md files):

```bash
uv run ruff format --config pyproject.toml
```

Type check:

```bash
uv run ty check .
```

Run tests:

```bash
uv run pytest
```

#### App Development

The app's frontend is in `app/`: React, Vite, and Tailwind. Its built view and browser host page are committed under `src/reality_check/capabilities/app/static/`, so the tool installs and runs with no Node.

Check and build it, and copy the build into the package (without pnpm, this says so and exits 0):

```bash
uv run build-app.py
```

`uv run build-app.py lint` (or `format`, `typecheck`, `build`, `build:view`) runs one step. The precommit hooks run these when `app/` changes, so commit the rebuilt files with the source.

To see a change, build it and serve the app:

```bash
uv run build-app.py build build:view && uv run reality-check app
```

#### References

`reference/` holds gitignored clones of the repositories worth reading while developing this tool. `uv run setup-for-dev.py` clones any that are missing.

#### Evaluations

Each capability is evaluated on tasks in isolated evaluation environments; see [evaluations/README.md](../evaluations/README.md).

```bash
uv run evaluations/run.py run --task excalidraw-01
```

#### Conformance

Run the spec's [conformance kit](https://github.com/microsoft/amplifier-smart-tools/tree/main/conformance) against this repository.
The outer `uv run` puts this project's `reality-check` on `PATH` for the kit to invoke; the inner one runs the kit with its own inline dependencies:

```bash
uv run -- uv run --no-project https://raw.githubusercontent.com/microsoft/amplifier-smart-tools/main/conformance/run.py .
```
