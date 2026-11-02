"""The baseline: a task's request given to the agent provider's own CLI, with nothing of reality-check installed.

Each agent provider the baseline runs has an entry in BASELINES: how to install its CLI at the version reality-check's
own runtime for that provider uses, the command line that runs a request with no approvals, how to read what the
CLI printed and kept, and how to see, while it runs, whether its agent has ended its turn. A provider is added with its
entry; tasks do not change.
"""

from collections.abc import Callable
from datetime import datetime
import functools
import itertools
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
from common.environment import HOME

from reality_check.schemas import AgentProvider, ReasoningEffort

REPOSITORY = Path(__file__).resolve().parents[2]


class Reading(NamedTuple):
    """What the CLI's output says: how it ended, its report, and its wall clock from its first event to its last."""

    outcome: dict[str, Any]
    report: str
    seconds: float | None


class Turn(NamedTuple):
    """Where the agent is, by its session's latest records."""

    ended: datetime | None  # when it ended its turn; None while it works
    active: datetime | None  # the time of its latest record


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
    skills: str  # directory in the twin the CLI loads a user's own skills from
    session: Callable[[str], str]  # shell that prints, for a session id, its session's latest records
    turn: Callable[[list[dict[str, Any]]], Turn]  # those records, read
    process: Callable[[str], str]  # `pgrep -f` pattern of the CLI's own process, for a session id
    # The times of its first printed event and its last before a stop, leaving out what the stop printed.
    worked: Callable[[list[dict[str, Any]]], tuple[datetime, datetime] | None]


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

    The SDK downloads exactly this release of github/copilot-cli as its runtime.
    """
    return _sdk_pin("copilot", "github-copilot-sdk", "copilot._cli_version", "CLI_VERSION")


@functools.cache
def _claude_pin() -> Pin:
    """The Claude Code version that the claude-agent-sdk reality-check's claude extra resolves to bundles."""
    return _sdk_pin("claude", "claude-agent-sdk", "claude_agent_sdk._cli_version", "__cli_version__")


