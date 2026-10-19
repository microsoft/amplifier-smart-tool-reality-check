"""The agent providers' prerequisites, then reality-check, installed in the twin the way the README tells a user to."""

import json
from pathlib import Path
import shlex
import subprocess
from typing import Any

from common import providers
from common.context import RunContext
from common.environment import HOME, REPOSITORY_URL, Environment

REPOSITORY = Path(__file__).resolve().parents[2]
TOOL_BIN = f"{HOME}/.local/share/uv/tools/reality-check/bin"
DTU = f"{TOOL_BIN}/digital-twin-universe"


def provider_and_reality_check(env: Environment, context: RunContext) -> None:
    """Install what the run's agent providers need, then reality-check, and record the versions installed."""
    for name in dict.fromkeys([context.spec.agent_provider, context.spec.judge_agent_provider]):
        env.run_checked(f"setup-{name}", providers.provider(name).setup)
    extra = providers.provider(context.spec.agent_provider).extra
    # The checkout uv cloned holds the evaluations' tasks and answer keys; the installed tool does not need it.
    env.run_checked("install", f"uv tool install {shlex.quote(spec(extra))} && rm -rf {HOME}/.cache/uv/git-v*")
    listed = env.run_checked("versions", f"uv pip list --python {TOOL_BIN}/python --format json", timeout_seconds=60)
    context.record.versions = {
        "repository": _repository_version(),
        "environment": {package["name"]: package["version"] for package in json.loads(listed.stdout)},
    }


def spec(extra: str) -> str:
    """The requirement that installs reality-check with `extra` from the checkout the environment serves."""
    return f"reality-check[{extra}] @ git+{REPOSITORY_URL}"


def _repository_version() -> dict[str, Any]:
    def git(*arguments: str) -> str:
        return subprocess.run(["git", "-C", str(REPOSITORY), *arguments], capture_output=True, text=True).stdout.strip()

    return {"commit": git("rev-parse", "HEAD"), "dirty": bool(git("status", "--porcelain"))}
