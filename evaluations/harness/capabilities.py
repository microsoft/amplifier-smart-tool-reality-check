"""How each capability is run in the evaluation environment, and where its output is."""

import json
from pathlib import Path
import shlex

from harness.tasks import Task

from reality_check.schemas import AgentProvider, ReasoningEffort


def command(task: Task, agent_provider: AgentProvider, model: str, reasoning_effort: ReasoningEffort) -> str:
    """The shell command that runs the task's capability, run from the user's project, its events on stdout."""
    match task.capability:
        case "check-software":
            arguments = [
                "reality-check",
                "check-software",
                "--request",
                task.request,
                *(["--target", task.target] if task.target else []),
                "--agent-provider",
                agent_provider,
                "--model",
                model,
                "--reasoning-effort",
                reasoning_effort,
                "--ask-first",
                "never",
                "--timeout-seconds",
                str(task.timeout_seconds),
            ]
    return shlex.join(arguments)


def events(stdout: Path) -> list[dict]:
    """The capability's events, one JSON object per line of its stdout; lines that are not JSON are skipped."""
    found: list[dict] = []
    if not stdout.is_file():
        return found
    for line in stdout.read_text(encoding="utf-8").splitlines():
        try:
            found.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return found


def output_directory(task: Task, found: list[dict]) -> str | None:
    """Where in the environment the capability kept its own record of the run, from its events."""
    match task.capability:
        case "check-software":
            started = next((event for event in found if event.get("kind") == "started"), None)
            return started["data"].get("directory") if started else None


def outcome(task: Task, found: list[dict]) -> dict:
    """How the capability ended, from its last event: its status, ids, and the error when it failed."""
    match task.capability:
        case "check-software":
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
