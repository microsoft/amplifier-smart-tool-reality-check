# Reality Check Development

## Development Setup

### Prerequisites

Install:

- [Git](https://git-scm.com/)
- [uv](https://docs.astral.sh/uv/getting-started/installation/): Manages Python environments
- [prek](https://github.com/j178/prek): Used for precommit hooks. Recommended to install through PyPI/uv with `uv tool install prek`. Use `uv tool upgrade prek` to update it.
- [GitHub CLI](https://cli.github.com/) for intelligence features with GitHub Copilot.
- [GitHub Copilot subscription](https://github.com/github/copilot-cli#prerequisites) for intelligent features through the `copilot` agent provider.
- [Model provider credentials](https://github.com/microsoft/amplifier-agent/blob/v0.25.0/docs/providers.md), such as `OPENAI_API_KEY`, for intelligent features through the `amplifier-agent` agent provider.
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

To update dependencies, follow [Updating Dependencies](#updating-dependencies).

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

#### Updating Dependencies

Every dependency has a 7 day cooldown: `exclude-newer = "7 days"` under `[tool.uv]` in `pyproject.toml`, and `minimumReleaseAge: 10080` (minutes) in `app/pnpm-workspace.yaml`.
An update never applies a major version upgrade. Collect each one, check whether its peers allow it, and report it at the end.

##### Dependabot

1. List the open Dependabot alerts and pull requests:

   ```bash
   gh api repos/microsoft/amplifier-smart-tool-reality-check/dependabot/alerts \
     --jq '.[] | select(.state == "open") | [.dependency.package.name, .dependency.manifest_path, .security_vulnerability.first_patched_version.identifier] | @tsv'
   gh pr list --author app/dependabot
   ```

1. Do not merge the pull requests. Each one changes a lock file or workflow, so they conflict with each other and with the update, which moves the same packages. Dependabot closes them, and the alerts, once the merged lock files no longer hold the vulnerable versions.

##### Python

1. Runtime dependencies and extras carry a cap at the next major, for example `"mcp>=2.3.0,<3.0.0"`, so we never auto upgrade to a new major. A 0.x package treats its minor as the major, so its cap is the next minor, for example `"fastapi>=0.141.1,<0.142.0"`. The exception is `openai-codex`, capped at `<1.0.0`: each of its versions pins the Codex CLI release of the same number, so a new minor is a routine CLI release. Dev dependencies have no cap.
1. For each PyPI dependency in `[project.dependencies]`, `[project.optional-dependencies]`, and `[dependency-groups]`, find the latest version. Read `https://pypi.org/pypi/<name>/json` and take the newest non-prerelease, non-yanked release whose earliest file upload is at least 7 days old. Do not trust the top of the PyPI history page; it ignores the cooldown.
1. Raise each floor that is behind to that version, keeping the form the entry already uses (`>=2.13,<3.0` stays two-part, `>=0.27.2,<0.28.0` stays three-part). Never raise a cap: a latest version at or past the cap is a major upgrade to report.
1. Move the git dependencies, which have no cooldown. They are pinned exactly and checked by the evaluation runs below, so they move even across a 0.x minor.
   - `amplifier-agent` to its newest release tag, from `gh release list -R microsoft/amplifier-agent -L 1`. Its tag is also in the providers documentation links; replace every match of `git grep <old-tag>`.
   - `digital-twin-universe` to its newest release tag, from `git ls-remote --tags --refs --sort=-v:refname https://github.com/microsoft/amplifier-smart-tool-digital-twin-universe "v*" | head -1`.
1. Update `uv_build` under `[build-system]` to the latest version, moving its cap with it. It is the one exception to the cap rule.
1. `exclude-newer-package` exempts a package from the cooldown for a security fix. Remove each entry whose comment condition now holds.
1. Run `uv lock --upgrade`. It respects the cooldown and the caps, and moves transitive dependencies too. Do this even when `pyproject.toml` did not change.
1. Run `uv sync --frozen --all-extras --all-groups`.
1. Run `uv build --wheel -o temp/dist` and confirm the wheel still holds `SMART_TOOL.md`, `skills/`, and `capabilities/app/static/`. Delete `temp/dist` after.
1. `.pre-commit-config.yaml` only has local hooks, so it has no hook versions to bump. If a remote hook repository is ever added, bump its `rev` to its latest release the same way.

##### App

1. Run `pnpm --dir app outdated`. Its Latest column already respects the cooldown.
1. Note every row whose Latest is a new major (for example `typescript` 6 to 7). For each, check its peers with `pnpm view <package>@<version> peerDependencies`, and the peer ranges of the packages that depend on it, so the report can say whether it is possible today. A common blocker is `typescript-eslint` capping `typescript`.
1. Update everything else, excluding each major by name:

   ```bash
   pnpm --dir app update --latest '!<major-1>' '!<major-2>'
   ```

   Read the output for peer dependency warnings, especially across the React, Vite, and ESLint packages.
1. Run `pnpm --dir app update <package>` for each excluded major, so it still moves to the newest release within its current range.
1. If `app/pnpm-workspace.yaml` has `overrides`, make sure each still matches the updated versions, then run `pnpm --dir app install`.
1. Set `packageManager` in `app/package.json` to the newest pnpm release in its major that is at least 7 days old, from `pnpm view pnpm time --json`.
1. Run `uv run build-app.py`. It installs, lints, formats, type checks, and compiles both the host page and the view into `src/reality_check/capabilities/app/static/`. Those compiled files are committed, so they are part of the change.

##### GitHub Actions

1. For each `uses:` in `.github/workflows/*.yml`, find the newest release in its current major that is at least 7 days old. The list is not in version order, since some actions also release older majors:

   ```bash
   gh release list -R <owner>/<repo> --exclude-pre-releases --json tagName,publishedAt --jq '.[] | [.tagName, .publishedAt] | @tsv'
   ```

1. Pin it by the full commit SHA of its tag, with the tag as a comment, for example `actions/checkout@<sha> # v7.0.1`. Use the same SHA in every workflow:

   ```bash
   gh api repos/<owner>/<repo>/commits/<tag> --jq .sha
   ```

##### Finish

1. Run `prek run --all-files` and `uv run pytest`; both must pass.
1. Only when an agent SDK moves to a new major version, by the same rule as the caps (a 0.x minor counts, an `openai-codex` minor does not), run one [evaluation](../evaluations/README.md) task on each provider whose SDK did, all at the same time. They are too slow for minor and patch bumps. `copilot` covers `github-copilot-sdk`, `codex` covers `openai-codex`, `claude` covers `claude-agent-sdk`, and `amplifier-agent` covers `amplifier-agent`. Each run must complete, with a score in line with that provider's earlier runs of the task. The runs install reality-check as a user does, so they test the newest versions the `pyproject.toml` ranges allow, not `uv.lock`.

   ```bash
   for provider in <provider-1> <provider-2>; do
     uv run evaluations/run.py run --task excalidraw-01 --agent-provider "$provider" > "temp/eval-$provider.log" 2>&1 &
   done
   wait
   ```

1. Run the Dependabot alert command again. Each alerted package must now be at or above its patched version in `uv.lock` or `app/pnpm-lock.yaml`.
   - If the cooldown holds back the fix, exempt that package, with a comment saying when to remove it: `exclude-newer-package` under `[tool.uv]`, or `minimumReleaseAgeExclude` in `app/pnpm-workspace.yaml`.
   - If the fix is a new major of a transitive dependency that its dependents do not allow yet, report it with the other majors.
1. Report what moved on each side, every major upgrade held back with whether its peers allow it, any evaluation scores, and which Dependabot alerts remain.

#### References

`reference/` holds gitignored clones of the repositories worth reading while developing this tool. `uv run setup-for-dev.py` clones any that are missing.

#### Evaluations

Each capability is evaluated on tasks in isolated evaluation environments; see [evaluations/README.md](../evaluations/README.md).

#### Conformance

Run the spec's [conformance kit](https://github.com/microsoft/amplifier-smart-tools/tree/main/conformance) against this repository.
The outer `uv run` puts this project's `reality-check` on `PATH` for the kit to invoke; the inner one runs the kit with its own inline dependencies:

```bash
uv run -- uv run --no-project https://raw.githubusercontent.com/microsoft/amplifier-smart-tools/main/conformance/run.py .
```

## Releasing

Each PR that changes the library or CLI already bumps the version: `uv version --bump <part>`, then the same version in
`SMART_TOOL.md`, `SKILL.md`, and the `@v<version>` and `#v<version>` install pins, which `tests/test_manifest.py`
holds to the package version.

Each PR also adds its user-visible changes under `## Unreleased` in `CHANGELOG.md`. The version bump renames
`## Unreleased` to `## X.Y.Z (YYYY-MM-DD)` and starts a new, empty `## Unreleased` above it.

Tag the merge commit right after the PR merges, since main's docs already point at the new tag:

```bash
git tag v<version> <commit>
git push origin v<version>
```

The tag runs `.github/workflows/release.yml`, which builds the wheel and sdist and publishes them as a GitHub Release
with generated notes.
