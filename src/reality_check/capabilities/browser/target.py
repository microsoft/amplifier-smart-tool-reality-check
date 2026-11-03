"""Which agent-browser build runs here, and whether Chrome for Testing has a build beside it."""

import platform
import sys
from typing import NamedTuple

ARCHITECTURES = {"x86_64": "x64", "amd64": "x64", "aarch64": "arm64", "arm64": "arm64"}
SUPPORTED = "Linux, macOS, and Windows, on x86_64 or arm64"


class Unavailable(NamedTuple):
    """Why agent-browser cannot run here, and what enables it, when anything does."""

    reason: str
    remedy: str | None


class Target(NamedTuple):
    """The agent-browser build for this machine."""

    # The release asset's platform part, such as `linux-musl-x64`.
    label: str

    @property
    def asset(self) -> str:
        return f"agent-browser-{self.label}.exe" if self.windows else f"agent-browser-{self.label}"

    @property
    def executable_name(self) -> str:
        return "agent-browser.exe" if self.windows else "agent-browser"

    @property
    def windows(self) -> bool:
        return self.label.startswith("win32")

    @property
    def linux(self) -> bool:
        return self.label.startswith("linux")

    @property
    def chrome_for_testing(self) -> bool:
        """Whether `agent-browser install` can download Chrome for Testing, which has no Linux arm64 or musl build."""
        return not self.linux or self.label == "linux-x64"


def resolve_target() -> Target | Unavailable:
    """The agent-browser build for this OS, architecture, and, on Linux, C library."""
    machine = ARCHITECTURES.get(platform.machine().lower())
    if machine is None:
        return Unavailable(
            f"agent-browser has no build for the {platform.machine()} architecture; it runs on {SUPPORTED}.", None
        )
    if sys.platform == "win32":
        # There is no Windows arm64 build; Windows runs the x64 one under emulation.
        return Target("win32-x64")
    if sys.platform == "darwin":
        return Target(f"darwin-{machine}")
    if sys.platform.startswith("linux"):
        return Target(f"linux-musl-{machine}" if is_musl() else f"linux-{machine}")
    return Unavailable(f"agent-browser runs on {SUPPORTED}, not on {sys.platform}.", None)


def is_musl() -> bool:
    """Linux without glibc, such as Alpine, where the glibc build does not start."""
    # Reads the C library this Python links; empty for musl and for a static Python, which glibc systems do not ship.
    return platform.libc_ver()[0] != "glibc"
