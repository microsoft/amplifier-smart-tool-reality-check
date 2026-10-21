"""The baseline: a task's request given to the agent provider's own CLI, with nothing of reality-check installed.

Each agent provider the baseline runs has an entry in BASELINES: how to install its CLI at the version reality-check's
own runtime for that provider uses, the command line that runs a request with no approvals, and how to read what the
CLI printed and kept. A provider is added with its entry; tasks do not change.
"""

from collections.abc import Callable
from datetime import datetime
import functools
import json
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import tomllib
from typing import Any, NamedTuple

from common import usage
from common.context import EvaluationError

from reality_check.schemas import AgentProvider, ReasoningEffort

REPOSITORY = Path(__file__).resolve().parents[2]


class Reading(NamedTuple):
    """What the CLI's output says: how it ended, its report, and its wall clock from its first event to its last."""

    outcome: dict[str, Any]
    report: str
    seconds: float | None


class Pin(NamedTuple):
    """The CLI version to install, and what pins it, such as the SDK version reality-check's install resolves."""

    version: str
    pinned_by: dict[str, str]


class Baseline(NamedTuple):
    """How the baseline installs, runs, and reads one agent provider's own CLI."""

    pin: Callable[[], Pin]  # the version reality-check's own runtime for the provider uses
    install: Callable[[str], str]  # shell that installs that version in the twin, as its user would
    version: str  # shell that prints the installed CLI's version
    command: Callable[[str, str, ReasoningEffort, str], list[str]]  # prompt, model, effort, a new session id
    read: Callable[[list[dict[str, Any]], str], Reading]  # the events it printed and its stderr
    usage: Callable[[str], str]  # shell that prints, for a session id, the records its usage is read from
    read_usage: Callable[[str], dict[str, Any]]  # that output, summed as `usage.summarize` does


def prompt(request: str, target: str | None) -> str:
    """What the baseline is given: the task's request, and its target when it has one."""
    return f"{request}\n\nTarget: {target}" if target else request


def baseline(name: AgentProvider) -> Baseline:
    """The named provider's baseline, or a failure naming the ones there are."""
    if name not in BASELINES:
        raise EvaluationError(
            f"The baseline cannot run {name} yet; it runs: {', '.join(BASELINES)}. Add {name}'s entry to BASELINES "
            "in evaluations/common/baselines.py."
        )
    return BASELINES[name]


@functools.cache
def _copilot_pin() -> Pin:
    """The Copilot CLI version that the github-copilot-sdk reality-check's copilot extra resolves to pins.

    Resolved on the host the way `uv tool install` resolves it in the twin, so nothing of it enters the twin. The SDK
    downloads exactly this release of github/copilot-cli as its runtime.
    """
    requirement = _extra_requirement("copilot", "github-copilot-sdk")
    script = (
        "from importlib.metadata import version; from copilot._cli_version import CLI_VERSION; "
        "print(version('github-copilot-sdk'), CLI_VERSION)"
    )
    with tempfile.TemporaryDirectory() as scratch:
        read = subprocess.run(
            [
                "uv",
                "run",
                "--no-config",
                "--no-project",
                "--isolated",
                "--refresh-package",
                "github-copilot-sdk",
                "--with",
                requirement,
                "python",
                "-c",
                script,
            ],
            cwd=scratch,
            capture_output=True,
            text=True,
        )
    match read.stdout.split():
        case [sdk, cli] if read.returncode == 0 and cli != "None":
            return Pin(version=cli, pinned_by={"github-copilot-sdk": sdk})
        case _:
            raise EvaluationError(
                f"The Copilot CLI version {requirement} pins could not be read: {read.stderr.strip()[-500:]}"
            )


