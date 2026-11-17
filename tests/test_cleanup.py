"""A check finds what its agent left running by the variable its agent's processes carry, records it, and stops it."""

from collections.abc import Generator, Iterator
import contextlib
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from typing import Any

from fakes import FakeIntelligence, FakeRun, finishes
import psutil
import pytest

from reality_check import lib, processes
from reality_check.capabilities.check_software import check, cleanup
from reality_check.capabilities.check_software.cleanup import clean_up, leftovers
from reality_check.capabilities.check_software.record import process_started, write_record
from reality_check.capabilities.check_software.registry import register_project
from reality_check.intelligence.schemas import AgentResult
from reality_check.processes import CHECK_ID_VARIABLE, found_process
from reality_check.schemas import CheckRecord

SLEEP = "import time; time.sleep(60)"
# Starts a sleeper in a session of its own, prints its pid, then sleeps or exits as its first argument says. The
# sleeper keeps the variable only when the second argument says so, as Chrome's processes do not show it.
STARTER = f"""
import os, subprocess, sys, time
detached = {{"start_new_session": True}} if sys.platform != "win32" else {{
    "creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
}}
environment = dict(os.environ)
if sys.argv[2] == "unmarked":
    environment.pop("{CHECK_ID_VARIABLE}")
sleeper = subprocess.Popen([sys.executable, "-c", "{SLEEP}"], env=environment, **detached)
print(sleeper.pid, flush=True)
if sys.argv[1] == "stays":
    time.sleep(60)
"""


class Started:
    """Processes a test starts, as an agent would, every one of them ended when the test ends."""

    def __init__(self) -> None:
        self.processes: list[psutil.Process] = []
        self._popens: list[subprocess.Popen[str]] = []

    def sleeper(self, marker: str | None) -> psutil.Process:
        return self._start(["-c", SLEEP], marker)

    def starter(self, marker: str, stays: bool, marked: bool) -> tuple[psutil.Process, psutil.Process]:
        """A process and the sleeper it starts in a session of its own; it exits at once unless it `stays`."""
        arguments = ["-c", STARTER, "stays" if stays else "exits", "marked" if marked else "unmarked"]
        parent = self._start(arguments, marker)
        stdout = self._popens[-1].stdout
        assert stdout is not None
        sleeper = psutil.Process(int(stdout.readline()))
        self.processes.append(sleeper)
        if not stays:
            self._popens[-1].wait()
        return parent, sleeper

    def close(self) -> None:
        for process in self.processes:
            with contextlib.suppress(psutil.Error):
                process.kill()
        for popen in self._popens:
            popen.wait()

    def _start(self, arguments: list[str], marker: str | None) -> psutil.Process:
        environment = {name: value for name, value in os.environ.items() if name != CHECK_ID_VARIABLE}
        if marker is not None:
            environment[CHECK_ID_VARIABLE] = marker
        popen = subprocess.Popen([sys.executable, *arguments], env=environment, stdout=subprocess.PIPE, text=True)
        self._popens.append(popen)
        process = psutil.Process(popen.pid)
        self.processes.append(process)
        return process


@pytest.fixture
def started() -> Generator[Started]:
    own = Started()
    yield own
    own.close()


def gone(process: psutil.Process) -> bool:
    try:
        return not process.is_running() or process.status() == psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return True


def leaves_processes(started: Started, spawned: dict[str, psutil.Process]) -> Any:
    """An agent that starts processes as agents do, some with its check's variable and some without, then ends."""

    async def script(run: FakeRun) -> AgentResult:
        marker = run.request.environment[CHECK_ID_VARIABLE]
        spawned["server"], spawned["browser"] = started.starter(marker, stays=True, marked=False)
        spawned["background"] = started.starter(marker, stays=False, marked=True)[1]
        spawned["unmarked"] = started.sleeper(None)
        spawned["other check"] = started.sleeper("20200101-000000-aaaaaa")
        return await finishes()(run)

    return script


def cleanup_of(run: lib.CheckRun) -> dict[str, Any]:
    return json.loads((run.directory / "cleanup.json").read_text(encoding="utf-8"))


async def test_what_the_agent_left_running_is_recorded_and_stopped(tmp_path: Path, started: Started) -> None:
    spawned: dict[str, psutil.Process] = {}
    fake = FakeIntelligence(leaves_processes(started, spawned))

    run = await lib.check_software("Check the shop", checks_directory=tmp_path, intelligence=fake)
    await run.result()
    events = [event async for event in run.events()]

    assert fake.runs[0].request.environment == {CHECK_ID_VARIABLE: run.check_id}
    left = {name: spawned[name] for name in ("server", "browser", "background")}
    assert all(gone(process) for process in left.values())
    assert not gone(spawned["unmarked"])
    assert not gone(spawned["other check"])
    cleanup = cleanup_of(run)
    assert cleanup["keep_running"] is False
    assert {entry["pid"]: entry["outcome"] for entry in cleanup["processes"]} == {
        process.pid: "stopped" for process in left.values()
    }
    server = next(entry for entry in cleanup["processes"] if entry["pid"] == spawned["server"].pid)
    assert server["name"] == spawned["unmarked"].name()
    assert server["command"][1:3] == ["-c", STARTER]
    assert server["cwd"] == str(Path.cwd())
    assert cleanup["problems"] == []
    assert f"is in {run.directory / 'cleanup.json'}." in events[-1].text