def _sdk_pin(extra: str, package: str, module: str, name: str) -> Pin:
    """The CLI version `module.name` holds in the `package` that reality-check's `extra` resolves to.

    Resolved on the host the way `uv tool install` resolves it in the twin, so nothing of it enters the twin.
    """
    requirement = _extra_requirement(extra, package)
    script = f"from importlib.metadata import version; from {module} import {name}; print(version({package!r}), {name})"
    with tempfile.TemporaryDirectory() as scratch:
        read = subprocess.run(
            [
                "uv",
                "run",
                "--no-config",
                "--no-project",
                "--isolated",
                "--refresh-package",
                package,
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
            return Pin(version=cli, pinned_by={package: sdk})
        case _:
            raise EvaluationError(f"The CLI version {requirement} pins could not be read: {read.stderr.strip()[-500:]}")


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
    errors = [(event.get("data") or {}).get("message") for event in found if event.get("type") == "session.error"]
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
    return f'grep -h \'"type":"session.usage_record"\' {events} || true'


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


def _copilot_session(session_id: str) -> str:
    return f"tail -n 20 ~/.copilot/session-state/{shlex.quote(session_id)}/events.jsonl"


def _copilot_turn(records: list[dict[str, Any]]) -> Turn:
    """Copilot's session: its turn has ended when only what it writes as it goes idle follows its last turn end.

    That is a `session.usage_checkpoint`, and `session.shutdown` as it exits; another turn starts with
    `assistant.turn_start`, and a background shell that exits wakes it with a `system.notification`.
    """
    timed = [record for record in records if record.get("timestamp")]
    if not timed:
        return Turn(ended=None, active=None)
    ends = [record for record in timed if record.get("type") == "assistant.turn_end"]
    idle = timed[-1].get("type") in ("assistant.turn_end", "session.usage_checkpoint", "session.shutdown")
    return Turn(ended=_time(ends[-1]) if ends and idle else None, active=_time(timed[-1]))


def _copilot_worked(found: list[dict[str, Any]]) -> tuple[datetime, datetime] | None:
    """Its events up to a stop's `abort`, which the stop's aborted `assistant.idle` and `result` follow.

    `session.background_tasks_changed` is left out too: a background shell prints it whenever it changes, with the agent
    idle or not.
    """
    before = itertools.takewhile(lambda event: event.get("type") != "abort", found)
    times = [
        _time(event)
        for event in before
        if event.get("timestamp") and event.get("type") != "session.background_tasks_changed"
    ]
    return (times[0], times[-1]) if times else None


def _time(record: dict[str, Any]) -> datetime:
    return datetime.fromisoformat(record["timestamp"])


def _claude_command(text: str, model: str, reasoning_effort: ReasoningEffort, session_id: str) -> list[str]:
    # `--effort` takes reality-check's efforts as they are. The pinned version and no approvals, as for copilot, and
    # stream-json with --verbose, as the SDK runs it.
    return [
        "claude",
        "-p",
        text,
        "--model",
        model,
        "--effort",
        reasoning_effort,
        "--dangerously-skip-permissions",
        "--settings",
        json.dumps({"env": {"DISABLE_AUTOUPDATER": "1"}}),
        "--output-format",
        "stream-json",
        "--verbose",
        "--session-id",
        session_id,
    ]


def _claude_read(found: list[dict[str, Any]], stderr: str) -> Reading:
    """Claude Code's `--output-format stream-json` events: a `result` event ends a run, and its last text reports.

    Only its messages carry a time, so without two of them the time is the result's own duration.
    """
    texts = [
        "".join(block.get("text", "") for block in event["message"]["content"] if block.get("type") == "text")
        for event in found
        if event.get("type") == "assistant"
        and not event.get("parent_tool_use_id")
        and isinstance((event.get("message") or {}).get("content"), list)
    ]
    messages = [text for text in texts if text]
    result = next((event for event in reversed(found) if event.get("type") == "result"), None)
    times = [datetime.fromisoformat(event["timestamp"]) for event in found if event.get("timestamp")]
    if len(times) >= 2:
        seconds = round((times[-1] - times[0]).total_seconds(), 1)
    elif result is not None and result.get("duration_ms") is not None:
        seconds = round(result["duration_ms"] / 1000, 1)
    else:
        seconds = None
    lines = [line for line in stderr.splitlines() if line.strip()]
    if result is None:
        error = lines[-1] if lines else "the CLI ended without a result event"
        outcome = {"status": "failed", "session_id": None, "error": error}
    elif not result.get("is_error") and result.get("subtype") == "success":
        outcome = {"status": "done", "session_id": result.get("session_id")}
    else:
        errors = [*(result.get("errors") or []), result.get("result"), *lines[-1:]]
        error = next((message for message in errors if message), f"the CLI's result is {result.get('subtype')}")
        outcome = {"status": "failed", "session_id": result.get("session_id"), "error": error}
    final = result.get("result") if result is not None and outcome["status"] == "done" else None
    return Reading(outcome=outcome, report=final or (messages[-1] if messages else ""), seconds=seconds)


def _claude_usage(session_id: str) -> str:
    # The session's transcript, and its subagents' beside it, in the folder of the project it ran in.
    session = f"~/.claude/projects/*/{shlex.quote(session_id)}"
    return (
        f'{{ grep -h \'"type":"assistant"\' {session}.jsonl {session}/subagents/*.jsonl; '
        f'grep -h \'"type":"cost-state"\' {session}.jsonl | tail -n 1; }} 2>/dev/null || true'
    )


def _claude_read_usage(records: str) -> dict[str, Any]:
    """The session's assistant messages, one per model call, as reality-check's `usage` events, and its cost.

    A message with several content blocks is a line for each, so a call is counted once, by its message id. The cost
    is the session's own by model, from its last `cost-state` record, which it writes as it ends.
    """
    calls: dict[str, dict[str, Any]] = {}
    costs: dict[str, Any] = {}
    for line in records.splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        if record.get("type") == "cost-state":
            costs = {model: each.get("costUSD") for model, each in (record.get("modelUsage") or {}).items()}
            continue
        message = record.get("message")
        if not isinstance(message, dict) or not isinstance(message.get("usage"), dict):
            continue
        called = message["usage"]
        data = {
            "model": message.get("model"),
            "input_tokens": called.get("input_tokens"),
            "output_tokens": called.get("output_tokens"),
            "cache_read_tokens": called.get("cache_read_input_tokens"),
            "cache_write_tokens": called.get("cache_creation_input_tokens"),
            "reasoning_tokens": (called.get("output_tokens_details") or {}).get("thinking_tokens"),
        }
        calls[message.get("id") or record.get("uuid") or line] = {"kind": "usage", "data": data}
    summary = usage.summarize(list(calls.values()))
    for model, dollars in costs.items():
        if dollars is not None:
            summary["usd"] = summary.get("usd", 0) + dollars
            summary["by_model"].setdefault(model, {})["usd"] = dollars
    return summary


def _claude_session(session_id: str) -> str:
    transcript = f"~/.claude/projects/*/{shlex.quote(session_id)}.jsonl"
    return f'grep -h -e \'"type":"assistant"\' -e \'"type":"user"\' {transcript} | tail -n 5'


def _claude_turn(records: list[dict[str, Any]]) -> Turn:
    """Claude Code's transcript: its turn has ended when its last message is the agent's, stopped with `end_turn`.

    A tool call stops with `tool_use`, and its result is a user message.
    """
    messages = [record for record in records if record.get("type") in ("assistant", "user") and record.get("timestamp")]
    if not messages:
        return Turn(ended=None, active=None)
    last = messages[-1]
    ended = last["type"] == "assistant" and (last.get("message") or {}).get("stop_reason") == "end_turn"
    return Turn(ended=_time(last) if ended else None, active=_time(last))


def _claude_worked(found: list[dict[str, Any]]) -> tuple[datetime, datetime] | None:
    """Its timed events; a stop prints only its result, which it printed already, and untimed task notifications."""
    times = [_time(event) for event in found if event.get("timestamp")]
    return (times[0], times[-1]) if times else None


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
        skills=f"{HOME}/.agents/skills",
        session=_copilot_session,
        turn=_copilot_turn,
        process=lambda session_id: f"^([^ ]*/)?copilot -p .* --session-id {session_id}$",
        worked=_copilot_worked,
    ),
    "claude": Baseline(
        pin=_claude_pin,
        # The native install Claude Code's setup docs give a user, with the version pinned.
        install=lambda version: f"curl -fsSL https://claude.ai/install.sh | bash -s {shlex.quote(version)}",
        version="claude --version",
        command=_claude_command,
        read=_claude_read,
        usage=_claude_usage,
        read_usage=_claude_read_usage,
        skills=f"{HOME}/.claude/skills",
        session=_claude_session,
        turn=_claude_turn,
        process=lambda session_id: f"^([^ ]*/)?claude -p .* --session-id {session_id}$",
        worked=_claude_worked,
    ),
}
