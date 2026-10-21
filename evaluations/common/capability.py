"""Runs the run's capability in the twin from the user's project, and reads what it reported.

The capability is `reality-check check-software`, or the baseline: the agent provider's own CLI given the request.
"""

from datetime import datetime
import json
from pathlib import Path
import shlex
from typing import Any
import uuid

from common import baselines, usage
from common.context import RunContext
from common.environment import PROJECT, Environment
from pydantic import BaseModel, Field

from reality_check.schemas import AskFirst

# Time past the capability's own timeout for it to stop and write its record.
GRACE_SECONDS = 600
# The exit code of `timeout` when it stopped the command.
TIMED_OUT = 124


class CapabilityResult(BaseModel):
    """What one capability run reported."""

    events: list[dict[str, Any]]
    outcome: dict[str, Any]
    seconds: float | None
    usage: dict[str, Any]
    record_directory: str | None
    report: str | None = Field(description="The report's path in the twin; None when it is only in the run")
    where: dict[str, str] = Field(description="What else the capability left in the twin, label to path, for the judge")


def run(
    env: Environment,
    context: RunContext,
    request: str,
    target: str | None = None,
    timeout_seconds: int = 3600,
    ask_first: AskFirst = "never",
    previous_checks: list[str] | None = None,
    keep_running: bool = False,
    resume: str | None = None,
    checks_directory: str | None = None,
) -> CapabilityResult:
    """Run the run's capability on `request` and record how it ended.

    reality-check gets every argument. The baseline gets the request with the target added, and the timeout; the rest
    are reality-check's own.
    """
    match context.spec.capability:
        case "reality-check":
            return check_software(
                env,
                context,
                request,
                target=target,
                timeout_seconds=timeout_seconds,
                ask_first=ask_first,
                previous_checks=previous_checks,
                keep_running=keep_running,
                resume=resume,
                checks_directory=checks_directory,
            )
        case "baseline":
            return baseline(env, context, request, target=target, timeout_seconds=timeout_seconds)


def check_software(
    env: Environment,
    context: RunContext,
    request: str,
    target: str | None = None,
    timeout_seconds: int = 3600,
    ask_first: AskFirst = "never",
    previous_checks: list[str] | None = None,
    keep_running: bool = False,
    resume: str | None = None,
    checks_directory: str | None = None,
) -> CapabilityResult:
    """Run one check with the run's agent provider, model, and reasoning effort, and record how it ended.

    Writes `events.jsonl` and `logs/capability.stderr`, and fills the record's outcome, capability time, and usage.
    """
    arguments = [
        "reality-check",
        "check-software",
        "--request",
        request,
        *(["--target", target] if target else []),
        *(["--resume", resume] if resume else []),
        *[argument for path in previous_checks or [] for argument in ("--previous-checks", path)],
        "--ask-first",
        ask_first,
        *(["--keep-running"] if keep_running else []),
        *(["--checks-directory", checks_directory] if checks_directory else []),
        "--agent-provider",
        context.spec.agent_provider,
        "--model",
        context.spec.model,
        "--reasoning-effort",
        context.spec.reasoning_effort,
        "--timeout-seconds",
        str(timeout_seconds),
    ]
    context.record.capability = "check-software"
    ran = env.capture("capability", shlex.join(arguments), timeout_seconds=timeout_seconds + GRACE_SECONDS)
    (context.directory / "events.jsonl").write_text(ran.stdout, encoding="utf-8")
    (context.directory / "logs" / "capability.stderr").write_text(ran.stderr, encoding="utf-8")
    found = events(context.directory / "events.jsonl")
    seconds = None
    if len(found) >= 2:
        first = datetime.fromisoformat(found[0]["time"])
        last = datetime.fromisoformat(found[-1]["time"])
        seconds = round((last - first).total_seconds(), 1)
    started = next((event for event in found if event.get("kind") == "started"), None)
    directory = in_project(started["data"].get("directory") if started else None)
    result = CapabilityResult(
        events=found,
        outcome=_outcome(found) | {"exit_code": ran.exit_code},
        seconds=seconds,
        usage=usage.summarize(found),
        record_directory=directory,
        report=f"{directory}/report.md" if directory else None,
        where={
            "Its record of the run, with `check.json`, its events in `events.jsonl`, and the evidence it gathered in "
            "`evidence/`": directory or "(the capability left no record)"
        },
    )
    context.record.outcome = result.outcome
    context.record.capability_seconds = result.seconds
    context.record.usage["capability"] = result.usage
    return result


