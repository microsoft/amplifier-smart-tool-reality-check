"""A baseline or installed run whose agent may have ended its turn while its CLI keeps running, for an operator.

An agent can leave a background process, such as `reality-check app`, that keeps its CLI running until the task's
timeout. `look` shows a running run's agent and what still runs under its CLI, from the twin, without changing it.
`stop` records the stop in the run's directory on the host, never in the twin, then ends the CLI as Ctrl+C does,
never the processes under it, which would wake the agent for another turn. The operator decides when.
"""

from datetime import UTC, datetime
import json
from pathlib import Path
import shlex
from typing import Any, NamedTuple

from common import baselines
from common.context import EvaluationError, RunRecord
from common.environment import PROJECT
from digital_twin_universe import lib as dtu
from digital_twin_universe.schemas import ExecResult

STOPPED = "stopped.json"
COMMAND_CHARACTERS = 160


class Process(NamedTuple):
    """A process in the twin, with the seconds it has run."""

    pid: int
    seconds: int
    command: str


class Look(NamedTuple):
    """A running run's agent, by its session, and its CLI's process with what runs under it."""

    turn: baselines.Turn
    cli: Process | None
    under: list[Process]


def batch(runs: Path, name: str | None) -> Path:
    """The batch directory `name` names, as a path or a name under `runs`, or the newest batch when it is None.

    A batch is a directory holding runs; its batch.json is only written once every run has ended.
    """
    if name is None:
        batches = sorted({path.parents[1] for path in runs.glob("*/*/run.json")})
        if not batches:
            raise EvaluationError(f"There is no batch in {runs}.")
        return batches[-1]
    for directory in (Path(name), runs / name):
        if any(directory.glob("*/run.json")):
            return directory
    raise EvaluationError(f"No batch {name!r}: give a batch directory, or the name of one in {runs}.")


def record(directory: Path) -> RunRecord:
    """The run's record, as its run.json has it now."""
    path = directory / "run.json"
    if not path.is_file():
        raise EvaluationError(f"No run in {directory}: it has no run.json.")
    return RunRecord.model_validate_json(path.read_text(encoding="utf-8"))


def running(directory: Path) -> list[RunRecord]:
    """The batch's baseline and installed runs whose CLI is running now."""
    records = [record(path.parent) for path in sorted(directory.glob("*/run.json"))]
    return [each for each in records if refusal(each) is None]


def refusal(run: RunRecord, look: Look | None = None, force: bool = False) -> str | None:
    """Why the run's CLI cannot be stopped, or None when it can.

    Without a `look`, only whether the run is running a CLI; with one, also whether its agent has ended its turn, which
    `force` overrides.
    """
    if run.spec.capability not in ("baseline", "installed"):
        return f"{run.run_id} is a {run.spec.capability} run; only a baseline or installed run runs the agent's CLI."
    if run.status != "running" or run.step != "capability":
        return f"{run.run_id} is not running its CLI: it is {run.status}, at the {run.step or 'first'} step."
    if not run.universe_id or not run.outcome.get("session_id"):
        return f"{run.run_id} has not recorded its universe and session yet."
    if look is None:
        return None
    if look.cli is None:
        return f"{run.run_id} has no {run.spec.agent_provider} process running in {run.universe_id}."
    if look.turn.ended is None and not force:
        return f"{run.run_id}'s agent has not ended its turn; give --force to stop it anyway."
    return None


def look(run: RunRecord) -> Look:
    """Read, from the run's twin, its agent's latest session records and the processes under its CLI."""
    cli = baselines.baseline(run.spec.agent_provider)
    session_id = str(run.outcome["session_id"])
    universe = str(run.universe_id)
    records = []
    for line in _execute(universe, cli.session(session_id)).stdout.splitlines():
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    found = _execute(universe, f"pgrep -o -f {shlex.quote(cli.process(session_id))}").stdout.split()
    listed = _execute(universe, "ps -eo pid=,ppid=,etimes=,args= -ww").stdout
    cli_process, under = processes(listed, int(found[0]) if found else None)
    return Look(turn=cli.turn([record for record in records if isinstance(record, dict)]), cli=cli_process, under=under)


