"""The cua-driver daemon, kept running only while checks use it.

There is one daemon per user. Each check that uses it holds a lease; the daemon a check started is recorded, and
the last check to let go of it stops it. A daemon reality-check did not start is the user's and is never stopped.
"""

from collections.abc import Callable
import contextlib
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import time
from typing import Any, NamedTuple

from filelock import FileLock
import platformdirs

from reality_check.capabilities.check_software.record import alive, process_started
from reality_check.capabilities.computer_use.install import MACOS_APP, VERSION
from reality_check.capabilities.computer_use.target import (
    TELEMETRY_OFF,
    Target,
    Unavailable,
    environment,
    run_driver,
    windows_path,
)
from reality_check.core.skill import DISTRIBUTION

STATE_DIRECTORY = platformdirs.user_data_path(DISTRIBUTION, appauthor=False, roaming=False) / "cua-driver"
CALL_TIMEOUT_SECONDS = 30
START_TIMEOUT_SECONDS = 10
STOP_TIMEOUT_SECONDS = 5
POLL_SECONDS = 0.25
LOCK_TIMEOUT_SECONDS = 60
LOG_LINES = 5
PID_PATTERN = re.compile(r"^\s*pid:\s*(\d+)\s*$", re.MULTILINE)


class Started(NamedTuple):
    """The daemon a check started, kept in `daemon.json` so the last check using it stops it."""

    pid: int | None
    executable: str


def acquire(check_id: str, target: Target, executable: Path) -> dict[str, Any] | Unavailable:
    """Lease the daemon for a check, starting it when none runs; its health report, or why it cannot be used."""
    STATE_DIRECTORY.mkdir(parents=True, exist_ok=True)
    with FileLock(STATE_DIRECTORY / "lock", timeout=LOCK_TIMEOUT_SECONDS):
        started = _started()
        if started is not None and not _live_leases():
            # Left by a check that ended without letting go of it, such as one whose process was killed.
            _stop(target, started)
        if _status(target, executable) is None:
            outcome = _start(target, executable)
            if isinstance(outcome, Unavailable):
                return outcome
            _record_started(outcome)
        health = json.loads(_call(target, executable, "health_report"))
        version = health.get("driver_version")
        if version != VERSION:
            return Unavailable(
                f"A cua-driver daemon of version {version} is running, and checks use {VERSION}.",
                f"Stop it with `{executable} stop`, then run the check again.",
            )
        _lease(check_id)
        return health


def release(check_id: str, target: Target) -> None:
    """Let go of a check's lease, and stop the daemon when a check started it and no check uses it anymore."""
    STATE_DIRECTORY.mkdir(parents=True, exist_ok=True)
    with FileLock(STATE_DIRECTORY / "lock", timeout=LOCK_TIMEOUT_SECONDS):
        (STATE_DIRECTORY / "leases" / f"{check_id}.json").unlink(missing_ok=True)
        started = _started()
        if started is not None and not _live_leases():
            _stop(target, started)


def _status(target: Target, executable: Path) -> int | None:
    """The running daemon's pid, 0 when it runs and gives none, or None when none runs."""
    completed = run_driver(target, executable, ["status"], CALL_TIMEOUT_SECONDS)
    if completed.returncode != 0:
        return None
    match = PID_PATTERN.search(completed.stdout)
    return int(match.group(1)) if match else 0


def _call(target: Target, executable: Path, tool: str) -> str:
    completed = run_driver(target, executable, ["call", tool], CALL_TIMEOUT_SECONDS)
    if completed.returncode != 0:
        raise OSError(f"`cua-driver call {tool}` exited {completed.returncode}: {completed.stderr.strip()}")
    return completed.stdout


