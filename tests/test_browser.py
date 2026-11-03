"""Gives each check's agent agent-browser by name, says in the prompt how to use it, and closes its sessions."""

import json
from pathlib import Path
import subprocess
import sys
from typing import Any

from fakes import FakeIntelligence, FakeRun, fails, finishes, works_forever
from fakes import Unavailable as UnstartableAgent
import pytest

from reality_check import lib
from reality_check.capabilities.browser import install, prepare, shim
from reality_check.capabilities.browser.prepare import Browser, NotInstalled, prepare_browser
from reality_check.capabilities.browser.shim import write_shim
from reality_check.capabilities.browser.target import Target, Unavailable
from reality_check.capabilities.check_software import check
from reality_check.intelligence.schemas import AgentResult
from reality_check.schemas import RealityCheckError

LINUX = Target("linux-x64")
COMMAND = Path("/cache/def/agent-browser")


@pytest.fixture
def never_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("agent-browser was run")

    monkeypatch.setattr(install.subprocess, "run", refuse)


@pytest.fixture
def placed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, never_runs: None) -> Path:
    executable = tmp_path / "data" / "bin" / "agent-browser"
    monkeypatch.setattr(prepare, "resolve_target", lambda: LINUX)
    monkeypatch.setattr(prepare, "own_executable", lambda target: executable)
    return executable


def test_prepare_with_an_install_gives_the_shim_and_the_check_s_session(placed: Path, tmp_path: Path) -> None:
    placed.parent.mkdir(parents=True)
    placed.write_text("binary", encoding="utf-8")

    ready = prepare_browser("20261103-120000-abc123", tmp_path / "cache")

    assert isinstance(ready, Browser)
    assert (ready.executable, ready.session) == (placed, "rc-20261103-120000-abc123")
    assert ready.command.name == "agent-browser"
    assert ready.command.parents[1] == tmp_path / "cache"
    assert str(placed) in ready.command.read_text(encoding="utf-8")


def test_prepare_without_an_install_gives_the_shim_for_where_the_install_will_put_it(
    placed: Path, tmp_path: Path
) -> None:
    outcome = prepare_browser("a", tmp_path / "cache")

    assert isinstance(outcome, NotInstalled)
    assert outcome.session == "rc-a"
    placed.parent.mkdir(parents=True)
    placed.write_text("binary", encoding="utf-8")
    ready = prepare_browser("a", tmp_path / "cache")
    assert isinstance(ready, Browser)
    assert ready.command == outcome.command


def test_prepare_turns_any_failure_into_unavailable_with_what_shows_why(
    monkeypatch: pytest.MonkeyPatch, placed: Path, tmp_path: Path
) -> None:
    def broken(target: Target, executable: Path, cache_directory: Path) -> Path:
        raise OSError("disk full")

    monkeypatch.setattr(prepare, "write_shim", broken)

    outcome = prepare_browser("a", tmp_path)

    assert isinstance(outcome, Unavailable)
    assert "disk full" in outcome.reason
    assert outcome.remedy == f"Run `{install.INSTALL_COMMAND}` to see why."