def processes(listed: str, pid: int | None) -> tuple[Process | None, list[Process]]:
    """From `ps -eo pid=,ppid=,etimes=,args=`, the process `pid` and every process under it."""
    rows: dict[int, tuple[int, Process]] = {}
    for line in listed.splitlines():
        match line.split(maxsplit=3):
            case [each, parent, seconds, command] if each.isdigit() and parent.isdigit() and seconds.isdigit():
                rows[int(each)] = (int(parent), Process(pid=int(each), seconds=int(seconds), command=command))
    if pid is None or pid not in rows:
        return None, []
    under: list[Process] = []
    parents = {pid}
    while True:
        children = [process for parent, process in rows.values() if parent in parents and process.pid not in parents]
        if not children:
            break
        under.extend(children)
        parents |= {process.pid for process in children}
    return rows[pid][1], sorted(under)


def describe(run: RunRecord, seen: Look, now: datetime) -> str:
    """What `run.py waiting` prints for one run."""
    if seen.turn.ended is not None:
        state = f"ended its turn {_duration((now - seen.turn.ended).total_seconds())} ago"
    elif seen.turn.active is not None:
        state = f"working, last active {_duration((now - seen.turn.active).total_seconds())} ago"
    else:
        state = "working, with no session records yet"
    lines = [f"{run.run_id}: {state}"]
    if seen.cli is None:
        lines.append(f"  no {run.spec.agent_provider} process is running")
    else:
        lines.append(f"  cli  {_process(seen.cli)}")
        lines.extend(f"  under {_process(process)}" for process in seen.under)
    return "\n".join(lines)


def stop(directory: Path, force: bool = False) -> dict[str, Any]:
    """Write the run's `stopped.json` on the host, then send SIGTERM to its CLI in the twin, and return what it wrote.

    Refuses when the run is not running its CLI, when it was stopped already, or, without `force`, when its agent has
    not ended its turn.
    """
    run = record(directory)
    if (directory / STOPPED).is_file():
        raise EvaluationError(f"{run.run_id} was stopped already; see {directory / STOPPED}.")
    reason = refusal(run)
    if reason is not None:
        raise EvaluationError(reason)
    seen = look(run)
    reason = refusal(run, seen, force)
    if reason is not None or seen.cli is None:
        raise EvaluationError(reason or f"{run.run_id} has no CLI process to stop.")
    now = datetime.now(UTC)
    written = {
        "by": "operator",
        "at": now.isoformat(),
        "forced": seen.turn.ended is None,
        "idle_seconds": round((now - seen.turn.ended).total_seconds(), 1) if seen.turn.ended else None,
        "cli": seen.cli._asdict(),
        "running": [process._asdict() for process in seen.under],
    }
    (directory / STOPPED).write_text(json.dumps(written, indent=2), encoding="utf-8")
    signalled = _execute(str(run.universe_id), f"kill -TERM {seen.cli.pid}")
    if signalled.exit_code != 0:
        (directory / STOPPED).unlink()
        raise EvaluationError(f"SIGTERM to {seen.cli.pid} in {run.universe_id} failed: {signalled.stderr.strip()}")
    return written


def read_stop(directory: Path, worked: tuple[datetime, datetime] | None) -> tuple[dict[str, Any], float | None] | None:
    """A stopped run's stop and capability seconds, or None when the run was not stopped.

    The capability ends at the agent's last event before the stop, `worked`'s end, and the idle seconds are recomputed
    from it to the stop; without `worked`, they stay as measured at the stop and the seconds are unknown.
    """
    path = directory / STOPPED
    if not path.is_file():
        return None
    stopped = json.loads(path.read_text(encoding="utf-8"))
    if worked is None:
        return stopped, None
    started, ended = worked
    idle_seconds = (datetime.fromisoformat(stopped["at"]) - ended).total_seconds()
    return stopped | {"idle_seconds": round(idle_seconds, 1)}, round((ended - started).total_seconds(), 1)


def _execute(universe: str, command: str) -> ExecResult:
    try:
        return dtu.execute(universe, command, workdir=PROJECT, timeout_seconds=60)
    except dtu.DigitalTwinUniverseError as error:
        raise EvaluationError(f"{universe} could not be reached: {error}") from error


def _process(process: Process) -> str:
    command = process.command
    if len(command) > COMMAND_CHARACTERS:
        command = command[: COMMAND_CHARACTERS - 3] + "..."
    return f"{process.pid:>7}  {_duration(process.seconds):>9}  {command}"


def _duration(seconds: float) -> str:
    minutes, rest = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m{rest:02d}s" if hours else f"{minutes}m{rest:02d}s"
