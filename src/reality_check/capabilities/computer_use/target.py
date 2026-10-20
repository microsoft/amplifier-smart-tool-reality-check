"""Which desktop computer use drives, and how to run cua-driver for it."""

import functools
import os
from pathlib import Path
import platform
import subprocess
import sys
from typing import NamedTuple

from reality_check.schemas import ComputerUseTarget

# Every cua-driver process gets these, so it never sends telemetry or looks for updates.
TELEMETRY_OFF = {"DO_NOT_TRACK": "1", "CUA_DRIVER_RS_TELEMETRY_ENABLED": "0", "CUA_DRIVER_RS_UPDATE_CHECK": "0"}
ARCHITECTURES = {"x86_64": "x86_64", "amd64": "x86_64", "aarch64": "arm64", "arm64": "arm64"}
# Holds a `WSLInterop` entry only where WSL can start Windows programs; newer WSL names it `WSLInterop-late`.
BINFMT = Path("/proc/sys/fs/binfmt_misc")
SUPPORTED = "Windows, WSL (which drives the Windows desktop), Linux with a desktop, and macOS, on x86_64 or arm64"
WINDOWS_TIMEOUT_SECONDS = 15


class Unavailable(NamedTuple):
    """Why computer use cannot run here, and what enables it, when anything does."""

    reason: str
    remedy: str | None


class Target(NamedTuple):
    """The desktop to drive and the cua-driver build that drives it."""

    kind: ComputerUseTarget
    # The release asset's platform part, such as `windows-x86_64-binary`.
    label: str
    archive: str

    def asset(self, version: str) -> str:
        return f"cua-driver-rs-{version}-{self.label}.{self.archive}"

    @property
    def executable_name(self) -> str:
        return "cua-driver.exe" if self.kind in ("windows", "wsl") else "cua-driver"


def resolve_target() -> Target | Unavailable:
    """The desktop to drive from here, picked by where the desktop is rather than by the Python running this."""
    if sys.platform == "darwin":
        return Target("macos", "darwin-universal", "tar.gz")
    machine = ARCHITECTURES.get(platform.machine().lower())
    if machine is None:
        return Unavailable(
            f"cua-driver has no build for the {platform.machine()} architecture; it runs on {SUPPORTED}.", None
        )
    if sys.platform == "win32":
        return Target("windows", f"windows-{machine}-binary", "zip")
    if not sys.platform.startswith("linux"):
        return Unavailable(f"Computer use runs on {SUPPORTED}, not on {sys.platform}.", None)
    if is_wsl():
        return Target("wsl", f"windows-{machine}-binary", "zip")
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return Unavailable(
            "There is no desktop: neither DISPLAY nor WAYLAND_DISPLAY is set.",
            "Run in a desktop session, with DISPLAY or WAYLAND_DISPLAY set.",
        )
    return Target("linux", f"linux-{machine}-binary", "tar.gz")


def is_wsl() -> bool:
    """WSL with Windows interop; a container on a WSL host has the same kernel but cannot start Windows programs."""
    if "microsoft" not in platform.release().lower():
        return False
    try:
        return any(entry.name.startswith("WSLInterop") for entry in BINFMT.iterdir())
    except OSError:
        return False


def environment(target: Target) -> dict[str, str]:
    """This process's environment with telemetry off, passed on to Windows programs under WSL as well."""
    variables = {**os.environ, **TELEMETRY_OFF}
    if target.kind == "wsl":
        variables["WSLENV"] = wslenv(os.environ.get("WSLENV", ""))
    return variables


def wslenv(current: str) -> str:
    """`WSLENV` with the telemetry variables added, so WSL passes them on to the Windows programs it starts."""
    shared = [name for name in current.split(":") if name]
    names = {name.split("/")[0] for name in shared}
    return ":".join([*shared, *(name for name in TELEMETRY_OFF if name not in names)])


def run_driver(
    target: Target, executable: Path, arguments: list[str], timeout: float, stdin: str | None = None
) -> subprocess.CompletedProcess[str]:
    """Run cua-driver once with telemetry off; raises OSError and subprocess.TimeoutExpired."""
    return subprocess.run(
        [str(executable), *arguments],
        input=stdin if stdin is not None else "",
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=environment(target),
        timeout=timeout,
        check=False,
    )


@functools.cache
def windows_folders() -> tuple[Path, Path]:
    """Under WSL, the Windows user's LocalAppData and profile folders, as WSL paths."""
    # `/u` makes cmd print UTF-16, so names outside the console's code page survive.
    output = subprocess.run(
        ["cmd.exe", "/d", "/u", "/c", "echo %LOCALAPPDATA%&echo %USERPROFILE%"],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=WINDOWS_TIMEOUT_SECONDS,
        check=True,
    ).stdout.decode("utf-16-le")
    local, profile = (wsl_path(line.strip()) for line in output.splitlines()[:2])
    return local, profile


def wsl_path(windows: str) -> Path:
    """A Windows path as WSL sees it."""
    return Path(_wslpath("-u", windows))


def windows_path(path: Path) -> str:
    """A WSL path as Windows programs see it."""
    return _wslpath("-w", str(path))


def _wslpath(flag: str, path: str) -> str:
    return subprocess.run(
        ["wslpath", flag, path], capture_output=True, text=True, timeout=WINDOWS_TIMEOUT_SECONDS, check=True
    ).stdout.strip()