def baseline(
    env: Environment, context: RunContext, request: str, target: str | None = None, timeout_seconds: int = 3600
) -> CapabilityResult:
    """Give the request to the agent provider's own CLI, with every tool, path, and URL allowed, and read what it did.

    Writes `events.jsonl`, `report.md` from its last message, and `logs/capability.stderr`, and fills the record's
    outcome, capability time, and usage.
    """
    cli = baselines.baseline(context.spec.agent_provider)
    session_id = str(uuid.uuid4())
    arguments = cli.command(
        baselines.prompt(request, target), context.spec.model, context.spec.reasoning_effort, session_id
    )
    context.record.capability = "baseline"
    ran = env.capture(
        "capability",
        f"timeout --kill-after=30 {timeout_seconds} {shlex.join(arguments)}",
        timeout_seconds=timeout_seconds + GRACE_SECONDS,
    )
    (context.directory / "events.jsonl").write_text(ran.stdout, encoding="utf-8")
    (context.directory / "logs" / "capability.stderr").write_text(ran.stderr, encoding="utf-8")
    found = events(context.directory / "events.jsonl")
    reading = cli.read(found, ran.stderr)
    session = str(reading.outcome.get("session_id") or session_id)
    outcome = reading.outcome | {"session_id": session, "exit_code": ran.exit_code}
    if ran.exit_code == TIMED_OUT:
        outcome |= {"status": "timed-out", "error": f"the CLI ran past {timeout_seconds} seconds and was stopped"}
    if reading.report:
        (context.directory / "report.md").write_text(reading.report, encoding="utf-8")
    records = env.capture("capability-usage", cli.usage(session), timeout_seconds=300)
    result = CapabilityResult(
        events=found,
        outcome=outcome,
        seconds=reading.seconds,
        usage=cli.read_usage(records.stdout),
        record_directory=None,
        report=None,
        where={},
    )
    context.record.outcome = result.outcome
    context.record.capability_seconds = result.seconds
    context.record.usage["capability"] = result.usage
    return result


def events(stdout: Path) -> list[dict[str, Any]]:
    """Events, one JSON object per line of `stdout`; lines that are not JSON are skipped."""
    found: list[dict[str, Any]] = []
    if not stdout.is_file():
        return found
    for line in stdout.read_text(encoding="utf-8").splitlines():
        try:
            found.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return found


def in_project(path: str | None) -> str | None:
    """A path the capability reported, which is relative to the project it ran in, made absolute."""
    if path is None:
        return None
    return path if path.startswith("/") else f"{PROJECT}/{path}"


def _outcome(found: list[dict[str, Any]]) -> dict[str, Any]:
    """How the check ended, from its last event: its status, ids, and the error when it failed."""
    last = found[-1] if found else {}
    match last.get("kind"):
        case "finished":
            data = last["data"]
            return {"status": data["status"], "check_id": data["check_id"], "session_id": data["session_id"]}
        case "failed":
            data = last["data"]
            result = data.get("result") or {}
            return {
                "status": "failed",
                "check_id": last.get("check_id"),
                "session_id": result.get("session_id"),
                "error": f"{data.get('code')}: {data.get('message')}",
            }
        case _:
            return {
                "status": "failed",
                "check_id": last.get("check_id"),
                "error": "the check ended without a finished or failed event",
            }
