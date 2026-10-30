"""Readies computer use for checks against a fake cua-driver: the daemon's lifetime, the agent's shim, the prompt."""

import asyncio
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any

from fakes import FakeIntelligence, fails, finishes, waits_for_steering, works_forever
from fakes import Unavailable as UnstartableAgent
import pytest

from reality_check import lib
from reality_check.capabilities.check_software import check
from reality_check.capabilities.computer_use import daemon, prepare
from reality_check.capabilities.computer_use.prepare import ComputerUse, NotInstalled, prepare_computer_use
from reality_check.capabilities.computer_use.shim import write_shim
from reality_check.capabilities.computer_use.target import Target, Unavailable, run_driver
from reality_check.schemas import AskFirst, RealityCheckError

WSL = Target("wsl", "windows-x86_64-binary", "zip")
LINUX = Target("linux", "linux-x86_64-binary", "tar.gz")
WINDOWS = Target("windows", "windows-x86_64-binary", "zip")
MACOS = Target("macos", "darwin-universal", "tar.gz")
EXECUTABLE = Path("/mnt/c/cua/cua-driver.exe")
HEALTHY = [
    {"name": "ax_capability", "status": "pass"},
    {"name": "tcc_accessibility", "status": "skip"},
    {"name": "tcc_screen_recording", "status": "skip"},
]