def _start(target: Target, executable: Path) -> Started | Unavailable:
    log = STATE_DIRECTORY / "daemon.log"
    match target.kind:
        case "windows" | "wsl":
            _start_on_windows(target, executable)
        case "macos":
            # Started through LaunchServices, so macOS attributes its grants to CuaDriver.app and not to this process.
            options = [part for name, value in TELEMETRY_OFF.items() for part in ("--env", f"{name}={value}")]
            command = ["open", "-n", "-g", *options, "-a", str(MACOS_APP), "--args", "serve"]
            subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, timeout=CALL_TIMEOUT_SECONDS)
        case "linux":
            with log.open("wb") as output:
                process = subprocess.Popen(
                    [str(executable), "serve"],
                    stdin=subprocess.DEVNULL,
                    stdout=output,
                    stderr=output,
                    env=environment(target),
                    start_new_session=True,
                )
            # Waited on, so it leaves no zombie once stopped.
            threading.Thread(target=process.wait, daemon=True).start()
    deadline = time.monotonic() + START_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        pid = _status(target, executable)
        if pid is not None:
            return Started(pid or None, str(executable))
        time.sleep(POLL_SECONDS)
    said = _tail(log) if target.kind == "linux" else ""
    return Unavailable(
        f"The cua-driver daemon did not start within {START_TIMEOUT_SECONDS} seconds.{said}",
        f"Run `{executable} doctor` to see why, or `{executable} serve` in a terminal for its errors.",
    )


def _start_on_windows(target: Target, executable: Path) -> None:
    """Start the daemon hidden and apart from this process, in the user's desktop session."""
    path = windows_path(executable) if target.kind == "wsl" else str(executable)
    folder = path.rsplit("\\", 1)[0]
    quoted, quoted_folder = (text.replace("'", "''") for text in (path, folder))
    # Start-Process lets the daemon go on alone; redirecting its output would tie it to this process's pipes.
    script = f"Start-Process -FilePath '{quoted}' -ArgumentList serve -WindowStyle Hidden -WorkingDirectory '{quoted_folder}'"
    subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        env=environment(target),
        timeout=CALL_TIMEOUT_SECONDS,
        check=True,
    )


def _stop(target: Target, started: Started) -> None:
    """Stop the daemon a check started, when it is still that one, and forget it."""
    executable = Path(started.executable)
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        running = _status(target, executable)
        if running is not None and started.pid in (None, running):
            run_driver(target, executable, ["stop"], CALL_TIMEOUT_SECONDS)
            if not _until(lambda: _status(target, executable) is None) and running:
                _kill(target, running)
    (STATE_DIRECTORY / "daemon.json").unlink(missing_ok=True)


def _kill(target: Target, pid: int) -> None:
    if target.kind in ("windows", "wsl"):
        command = ["taskkill.exe", "/PID", str(pid), "/F"]
        subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, timeout=CALL_TIMEOUT_SECONDS)
        return
    with contextlib.suppress(ProcessLookupError):
        os.kill(pid, 9)


def _until(condition: Callable[[], bool]) -> bool:
    deadline = time.monotonic() + STOP_TIMEOUT_SECONDS
    while not condition():
        if time.monotonic() >= deadline:
            return False
        time.sleep(POLL_SECONDS)
    return True


def _started() -> Started | None:
    with contextlib.suppress(OSError, ValueError, TypeError):
        data = json.loads((STATE_DIRECTORY / "daemon.json").read_text(encoding="utf-8"))
        return Started(data["pid"], data["executable"])
    return None


def _record_started(started: Started) -> None:
    _write(STATE_DIRECTORY / "daemon.json", {**started._asdict(), "version": VERSION})


def _lease(check_id: str) -> None:
    pid = os.getpid()
    _write(STATE_DIRECTORY / "leases" / f"{check_id}.json", {"pid": pid, "started": process_started(pid)})


def _live_leases() -> list[str]:
    """The checks whose process still holds a lease; the leases of ended processes are removed."""
    live: list[str] = []
    for path in sorted((STATE_DIRECTORY / "leases").glob("*.json")):
        try:
            owner = json.loads(path.read_text(encoding="utf-8"))
            holding = alive(owner["pid"], owner["started"])
        except (OSError, ValueError, KeyError, TypeError):
            holding = False
        if holding:
            live.append(path.stem)
        else:
            path.unlink(missing_ok=True)
    return live


def _write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(f"{path.name}.tmp")
    partial.write_text(json.dumps(data), encoding="utf-8")
    partial.replace(path)


def _tail(log: Path) -> str:
    with contextlib.suppress(OSError):
        lines = log.read_text(encoding="utf-8", errors="replace").strip().splitlines()[-LOG_LINES:]
        if lines:
            return " It printed: " + " | ".join(lines)
    return ""
