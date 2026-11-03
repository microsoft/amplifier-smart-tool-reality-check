"""Give one check's agent the headless browser, or say why it cannot have one; never fails the check over it."""

import contextlib
import json
from pathlib import Path
import subprocess
from typing import NamedTuple

from reality_check.capabilities.browser.install import INSTALL_COMMAND, own_executable, run_agent_browser
from reality_check.capabilities.browser.shim import write_shim
from reality_check.capabilities.browser.target import Unavailable, resolve_target

SESSION_PREFIX = "rc-"
LIST_TIMEOUT_SECONDS = 15
CLOSE_TIMEOUT_SECONDS = 15


class Browser(NamedTuple):
    """agent-browser, installed, for one check."""

    executable: Path
    # The shim the agent runs, which hands agent-browser its skills and this machine's certificates.
    command: Path
    # The session the agent passes on every command; others it opens start with it and a dash.
    session: str

    def release(self) -> None:
        """Close the check's browser sessions."""
        close_sessions(self.executable, self.session)


class NotInstalled(NamedTuple):
    """No agent-browser yet; the shim runs it from where `install` will put it."""

    executable: Path
    command: Path
    session: str

    def release(self) -> None:
        """Close the check's browser sessions, when the agent installed agent-browser during the check."""
        close_sessions(self.executable, self.session)


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


def close_sessions(executable: Path, session: str) -> None:
    """Close `session` and every `<session>-<role>` agent-browser runs; best effort, and nothing when not installed."""
    if not executable.is_file():
        return
    try:
        listed = run_agent_browser(executable, ["session", "list", "--json"], LIST_TIMEOUT_SECONDS)
        sessions = json.loads(listed.stdout)["data"]["sessions"]
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
        return
    for name in sessions:
        if isinstance(name, str) and (name == session or name.startswith(f"{session}-")):
            with contextlib.suppress(OSError, subprocess.SubprocessError):
                run_agent_browser(executable, ["--session", name, "close"], CLOSE_TIMEOUT_SECONDS)