class Desktop:
    """The user's one cua-driver daemon, as `status`, `call health_report`, `stop`, and a start see it."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, state: Path) -> None:
        self.pid: int | None = None
        self.version = "0.36.0"
        self.checks = HEALTHY
        self.starts = 0
        self.stops = 0
        self.kills: list[int] = []
        self.starts_at_all = True
        self.stops_at_all = True
        self._next_pid = 100
        monkeypatch.setattr(daemon, "STATE_DIRECTORY", state)
        monkeypatch.setattr(daemon, "POLL_SECONDS", 0.01)
        monkeypatch.setattr(daemon, "START_TIMEOUT_SECONDS", 0.1)
        monkeypatch.setattr(daemon, "STOP_TIMEOUT_SECONDS", 0.1)
        monkeypatch.setattr(daemon, "run_driver", self._run)
        monkeypatch.setattr(daemon, "_start_on_windows", self._start)
        monkeypatch.setattr(daemon, "_kill", self._kill)

    def users_daemon(self, version: str = "0.36.0") -> None:
        self.pid = 7
        self.version = version

    def _run(self, target: Target, executable: Path, arguments: list[str], timeout: float) -> Any:
        match arguments:
            case ["status"]:
                if self.pid is None:
                    return subprocess.CompletedProcess(arguments, 1, "", "Cua Driver daemon is not running\n")
                return subprocess.CompletedProcess(
                    arguments, 0, f"Cua Driver daemon is running\n  pid: {self.pid}\n", ""
                )
            case ["call", "health_report"]:
                assert self.pid is not None
                report = {"driver_version": self.version, "checks": self.checks}
                return subprocess.CompletedProcess(arguments, 0, json.dumps(report), "")
            case ["stop"]:
                self.stops += 1
                if self.stops_at_all:
                    self.pid = None
                return subprocess.CompletedProcess(arguments, 0, "", "")
        raise AssertionError(arguments)

    def _start(self, target: Target, executable: Path) -> None:
        self.starts += 1
        if self.starts_at_all:
            self._next_pid += 1
            self.pid = self._next_pid

    def _kill(self, target: Target, pid: int) -> None:
        self.kills.append(pid)
        self.pid = None


@pytest.fixture
def desktop(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Desktop:
    return Desktop(monkeypatch, tmp_path / "state")


def dead_pid() -> int:
    process = subprocess.Popen([sys.executable, "-c", "pass"])
    process.wait()
    return process.pid


def test_a_check_starts_the_daemon_and_stops_it_when_it_ends(desktop: Desktop) -> None:
    health = daemon.acquire("a", WSL, EXECUTABLE)
    running = desktop.pid

    daemon.release("a", WSL)

    assert isinstance(health, dict)
    assert health["driver_version"] == "0.36.0"
    assert (desktop.starts, desktop.stops, running, desktop.pid) == (1, 1, 101, None)
    assert not (daemon.STATE_DIRECTORY / "daemon.json").exists()
    assert list((daemon.STATE_DIRECTORY / "leases").iterdir()) == []


def test_the_users_own_daemon_is_used_and_never_stopped(desktop: Desktop) -> None:
    desktop.users_daemon()

    daemon.acquire("a", WSL, EXECUTABLE)
    daemon.release("a", WSL)

    assert (desktop.starts, desktop.stops, desktop.pid) == (0, 0, 7)


def test_a_running_daemon_of_another_version_is_refused_with_how_to_stop_it(desktop: Desktop) -> None:
    desktop.users_daemon("0.35.0")

    outcome = daemon.acquire("a", WSL, EXECUTABLE)

    assert isinstance(outcome, Unavailable)
    assert "0.35.0" in outcome.reason
    assert outcome.remedy == f"Stop it with `{EXECUTABLE} stop`, then run the check again."
    assert desktop.stops == 0
    assert not list((daemon.STATE_DIRECTORY / "leases").glob("*.json"))


def test_overlapping_checks_keep_the_daemon_until_the_last_one_ends(desktop: Desktop) -> None:
    daemon.acquire("a", WSL, EXECUTABLE)
    daemon.acquire("b", WSL, EXECUTABLE)

    daemon.release("a", WSL)
    after_first = desktop.pid
    daemon.release("b", WSL)

    assert desktop.starts == 1
    assert after_first == 101
    assert desktop.pid is None


def test_a_lease_whose_process_is_gone_does_not_keep_the_daemon(desktop: Desktop) -> None:
    daemon.acquire("a", WSL, EXECUTABLE)
    daemon.acquire("b", WSL, EXECUTABLE)
    lease = daemon.STATE_DIRECTORY / "leases" / "b.json"
    lease.write_text(json.dumps({"pid": dead_pid(), "started": None}), encoding="utf-8")

    daemon.release("a", WSL)

    assert desktop.pid is None
    assert not lease.exists()


def test_a_daemon_left_by_a_crashed_check_is_stopped_before_the_next_check(desktop: Desktop) -> None:
    daemon.acquire("crashed", WSL, EXECUTABLE)
    lease = daemon.STATE_DIRECTORY / "leases" / "crashed.json"
    lease.write_text(json.dumps({"pid": dead_pid(), "started": None}), encoding="utf-8")

    daemon.acquire("next", WSL, EXECUTABLE)

    assert (desktop.starts, desktop.stops, desktop.pid) == (2, 1, 102)


def test_a_daemon_that_does_not_stop_is_killed(desktop: Desktop) -> None:
    daemon.acquire("a", WSL, EXECUTABLE)
    desktop.stops_at_all = False

    daemon.release("a", WSL)

    assert desktop.kills == [101]
    assert desktop.pid is None


def test_a_recorded_daemon_replaced_by_the_users_own_is_left_alone(desktop: Desktop) -> None:
    daemon.acquire("a", WSL, EXECUTABLE)
    desktop.users_daemon()

    daemon.release("a", WSL)

    assert (desktop.stops, desktop.kills, desktop.pid) == (0, [], 7)
    assert not (daemon.STATE_DIRECTORY / "daemon.json").exists()


def test_a_daemon_that_does_not_start_is_unavailable_with_how_to_see_why(desktop: Desktop) -> None:
    desktop.starts_at_all = False

    outcome = daemon.acquire("a", WSL, EXECUTABLE)

    assert isinstance(outcome, Unavailable)
    assert "did not start" in outcome.reason
    assert f"`{EXECUTABLE} doctor`" in (outcome.remedy or "")


@pytest.fixture
def located(monkeypatch: pytest.MonkeyPatch, desktop: Desktop) -> Desktop:
    monkeypatch.setattr(prepare, "resolve_target", lambda: WSL)
    monkeypatch.setattr(prepare, "locate", lambda target: EXECUTABLE)
    return desktop


def test_prepare_leases_the_daemon_and_writes_the_shim(located: Desktop, tmp_path: Path) -> None:
    ready = prepare_computer_use("a", tmp_path / "cache")

    assert isinstance(ready, ComputerUse)
    assert ready.accessibility
    assert ready.command.parent.parent == tmp_path / "cache"
    assert str(EXECUTABLE) in ready.command.read_text(encoding="utf-8")
    ready.release()
    assert located.pid is None


def test_prepare_without_an_install_gives_the_shim_for_where_the_install_will_put_it(
    monkeypatch: pytest.MonkeyPatch, located: Desktop, tmp_path: Path
) -> None:
    monkeypatch.setattr(prepare, "locate", lambda target: None)
    monkeypatch.setattr(prepare, "own_executable", lambda target: EXECUTABLE)

    outcome = prepare_computer_use("a", tmp_path)

    assert isinstance(outcome, NotInstalled)
    assert outcome.executable == EXECUTABLE
    assert str(EXECUTABLE) in outcome.command.read_text(encoding="utf-8")
    assert located.starts == 0


def test_prepare_where_computer_use_cannot_run_passes_on_why(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    headless = Unavailable("There is no desktop.", "Run in one.")
    monkeypatch.setattr(prepare, "resolve_target", lambda: headless)

    assert prepare_computer_use("a", tmp_path) == headless


def test_prepare_turns_any_failure_into_unavailable_and_lets_go_of_the_daemon(
    monkeypatch: pytest.MonkeyPatch, located: Desktop, tmp_path: Path
) -> None:
    def broken(target: Target, executable: Path, cache_directory: Path) -> Path:
        raise OSError("disk full")

    monkeypatch.setattr(prepare, "write_shim", broken)

    outcome = prepare_computer_use("a", tmp_path)

    assert isinstance(outcome, Unavailable)
    assert "disk full" in outcome.reason
    assert outcome.remedy is not None
    assert located.pid is None


def test_prepare_on_a_desktop_without_an_accessibility_tree_still_enables_screenshots(
    located: Desktop, tmp_path: Path
) -> None:
    located.checks = [{"name": "ax_capability", "status": "fail"}]

    ready = prepare_computer_use("a", tmp_path)

    assert isinstance(ready, ComputerUse)
    assert not ready.accessibility


def test_prepare_on_macos_without_the_grants_names_the_grant_command(
    monkeypatch: pytest.MonkeyPatch, located: Desktop, tmp_path: Path
) -> None:
    monkeypatch.setattr(prepare, "resolve_target", lambda: MACOS)
    located.users_daemon()
    located.checks = [
        {"name": "tcc_accessibility", "status": "pass"},
        {"name": "tcc_screen_recording", "status": "fail"},
    ]

    outcome = prepare_computer_use("a", tmp_path)

    assert isinstance(outcome, Unavailable)
    assert outcome.remedy == f"Run `{EXECUTABLE} permissions grant` and allow both."
    assert not list((daemon.STATE_DIRECTORY / "leases").glob("*.json"))


@pytest.mark.skipif(sys.platform == "win32", reason="runs the POSIX shim")
@pytest.mark.parametrize("chosen", [LINUX, WSL])
def test_the_shim_runs_the_driver_with_telemetry_off(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, chosen: Target
) -> None:
    driver = tmp_path / "bin dir" / "cua-driver"
    driver.parent.mkdir()
    driver.write_text('#!/bin/sh\nenv\necho "args: $*"\n', encoding="utf-8")
    driver.chmod(0o755)
    monkeypatch.setenv("WSLENV", "USERPROFILE/p")

    shim = write_shim(chosen, driver, tmp_path / "cache")
    output = subprocess.run([str(shim), "call", "a b"], capture_output=True, text=True, check=True).stdout

    assert "DO_NOT_TRACK=1" in output
    assert "CUA_DRIVER_RS_TELEMETRY_ENABLED=0" in output
    assert "CUA_DRIVER_RS_UPDATE_CHECK=0" in output
    assert "args: call a b" in output
    expected = "USERPROFILE/p:DO_NOT_TRACK:CUA_DRIVER_RS_TELEMETRY_ENABLED:CUA_DRIVER_RS_UPDATE_CHECK"
    assert (f"WSLENV={expected}" in output) == (chosen.kind == "wsl")
    assert write_shim(chosen, driver, tmp_path / "cache") == shim


def test_the_windows_shim_is_a_batch_file_setting_telemetry_off(tmp_path: Path) -> None:
    executable = Path("C:/Users/Ada Lovelace/AppData/Local/reality-check/cua-driver/0.36.0/cua-driver.exe")

    shim = write_shim(WINDOWS, executable, tmp_path)

    assert shim.name == "cua-driver.cmd"
    assert shim.read_bytes().decode("utf-8").split("\r\n") == [
        "@echo off",
        "set DO_NOT_TRACK=1",
        "set CUA_DRIVER_RS_TELEMETRY_ENABLED=0",
        "set CUA_DRIVER_RS_UPDATE_CHECK=0",
        f'"{executable}" %*',
        "exit /b %errorlevel%",
        "",
    ]


class Readied:
    """Computer use as a check sees it, recording when the check lets go of it."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, outcome: str, accessibility: bool = True) -> None:
        self.prepared: list[str] = []
        self.released: list[str] = []
        self.command = Path("/cache/abc/cua-driver")
        self.installed = Path(tempfile.mkdtemp()) / "cua-driver"
        self._outcome = outcome
        self._accessibility = accessibility
        monkeypatch.setattr(check, "prepare_computer_use", self._prepare)
        monkeypatch.setattr(daemon, "release", lambda check_id, target: self.released.append(check_id))

    def _prepare(self, check_id: str, cache_directory: Path) -> ComputerUse | NotInstalled | Unavailable:
        self.prepared.append(check_id)
        if self._outcome == "not-installed":
            if self.installed.is_file():
                return ComputerUse(check_id, WSL, self.installed, self.command, True)
            return NotInstalled(WSL, self.installed, self.command)
        if self._outcome == "off":
            return Unavailable("cua-driver 0.36.0 is not installed.", "Run `reality-check install-computer-use`.")
        if self._outcome == "unsupported":
            return Unavailable("cua-driver has no build for the riscv64 architecture.", None)
        return ComputerUse(check_id, WSL, EXECUTABLE, self.command, self._accessibility)