@pytest.fixture
def bundles(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[Path]:
    paths = [tmp_path / "missing.crt", tmp_path / "ca-bundle.crt", tmp_path / "other.crt"]
    for path in paths[1:]:
        path.write_text("PEM", encoding="utf-8")
    monkeypatch.setattr(shim, "CA_BUNDLES", tuple(str(path) for path in paths))
    return paths


def run_shim(tmp_path: Path, certutil: bool, ssl_cert_file: Path | None = None) -> str:
    """Run a fresh shim for a fake agent-browser that prints its environment, with certutil on PATH or not."""
    binary = tmp_path / "bin dir" / "agent-browser"
    binary.parent.mkdir(exist_ok=True)
    binary.write_text('#!/bin/sh\nenv\necho "args: $*"\n', encoding="utf-8")
    binary.chmod(0o755)
    tools = tmp_path / "tools"
    tools.mkdir(exist_ok=True)
    if certutil:
        (tools / "certutil").write_text("#!/bin/sh\n", encoding="utf-8")
        (tools / "certutil").chmod(0o755)
    environment = {"PATH": f"{tools}:/usr/bin:/bin"}
    if ssl_cert_file is not None:
        environment["SSL_CERT_FILE"] = str(ssl_cert_file)
    command = write_shim(LINUX, binary, tmp_path / "cache")
    return subprocess.run(
        [str(command), "open", "a b"], capture_output=True, text=True, env=environment, check=True
    ).stdout


@pytest.mark.skipif(sys.platform == "win32", reason="runs the POSIX shim")
def test_the_shim_runs_agent_browser_with_its_skills_and_no_update_check(tmp_path: Path, bundles: list[Path]) -> None:
    output = run_shim(tmp_path, certutil=False)

    assert f"AGENT_BROWSER_SKILLS_DIR={install.skills_directory()}" in output
    assert "AGENT_BROWSER_NO_VERSION_CHECK=1" in output
    assert "AGENT_BROWSER_SESSION" not in output
    assert "args: open a b" in output


@pytest.mark.skipif(sys.platform == "win32", reason="runs the POSIX shim")
def test_the_shim_hands_certificates_only_once_certutil_is_there(tmp_path: Path, bundles: list[Path]) -> None:
    assert "AGENT_BROWSER_CA_CERT" not in run_shim(tmp_path, certutil=False)
    assert f"AGENT_BROWSER_CA_CERT={bundles[1]}" in run_shim(tmp_path, certutil=True)
    assert f"AGENT_BROWSER_CA_CERT={bundles[2]}" in run_shim(tmp_path, certutil=True, ssl_cert_file=bundles[2])


class Browsing:
    """agent-browser as a check sees it, recording what the check runs it with when it ends."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, directory: Path, outcome: str) -> None:
        self.executable = directory / "agent-browser"
        self.check_ids: list[str] = []
        self.calls: list[list[str]] = []
        self.failing: set[str] = set()
        self._outcome = outcome
        if outcome == "installed":
            self.executable.write_text("binary", encoding="utf-8")
        monkeypatch.setattr(check, "prepare_browser", self._prepare)
        monkeypatch.setattr(prepare, "run_agent_browser", self._run)

    @property
    def closed(self) -> list[str]:
        return [arguments[1] for arguments in self.calls if arguments[0] == "--session"]

    def _prepare(self, check_id: str, cache_directory: Path) -> Browser | NotInstalled | Unavailable:
        self.check_ids.append(check_id)
        if self._outcome == "unsupported":
            return Unavailable("agent-browser has no build for the riscv64 architecture.", None)
        if self._outcome == "off":
            return Unavailable("agent-browser could not be made ready: OSError: disk full", "Free some space.")
        if self.executable.is_file():
            return Browser(self.executable, COMMAND, f"rc-{check_id}")
        return NotInstalled(self.executable, COMMAND, f"rc-{check_id}")

    def _run(self, executable: Path, arguments: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
        assert executable == self.executable
        self.calls.append(arguments)
        if arguments == ["session", "list", "--json"]:
            if "list" in self.failing:
                raise OSError("daemon gone")
            sessions = ["rc-20200101-000000-aaaaaa", "default"]
            for check_id in self.check_ids:
                sessions += [f"rc-{check_id}-admin", f"rc-{check_id}", f"rc-{check_id}0"]
            return subprocess.CompletedProcess(
                arguments, 0, json.dumps({"success": True, "data": {"sessions": sessions}})
            )
        if "close" in self.failing:
            raise subprocess.TimeoutExpired(arguments, timeout)
        return subprocess.CompletedProcess(arguments, 0, "")


async def test_the_prompt_gives_the_session_and_the_check_closes_only_its_own_sessions(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    browsing = Browsing(monkeypatch, tmp_path, "installed")
    fake = FakeIntelligence(finishes())

    run = await lib.check_software("Check the shop", checks_directory=tmp_path, intelligence=fake)
    await run.result()

    enabled = (
        f"A headless browser is enabled through the CLI `agent-browser`; pass `--session rc-{run.check_id}` on every "
        "command, and see the using-browser skill."
    )
    assert f"{enabled}\n{check.ASK_FIRST['when-off']}" in fake.runs[0].request.initial_message
    assert COMMAND.parent in fake.runs[0].request.path_directories
    assert browsing.closed == [f"rc-{run.check_id}-admin", f"rc-{run.check_id}"]
    assert all(arguments[2:] == ["close"] for arguments in browsing.calls[1:])


async def test_without_an_install_the_prompt_says_how_to_install_and_which_session_to_pass(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    browsing = Browsing(monkeypatch, tmp_path, "not-installed")
    fake = FakeIntelligence(finishes())

    run = await lib.check_software("Check the shop", checks_directory=tmp_path, intelligence=fake)
    await run.result()

    prompt = fake.runs[0].request.initial_message
    assert "A headless browser is not installed yet." in prompt
    assert f"install it with `{check._install_command('browser')}`" in prompt
    assert f"pass `--session rc-{run.check_id}` on every command, and see the using-browser skill." in prompt
    assert check._install_command("browser").endswith("install --component browser")
    assert COMMAND.parent in fake.runs[0].request.path_directories
    assert browsing.calls == []


async def test_a_browser_installed_during_the_check_has_its_sessions_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    browsing = Browsing(monkeypatch, tmp_path, "not-installed")

    async def installs(run: FakeRun) -> AgentResult:
        browsing.executable.write_text("binary", encoding="utf-8")
        return await finishes()(run)

    fake = FakeIntelligence(installs)

    run = await lib.check_software("Check the shop", checks_directory=tmp_path, intelligence=fake)
    await run.result()

    assert browsing.closed == [f"rc-{run.check_id}-admin", f"rc-{run.check_id}"]


async def test_a_check_closes_its_sessions_however_it_ends(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    browsing = Browsing(monkeypatch, tmp_path, "installed")

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

    runs = (cancelled, timed_out, failed, unstarted)
    expected = [name for run in runs for name in (f"rc-{run.check_id}-admin", f"rc-{run.check_id}")]
    assert sorted(browsing.closed) == sorted(expected)


@pytest.mark.parametrize("failing", ["list", "close"])
async def test_sessions_that_fail_to_close_do_not_fail_the_check(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, failing: str
) -> None:
    browsing = Browsing(monkeypatch, tmp_path, "installed")
    browsing.failing.add(failing)

    run = await lib.check_software("a", checks_directory=tmp_path, intelligence=FakeIntelligence(finishes()))

    assert (await run.result()).status == "done"
    assert len(browsing.closed) == (2 if failing == "close" else 0)
