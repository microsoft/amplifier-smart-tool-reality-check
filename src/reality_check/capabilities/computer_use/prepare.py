"""Make computer use ready for one check, or say why it is not; never fails the check over it."""

import contextlib
from pathlib import Path
from typing import Any, NamedTuple

from reality_check.capabilities.computer_use import daemon
from reality_check.capabilities.computer_use.install import locate, own_executable
from reality_check.capabilities.computer_use.shim import write_shim
from reality_check.capabilities.computer_use.target import Target, Unavailable, resolve_target


class ComputerUse(NamedTuple):
    """Computer use, ready for one check until `release`."""

    check_id: str
    target: Target
    executable: Path
    # The shim the agent runs, which keeps telemetry off.
    command: Path
    # False when the desktop gives no accessibility tree, so the agent works from screenshots alone.
    accessibility: bool

    def release(self) -> None:
        """Let go of the daemon, stopping it when this check started it and no other check uses it."""
        daemon.release(self.check_id, self.target)


class NotInstalled(NamedTuple):
    """No cua-driver yet; the shim runs it from where `install-computer-use` will put it."""

    target: Target
    executable: Path
    command: Path


def prepare_computer_use(check_id: str, cache_directory: Path) -> ComputerUse | NotInstalled | Unavailable:
    """Find the pinned cua-driver and lease its daemon for a check; never downloads and never raises."""
    target: Target | Unavailable | None = None
    try:
        target = resolve_target()
        if isinstance(target, Unavailable):
            return target
        executable = locate(target)
        if executable is None:
            expected = own_executable(target)
            return NotInstalled(target, expected, write_shim(target, expected, cache_directory))
        health = daemon.acquire(check_id, target, executable)
        if isinstance(health, Unavailable):
            daemon.release(check_id, target)
            return health
        if target.kind == "macos" and not (
            _passes(health, "tcc_accessibility") and _passes(health, "tcc_screen_recording")
        ):
            daemon.release(check_id, target)
            return Unavailable(
                "CuaDriver does not have the Accessibility and Screen Recording permissions.",
                f"Run `{executable} permissions grant` and allow both.",
            )
        command = write_shim(target, executable, cache_directory)
        return ComputerUse(check_id, target, executable, command, not _fails(health, "ax_capability"))
    except Exception as error:  # whatever went wrong, the check goes on without computer use
        if isinstance(target, Target):
            with contextlib.suppress(Exception):
                daemon.release(check_id, target)
        return Unavailable(
            f"cua-driver could not be made ready: {type(error).__name__}: {error}",
            "Run `cua-driver doctor` to see why.",
        )


def _passes(health: dict[str, Any], name: str) -> bool:
    return any(check.get("name") == name and check.get("status") == "pass" for check in health.get("checks", []))


def _fails(health: dict[str, Any], name: str) -> bool:
    return any(
        check.get("name") == name and check.get("status") not in ("pass", "skip") for check in health.get("checks", [])
    )