@pytest.mark.parametrize("ask_first", ["when-off", "always", "never"])
async def test_the_prompt_says_computer_use_is_enabled_and_the_check_lets_go_of_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, ask_first: AskFirst
) -> None:
    readied = Readied(monkeypatch, "on")
    fake = FakeIntelligence(finishes())

    run = await lib.check_software(
        "Check Calculator", checks_directory=tmp_path, ask_first=ask_first, intelligence=fake
    )
    await run.result()

    prompt = fake.runs[0].request.initial_message
    enabled = "Computer use is enabled through the CLI `/cache/abc/cua-driver`; see the using-computer-use skill."
    assert f"{enabled}\n{check.ASK_FIRST[ask_first]}" in prompt
    assert "using-computer-use" in prompt
    assert readied.prepared == readied.released == [run.check_id]


async def test_the_prompt_says_to_work_from_screenshots_without_an_accessibility_tree(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    Readied(monkeypatch, "on", accessibility=False)
    fake = FakeIntelligence(finishes())

    await (await lib.check_software("Check the game", checks_directory=tmp_path, intelligence=fake)).result()

    assert (
        "no accessibility tree, so work from screenshots; `/cache/abc/cua-driver doctor`"
        in fake.runs[0].request.initial_message
    )


@pytest.mark.parametrize("ask_first", ["when-off", "always", "never"])
async def test_the_prompt_says_why_computer_use_is_off_and_how_to_enable_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, ask_first: AskFirst
) -> None:
    Readied(monkeypatch, "off")
    fake = FakeIntelligence(finishes())

    run = await lib.check_software(
        "Check Calculator", checks_directory=tmp_path, ask_first=ask_first, intelligence=fake
    )
    await run.result()

    off = (
        "Computer use is not enabled: cua-driver 0.36.0 is not installed. To enable it: Run `reality-check "
        "install-computer-use`. This matters only for software that needs its desktop UI driven."
    )
    assert f"{off}\n{check.ASK_FIRST[ask_first]}" in fake.runs[0].request.initial_message


