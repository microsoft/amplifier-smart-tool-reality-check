"""What a check's agent left running when it ended: found, recorded, and stopped unless the check keeps it running.

Every process the agent starts carries the check's id in `CHECK_ID_VARIABLE`, which its children inherit. Agents start
commands in sessions and process groups of their own, so the variable, not the process tree, says what is the
check's.
"""

import contextlib
from pathlib import Path

import psutil
from pydantic import BaseModel, Field

from reality_check.capabilities.browser.prepare import BrowserSession
from reality_check.capabilities.check_software.checks import running_check_processes
from reality_check.capabilities.check_software.record import CLEANUP, write_atomically
from reality_check.capabilities.computer_use.daemon import started_pid
from reality_check.processes import (
    CHECK_ID_VARIABLE,
    START_TOLERANCE_SECONDS,
    Found,
    Leftover,
    describe,
    environment,
    found_process,
    running,
    stop,
)
from reality_check.schemas import RealityCheckError


class Cleanup(BaseModel):
    """What a check found still running once its agent ended, as its cleanup.json keeps it."""

    keep_running: bool
    processes: list[Leftover]
    browser_sessions: list[BrowserSession] = Field(description="Closed whether or not the check keeps the rest running")
    problems: list[str] = Field(description="What could not be cleaned up, and why")


def clean_up(
    directory: Path, check_id: str, keep_running: bool, browser_sessions: list[BrowserSession], problems: list[str]
) -> Path | None:
    """Record what the check's agent left running in cleanup.json, stopping it unless kept; None when nothing was."""
    processes: list[Leftover] = []
    problems = list(problems)
    try:
        found = leftovers(check_id=check_id, problems=problems)
        outcomes = {item.process.pid: "left running" for item in found} if keep_running else stop(found=found)
        processes = [item.leftover.model_copy(update={"outcome": outcomes[item.process.pid]}) for item in found]
    except Exception as error:  # whatever went wrong, the check still ends and says so
        problems.append(f"Looking for processes the agent left running failed: {describe(error)}")
    if not processes and not browser_sessions and not problems:
        return None
    path = directory / CLEANUP
    cleanup = Cleanup(
        keep_running=keep_running, processes=processes, browser_sessions=browser_sessions, problems=problems
    )
    write_atomically(path=path, text=cleanup.model_dump_json(indent=2))
    return path


def leftovers(check_id: str, problems: list[str]) -> list[Found]:
    """This user's processes that carry `check_id`, with their descendants; those that cannot be read go in `problems`.

    Never this process, its ancestors, the shared computer use daemon, or another check's processes, such as a check
    the agent started, with what runs under them.
    """
    this = psutil.Process()
    user = this.username()
    children: dict[int, list[psutil.Process]] = {}
    created: dict[int, float | None] = {}
    marked: list[psutil.Process] = []
    for process in psutil.process_iter(["ppid", "username", "create_time"]):
        children.setdefault(process.info["ppid"], []).append(process)
        created[process.pid] = process.info["create_time"]
        if process.info["username"] == user and environment(process).get(CHECK_ID_VARIABLE) == check_id:
            marked.append(process)
    if not marked:
        return []
    others: set[int] = set()
    if (daemon := started_pid()) is not None:
        others.add(daemon)
    # The registry is only how other checks are told apart; without it, this check's own are still found.
    with contextlib.suppress(RealityCheckError, OSError):
        others |= running_check_processes() - {this.pid}
    spared = {this.pid, *(parent.pid for parent in this.parents()), *others}
    found: dict[int, Found] = {}
    waiting = [process for process in marked if process.pid not in spared and not _under(process=process, pids=others)]
    while waiting:
        process = waiting.pop()
        if process.pid in found or not running(process):
            continue
        try:
            found[process.pid] = found_process(process)
        except psutil.NoSuchProcess:
            pass
        except psutil.Error as error:
            problems.append(
                f"Process {process.pid}, which the agent left running, could not be read: {describe(error)}"
            )
        for child in children.get(process.pid, []):
            # Chrome overwrites its own environment, so what runs under a found process is the check's too, unless
            # it says it is another check's.
            if (
                child.pid not in spared
                and _started_since(started=created[child.pid], parent_started=created[process.pid])
                and environment(child).get(CHECK_ID_VARIABLE) in (None, check_id)
            ):
                waiting.append(child)
    return sorted(found.values(), key=lambda item: item.process.pid)


def _started_since(started: float | None, parent_started: float | None) -> bool:
    """Whether a process started no earlier than its parent, allowing for rounding, as a child must have.

    Windows keeps the parent pid of a process whose parent ended, and reuses pids, so an older process can name a
    newer one as its parent.
    """
    return started is not None and parent_started is not None and started > parent_started - START_TOLERANCE_SECONDS


def _under(process: psutil.Process, pids: set[int]) -> bool:
    """Whether `process` runs under one of `pids`, such as a process another check started with this one's variable."""
    try:
        return any(parent.pid in pids for parent in process.parents())
    except psutil.Error:
        return False
