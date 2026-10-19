"""Runs `reality-check check-software` in the twin from the user's project, and reads what it reported."""

from datetime import datetime
import json
from pathlib import Path
import shlex
from typing import Any

from common import usage
from common.context import RunContext
from common.environment import PROJECT, Environment
from pydantic import BaseModel

from reality_check.schemas import AskFirst

# Time past the capability's own timeout for it to stop and write its record.
GRACE_SECONDS = 600


class CapabilityResult(BaseModel):
    """What one capability run reported."""

    events: list[dict[str, Any]]
    outcome: dict[str, Any]
    seconds: float | None
    usage: dict[str, Any]
    record_directory: str | None


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
    directory = started["data"].get("directory") if started else None
    result = CapabilityResult(
        events=found,
        outcome=_outcome(found) | {"exit_code": ran.exit_code},
        seconds=seconds,
        usage=usage.summarize(found),
        record_directory=in_project(directory),
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