async def test_the_prompt_says_when_computer_use_cannot_be_enabled_here(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    Readied(monkeypatch, "unsupported")
    fake = FakeIntelligence(finishes())

    await (await lib.check_software("Check Calculator", checks_directory=tmp_path, intelligence=fake)).result()

    assert "riscv64 architecture. It cannot be enabled on this machine." in fake.runs[0].request.initial_message


async def test_a_resumed_check_decides_computer_use_again(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    Readied(monkeypatch, "off")
    first = await lib.check_software(
        "Check Calculator", checks_directory=tmp_path, intelligence=FakeIntelligence(finishes())
    )
    await first.result()
    readied = Readied(monkeypatch, "on")
    fake = FakeIntelligence(finishes())

    second = await lib.check_software("Go on.", resume=first.check_id, checks_directory=tmp_path, intelligence=fake)
    await second.result()

    enabled = "Computer use is enabled through the CLI `/cache/abc/cua-driver`; see the using-computer-use skill."
    assert f"{enabled}\n{check.ASK_FIRST['when-off']}" in fake.runs[0].request.initial_message
    assert readied.released == [second.check_id]


async def test_a_check_lets_go_of_computer_use_however_it_ends(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    readied = Readied(monkeypatch, "on")

    cancelled = await lib.check_software("a", checks_directory=tmp_path, intelligence=FakeIntelligence(works_forever))
    await cancelled.cancel()
    timed_out = await lib.check_software(
        "b", checks_directory=tmp_path, timeout_seconds=1, intelligence=FakeIntelligence(works_forever)
    )
    failed = await lib.check_software("c", checks_directory=tmp_path, intelligence=FakeIntelligence(fails))
    unstarted = await lib.check_software("d", checks_directory=tmp_path, intelligence=UnstartableAgent(finishes()))
    for run in (timed_out, failed, unstarted):
        with pytest.raises(RealityCheckError):
            await run.result()

    assert sorted(readied.released) == sorted(run.check_id for run in (cancelled, timed_out, failed, unstarted))


async def test_a_daemon_that_fails_to_stop_does_not_fail_the_check(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    Readied(monkeypatch, "on")

    def broken(check_id: str, target: Target) -> None:
        raise OSError("pipe closed")

    monkeypatch.setattr(daemon, "release", broken)

    run = await lib.check_software("a", checks_directory=tmp_path, intelligence=FakeIntelligence(finishes()))

    assert (await run.result()).status == "done"


@pytest.mark.skipif(sys.platform == "win32", reason="runs a POSIX script")
def test_the_driver_is_run_with_telemetry_off(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    driver = tmp_path / "cua-driver"
    driver.write_text("#!/bin/sh\nenv\n", encoding="utf-8")
    driver.chmod(0o755)
    monkeypatch.delenv("DO_NOT_TRACK", raising=False)

    output = run_driver(LINUX, driver, [], 10).stdout

    assert "DO_NOT_TRACK=1" in output
    assert "CUA_DRIVER_RS_UPDATE_CHECK=0" in output


async def test_without_an_install_the_agent_is_told_to_install_and_the_check_enables_it_once_there(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    readied = Readied(monkeypatch, "not-installed")
    monkeypatch.setattr(check, "POLL_SECONDS", 0.01)
    fake = FakeIntelligence(waits_for_steering)

    run = await lib.check_software("Check Calculator", checks_directory=tmp_path, intelligence=fake)
    await asyncio.sleep(0.1)
    readied.installed.write_text("driver", encoding="utf-8")
    await asyncio.sleep(0.1)
    await run.steer("done")
    await run.result()

    prompt = fake.runs[0].request.initial_message
    assert "Computer use is not installed yet." in prompt
    assert f"install it with `{check._install_command()}`" in prompt
    assert "enabled through the CLI `/cache/abc/cua-driver`" in prompt
    assert check._install_command().endswith("install-computer-use")
    assert len(readied.prepared) == 2
    assert readied.released == [run.check_id]


async def test_without_an_install_nothing_is_made_ready_or_released(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    readied = Readied(monkeypatch, "not-installed")

    await (
        await lib.check_software(
            "Check Calculator", checks_directory=tmp_path, intelligence=FakeIntelligence(finishes())
        )
    ).result()

    assert len(readied.prepared) == 1
    assert readied.released == []
