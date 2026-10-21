"""What the run's capability needs, installed in the twin the way its README tells a user to."""

import json
from pathlib import Path
import re
import shlex
import subprocess
import tomllib
from typing import Any

from common import baselines, providers
from common.context import Capability, EvaluationError, RunContext
from common.environment import HOME, REPOSITORY_URL, Environment

REPOSITORY = Path(__file__).resolve().parents[2]
TOOL_BIN = f"{HOME}/.local/share/uv/tools/reality-check/bin"
DTU = f"{TOOL_BIN}/digital-twin-universe"
# Digital Twin Universe installed on its own, for the judge of a run without reality-check.
STANDALONE_DTU = f"{HOME}/.local/share/uv/tools/digital-twin-universe/bin/digital-twin-universe"
VERSION = re.compile(r"\d+(?:\.\d+){2}(?:-[0-9A-Za-z]+)*")


def setup(env: Environment, context: RunContext, computer_use: bool = False) -> None:
    """Install what the run's capability needs, and record the versions installed.

    For reality-check: the agent providers' prerequisites, reality-check, and with `computer_use`, its computer use.
    For the baseline: the agent provider's own CLI and nothing else; the judge's needs wait for `judge_prerequisites`.
    """
    match context.spec.capability:
        case "reality-check":
            provider_and_reality_check(env, context)
            if computer_use:
                env.run_checked("install-computer-use", "reality-check install-computer-use")
        case "baseline":
            agent_cli(env, context)


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


def agent_cli(env: Environment, context: RunContext) -> None:
    """Install the agent provider's own CLI at the version reality-check's runtime for it uses, and record it."""
    cli = baselines.baseline(context.spec.agent_provider)
    pin = cli.pin()
    env.run_checked("install", cli.install(pin.version))
    printed = env.run_checked("versions", cli.version, timeout_seconds=60).stdout
    found = VERSION.search(printed)
    installed = found.group() if found else printed.strip()
    if installed != pin.version:
        raise EvaluationError(f"The baseline installed {context.spec.agent_provider} {installed}, not {pin.version}.")
    context.record.versions = {
        "repository": _repository_version(),
        "baseline": {"agent_provider": context.spec.agent_provider, "cli": installed, "pinned_by": pin.pinned_by},
    }


def judge_prerequisites(env: Environment, context: RunContext) -> None:
    """After a baseline, install what the judge needs that the capability did not; nothing for reality-check.

    That is the judge provider's prerequisites, and Digital Twin Universe at the version reality-check pins, at
    `STANDALONE_DTU`.
    """
    if context.spec.capability != "baseline":
        return
    name = context.spec.judge_agent_provider
    env.run_checked(f"judge-setup-{name}", providers.provider(name).setup)
    env.run_checked("judge-dtu", f"uv tool install {shlex.quote(_dtu_requirement())}", timeout_seconds=900)


def dtu(capability: Capability) -> str:
    """The Digital Twin Universe the judge of a `capability` run can launch universes with."""
    return DTU if capability == "reality-check" else STANDALONE_DTU


def spec(extra: str) -> str:
    """The requirement that installs reality-check with `extra` from the checkout the environment serves."""
    return f"reality-check[{extra}] @ git+{REPOSITORY_URL}"


def _dtu_requirement() -> str:
    with (REPOSITORY / "pyproject.toml").open("rb") as file:
        dependencies = tomllib.load(file)["project"]["dependencies"]
    return next(line for line in dependencies if line.startswith("digital-twin-universe"))


def _repository_version() -> dict[str, Any]:
    def git(*arguments: str) -> str:
        return subprocess.run(["git", "-C", str(REPOSITORY), *arguments], capture_output=True, text=True).stdout.strip()

    return {"commit": git("rev-parse", "HEAD"), "dirty": bool(git("status", "--porcelain"))}
