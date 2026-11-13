"""This user's processes: which carry a check's id, what they are, and stopping them safely."""

from datetime import UTC, datetime
from typing import NamedTuple

import psutil
from pydantic import BaseModel, Field

CHECK_ID_VARIABLE = "REALITY_CHECK_ID"
STOP_TIMEOUT_SECONDS = 5
KILL_TIMEOUT_SECONDS = 2
# A process's start time can differ by rounding between reads; a process that takes over a dead one's pid starts well
# after it.
START_TOLERANCE_SECONDS = 1.0


class Leftover(BaseModel):
    """A process the check's agent left running, and what the check did about it."""

    pid: int
    started_at: datetime
    name: str | None
    command: list[str] | None
    cwd: str | None = Field(description="Its working directory; None when it cannot be read")
    outcome: str = Field(description="stopped, killed, left running, or why it was not stopped")


class Found(NamedTuple):
    process: psutil.Process
    # In seconds since boot, so a process that later takes over its pid is never signalled.
    started: float
    leftover: Leftover


def stop(found: list[Found]) -> dict[int, str]:
    """End each process, killing those that outlast `STOP_TIMEOUT_SECONDS`; how each ended, by pid."""
    outcomes: dict[int, str] = {}
    terminated: list[psutil.Process] = []
    for item in found:
        pid = item.process.pid
        try:
            # Looked up again, so a pid another process took over since it was found is never signalled.
            current = psutil.Process(pid)
            if abs(since_boot(current) - item.started) >= START_TOLERANCE_SECONDS:
                outcomes[pid] = "ended on its own; its pid is now another process's"
                continue
            current.terminate()
            terminated.append(current)
        except psutil.NoSuchProcess:
            outcomes[pid] = "ended on its own"
        except psutil.Error as error:
            outcomes[pid] = f"not stopped: {describe(error)}"
    killed: list[psutil.Process] = []
    for process in _outlasting(processes=terminated, timeout=STOP_TIMEOUT_SECONDS, outcomes=outcomes, ended="stopped"):
        try:
            process.kill()
            killed.append(process)
        except psutil.NoSuchProcess:
            outcomes[process.pid] = "stopped"
        except psutil.Error as error:
            outcomes[process.pid] = f"not stopped: {describe(error)}"
    for process in _outlasting(processes=killed, timeout=KILL_TIMEOUT_SECONDS, outcomes=outcomes, ended="killed"):
        outcomes[process.pid] = "not stopped: still running after it was killed"
    return outcomes


def own_processes() -> list[psutil.Process]:
    """Every process of this process's user."""
    user = psutil.Process().username()
    return [process for process in psutil.process_iter(["username"]) if process.info["username"] == user]


def environment(process: psutil.Process) -> dict[str, str]:
    """The environment `process` started with; empty when it cannot be read."""
    try:
        return process.environ()
    except (psutil.Error, OSError):
        return {}


def describe(error: BaseException) -> str:
    """An error as a problem in cleanup.json says it."""
    return f"{type(error).__name__}: {error}"


def since_boot(process: psutil.Process) -> float:
    """When `process` started, in seconds since the machine booted."""
    # Relative to boot, because the wall-clock start time shifts with the boot time the platform reports, which WSL
    # moves by whole seconds between reads.
    return process.create_time() - psutil.boot_time()


def running(process: psutil.Process) -> bool:
    """Whether `process` has not ended; one that has and waits for its parent to collect it has nothing to stop."""
    try:
        return process.status() != psutil.STATUS_ZOMBIE
    except psutil.Error:
        return False


def found_process(process: psutil.Process) -> Found:
    """`process` as a leftover, with when it started, so it can be stopped safely later."""
    details = process.as_dict(["name", "cmdline", "cwd"])
    leftover = Leftover(
        pid=process.pid,
        started_at=datetime.fromtimestamp(process.create_time(), UTC),
        name=details["name"],
        command=details["cmdline"],
        cwd=details["cwd"],
        outcome="",
    )
    return Found(process=process, started=since_boot(process), leftover=leftover)


def _outlasting(
    processes: list[psutil.Process], timeout: float, outcomes: dict[int, str], ended: str
) -> list[psutil.Process]:
    """The processes still running after `timeout`; those that ended get `ended` as their outcome."""
    gone, alive = psutil.wait_procs(processes, timeout=timeout)
    for process in gone:
        outcomes[process.pid] = ended
    outlasting = []
    for process in alive:
        if running(process):
            outlasting.append(process)
        else:
            outcomes[process.pid] = ended
    return outlasting
