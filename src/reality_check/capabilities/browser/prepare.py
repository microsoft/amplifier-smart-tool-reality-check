"""Give one check's agent the headless browser, or say why it cannot have one; never fails the check over it."""

import json
from pathlib import Path
import subprocess
from typing import NamedTuple

import psutil
from pydantic import BaseModel, Field

from reality_check.capabilities.browser.install import INSTALL_COMMAND, own_executable, run_agent_browser
from reality_check.capabilities.browser.shim import write_shim
from reality_check.capabilities.browser.target import Unavailable, resolve_target
from reality_check.processes import CHECK_ID_VARIABLE, Found, describe, environment, found_process, own_processes, stop
from reality_check.schemas import RealityCheckError

SESSION_PREFIX = "rc-"
LIST_TIMEOUT_SECONDS = 15
CLOSE_TIMEOUT_SECONDS = 15


class BrowserSession(BaseModel):
    """A browser session of the check's that was open when it ended, and what the check did about it."""

    name: str
    outcome: str = Field(description="closed, how its daemon ended when it did not close, or why it was not closed")


class Closed(NamedTuple):
    """What closing a check's browser sessions did, and what could not be done, and why."""

    sessions: list[BrowserSession]
    problems: list[str]


class Browser(NamedTuple):
    """agent-browser, installed, for one check."""

    executable: Path
    # The shim the agent runs, which hands agent-browser its skills and this machine's certificates.
    command: Path
    # The session the agent passes on every command; others it opens start with it and a dash.
    session: str

    def release(self) -> Closed:
        """Close the check's browser sessions."""
        return close_sessions(executable=self.executable, check_id=self.session.removeprefix(SESSION_PREFIX))


class NotInstalled(NamedTuple):
    """No agent-browser yet; the shim runs it from where `install` will put it."""

    executable: Path
    command: Path
    session: str

    def release(self) -> Closed:
        """Close the check's browser sessions, when the agent installed agent-browser during the check."""
        return close_sessions(executable=self.executable, check_id=self.session.removeprefix(SESSION_PREFIX))


def prepare_browser(check_id: str, cache_directory: Path) -> Browser | NotInstalled | Unavailable:
    """Write the shim for the pinned agent-browser for a check; never downloads, never runs it, and never raises."""
    try:
        target = resolve_target()
        if isinstance(target, Unavailable):
            return target
        executable = own_executable(target)
        command = write_shim(target, executable, cache_directory)
        session = f"{SESSION_PREFIX}{check_id}"
        if executable.is_file():
            return Browser(executable, command, session)
        return NotInstalled(executable, command, session)
    except Exception as error:  # whatever went wrong, the check goes on without the browser
        return Unavailable(
            f"agent-browser could not be made ready: {type(error).__name__}: {error}",
            f"Run `{INSTALL_COMMAND}` to see why.",
        )


def close_sessions(executable: Path, check_id: str) -> Closed:
    """Close the check's sessions, and stop the daemon of any that does not close.

    The check's sessions are `rc-<check_id>`, every `rc-<check_id>-<role>`, and any whose daemon the check's agent
    started. Only listed sessions are closed, since closing another starts a daemon for it.
    """
    session = f"{SESSION_PREFIX}{check_id}"
    problems: list[str] = []
    daemons = _daemons(check_id=check_id, problems=problems)
    sessions: list[BrowserSession] = []
    names: list[str] = []
    if executable.is_file():
        try:
            listed = run_agent_browser(
                executable=executable, arguments=["session", "list", "--json"], timeout=LIST_TIMEOUT_SECONDS
            )
            names = [
                name
                for name in json.loads(listed.stdout)["data"]["sessions"]
                if isinstance(name, str) and (name == session or name.startswith(f"{session}-") or name in daemons)
            ]
        except (OSError, subprocess.SubprocessError, RealityCheckError, ValueError, KeyError, TypeError) as error:
            problems.append(f"Listing agent-browser sessions failed: {describe(error)}")
    for name in names:
        try:
            run_agent_browser(
                executable=executable, arguments=["--session", name, "close"], timeout=CLOSE_TIMEOUT_SECONDS
            )
            daemons.pop(name, None)
            sessions.append(BrowserSession(name=name, outcome="closed"))
        except (OSError, subprocess.SubprocessError, RealityCheckError) as error:
            problems.append(f"Closing agent-browser session {name} failed: {describe(error)}")
            if name not in daemons:
                sessions.append(BrowserSession(name=name, outcome=f"not closed: {describe(error)}"))
    # Stopped without starting a process, which may be what the machine has run out of.
    outcomes = stop(found=list(daemons.values()))
    for name, found in daemons.items():
        pid = found.process.pid
        sessions.append(BrowserSession(name=name, outcome=outcomes[pid]))
        problems.append(f"agent-browser session {name} was not closed; its daemon, process {pid}: {outcomes[pid]}.")
    return Closed(sessions=sessions, problems=problems)


def _daemons(check_id: str, problems: list[str]) -> dict[str, Found]:
    """The agent-browser daemons the check's agent started, by session; those that cannot be read go in `problems`."""
    daemons: dict[str, Found] = {}
    for process in own_processes():
        variables = environment(process)
        if variables.get("AGENT_BROWSER_DAEMON") == "1" and variables.get(CHECK_ID_VARIABLE) == check_id:
            session = variables.get("AGENT_BROWSER_SESSION", "default")
            try:
                daemons[session] = found_process(process)
            except psutil.NoSuchProcess:
                pass
            except psutil.Error as error:
                problems.append(
                    f"The daemon of agent-browser session {session}, process {process.pid}, could not be read: "
                    f"{describe(error)}"
                )
    return daemons