async def test_a_check_that_keeps_running_what_it_starts_only_records_it(tmp_path: Path, started: Started) -> None:
    spawned: dict[str, psutil.Process] = {}
    fake = FakeIntelligence(leaves_processes(started, spawned))

    run = await lib.check_software("Check the shop", checks_directory=tmp_path, keep_running=True, intelligence=fake)
    await run.result()

    assert not any(gone(process) for process in spawned.values())
    cleanup = cleanup_of(run)
    assert cleanup["keep_running"] is True
    assert {entry["outcome"] for entry in cleanup["processes"]} == {"left running"}
    assert len(cleanup["processes"]) == 3


async def test_a_check_whose_agent_left_nothing_writes_no_record(tmp_path: Path) -> None:
    run = await lib.check_software(
        "Check the shop", checks_directory=tmp_path, intelligence=FakeIntelligence(finishes())
    )
    await run.result()
    events = [event async for event in run.events()]

    assert not (run.directory / "cleanup.json").exists()
    assert "cleanup.json" not in events[-1].text


async def test_a_check_cleans_up_when_no_thread_can_start(
    tmp_path: Path, started: Started, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refused(**kwargs: Any) -> SimpleNamespace:
        def start() -> None:
            raise RuntimeError("can't start new thread")

        return SimpleNamespace(start=start)

    monkeypatch.setattr(check, "threading", SimpleNamespace(Thread=refused))
    spawned: list[psutil.Process] = []

    async def script(run: FakeRun) -> AgentResult:
        spawned.append(started.sleeper(run.request.environment[CHECK_ID_VARIABLE]))
        return await finishes()(run)

    run = await lib.check_software("Check the shop", checks_directory=tmp_path, intelligence=FakeIntelligence(script))
    await run.result()

    assert gone(spawned[0])
    assert [entry["outcome"] for entry in cleanup_of(run)["processes"]] == ["stopped"]


def test_a_process_that_took_over_a_found_pid_is_never_signalled(started: Started) -> None:
    process = started.sleeper("20260101-000000-abcdef")
    found = found_process(process)

    outcomes = processes.stop([found._replace(started=found.started - 100)])

    assert outcomes == {process.pid: "ended on its own; its pid is now another process's"}
    assert not gone(process)


def test_a_check_started_by_the_agent_is_never_taken_for_the_agent_s_own(tmp_path: Path, started: Started) -> None:
    marker = "20260101-000000-abcdef"
    nested = started.starter(marker, stays=True, marked=True)[0]
    own = started.sleeper(marker)
    checks = tmp_path / "checks"
    register_project(checks)
    (checks / "20260101-000001-abcdef").mkdir(parents=True)
    record = CheckRecord(
        check_id="20260101-000001-abcdef",
        request="Check the page",
        target=None,
        resume=None,
        ask_first="when-off",
        keep_running=False,
        agent_provider="copilot",
        model="gpt-6.1-sol",
        reasoning_effort=None,
        pid=nested.pid,
        pid_started=process_started(nested.pid),
    )
    write_record(checks / record.check_id, record)

    found = leftovers(check_id=marker, problems=[])

    assert [item.process.pid for item in found] == [own.pid]


def test_an_older_process_that_names_a_found_one_as_its_parent_is_not_taken_for_its_child(
    started: Started, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = "20260101-000000-abcdef"
    older = started.sleeper(None)
    parent = started.sleeper(marker)
    child = started.sleeper(None)
    listed = psutil.process_iter

    def process_iter(attrs: list[str]) -> Iterator[psutil.Process]:
        for process in listed(attrs):
            # As Windows lists processes whose parent ended once a newer process took over that parent's pid.
            if process.pid in (older.pid, child.pid):
                process.info["ppid"] = parent.pid
            if process.pid == older.pid:
                process.info["create_time"] -= 60
            yield process

    monkeypatch.setattr(psutil, "process_iter", process_iter)

    found = leftovers(check_id=marker, problems=[])

    assert {item.process.pid for item in found} == {parent.pid, child.pid}


def test_a_process_that_cannot_be_read_is_a_problem_and_the_others_are_still_stopped(
    tmp_path: Path, started: Started, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = "20260101-000000-abcdef"
    unreadable = started.sleeper(marker)
    readable = started.sleeper(marker)
    reads = cleanup.found_process

    def found_process(process: psutil.Process) -> processes.Found:
        if process.pid == unreadable.pid:
            raise psutil.AccessDenied(pid=process.pid)
        return reads(process)

    monkeypatch.setattr(cleanup, "found_process", found_process)

    path = clean_up(directory=tmp_path, check_id=marker, keep_running=False, browser_sessions=[], problems=[])

    assert path is not None
    recorded = json.loads(path.read_text(encoding="utf-8"))
    assert [(entry["pid"], entry["outcome"]) for entry in recorded["processes"]] == [(readable.pid, "stopped")]
    [problem] = recorded["problems"]
    assert problem.startswith(
        f"Process {unreadable.pid}, which the agent left running, could not be read: AccessDenied"
    )
    assert gone(readable)
    assert not gone(unreadable)