def _extra_requirement(extra: str, package: str) -> str:
    """`package`'s requirement in reality-check's `extra`, from the checkout's pyproject.toml."""
    with (REPOSITORY / "pyproject.toml").open("rb") as file:
        extras = tomllib.load(file)["project"]["optional-dependencies"]
    found = [line for line in extras.get(extra, []) if re.split(r"[\s<>=!~;@\[]", line, maxsplit=1)[0] == package]
    if not found:
        raise EvaluationError(f"reality-check's {extra} extra has no {package} requirement.")
    return found[0]


def _copilot_command(text: str, model: str, reasoning_effort: ReasoningEffort, session_id: str) -> list[str]:
    # The pinned version, not one the CLI would update itself to, and no approvals or questions, as `--ask-first
    # never` runs reality-check.
    return [
        "copilot",
        "-p",
        text,
        "--model",
        model,
        "--reasoning-effort",
        reasoning_effort,
        "--allow-all",
        "--no-ask-user",
        "--no-auto-update",
        "--output-format",
        "json",
        "--session-id",
        session_id,
    ]


def _copilot_read(found: list[dict[str, Any]], stderr: str) -> Reading:
    """Copilot's `--output-format json` events: a `result` event ends a run, and the last assistant message reports."""
    messages = [
        event["data"]["content"]
        for event in found
        if event.get("type") == "assistant.message" and (event.get("data") or {}).get("content")
    ]
    times = [datetime.fromisoformat(event["timestamp"]) for event in found if event.get("timestamp")]
    seconds = round((times[-1] - times[0]).total_seconds(), 1) if len(times) >= 2 else None
    result = next((event for event in reversed(found) if event.get("type") == "result"), None)
    errors = [
        (event.get("data") or {}).get("message") for event in found if event.get("type") == "session.error"
    ]
    lines = [line for line in stderr.splitlines() if line.strip()]
    error = next((message for message in reversed(errors) if message), None) or (lines[-1] if lines else None)
    if result is None:
        outcome = {"status": "failed", "session_id": None, "error": error or "the CLI ended without a result event"}
    elif result.get("exitCode") == 0:
        outcome = {"status": "done", "session_id": result.get("sessionId")}
    else:
        outcome = {
            "status": "failed",
            "session_id": result.get("sessionId"),
            "error": error or f"the CLI's result has exit code {result.get('exitCode')}",
        }
    return Reading(outcome=outcome, report=messages[-1] if messages else "", seconds=seconds)


def _copilot_usage(session_id: str) -> str:
    events = f"~/.copilot/session-state/{shlex.quote(session_id)}/events.jsonl"
    return f"grep -h '\"type\":\"session.usage_record\"' {events} || true"


def _copilot_read_usage(records: str) -> dict[str, Any]:
    """The session's `session.usage_record` events, one per model call, as reality-check's `usage` events.

    Its printed events carry no tokens, and the session keeps a record for every call even when the run is killed.
    """
    calls: list[dict[str, Any]] = []
    for line in records.splitlines():
        try:
            record = json.loads(line)["data"]["usage"]
        except (json.JSONDecodeError, KeyError, TypeError):
            continue
        data = {
            "model": record.get("model"),
            "input_tokens": record.get("inputTokens"),
            "output_tokens": record.get("outputTokens"),
            "cache_read_tokens": record.get("cacheReadTokens"),
            "cache_write_tokens": record.get("cacheWriteTokens"),
            "reasoning_tokens": record.get("reasoningTokens"),
            "cost": record.get("cost"),
            "copilot_usage": record.get("copilotUsage"),
        }
        calls.append({"kind": "usage", "data": data})
    return usage.summarize(calls)


BASELINES: dict[AgentProvider, Baseline] = {
    "copilot": Baseline(
        pin=_copilot_pin,
        # The install script github/copilot-cli's README gives a user, with the version pinned.
        install=lambda version: f"curl -fsSL https://gh.io/copilot-install | VERSION={shlex.quote(version)} bash",
        version="copilot --version",
        command=_copilot_command,
        read=_copilot_read,
        usage=_copilot_usage,
        read_usage=_copilot_read_usage,
    ),
}
