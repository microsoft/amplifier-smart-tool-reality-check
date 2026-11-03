"""Install, once, each component checks use beyond the agent, through that component's own installer."""

from collections.abc import Callable
import platform
import sys
from typing import NamedTuple

from reality_check.capabilities.browser import install as browser
from reality_check.capabilities.computer_use import install as computer_use
from reality_check.capabilities.computer_use.target import ARCHITECTURES, is_wsl
from reality_check.schemas import (
    COMPONENTS,
    Component,
    ComponentInstall,
    ComponentNotInstalled,
    Install,
    RealityCheckError,
)


class Installer(NamedTuple):
    install: Callable[[], ComponentInstall]
    # The failure that means this machine cannot run the component as it is, rather than an install that went wrong.
    unsupported_code: str
    # What installing it does here, from cheap local checks only: no network, and none of its binaries run.
    on_this_machine: Callable[[], str]


INSTALLERS: dict[Component, Installer] = {
    "computer-use": Installer(
        computer_use.install_computer_use, "computer-use-unsupported", computer_use.on_this_machine
    ),
    "browser": Installer(browser.install_browser, "browser-unsupported", browser.on_this_machine),
}
SYSTEMS = {"linux": "Linux", "darwin": "macOS", "win32": "Windows"}


def install(components: list[Component] | None = None) -> Install:
    """Install every component this machine supports, or the ones named, and report each; never raises for one."""
    wanted = [component for component in COMPONENTS if component in components] if components else list(COMPONENTS)
    installed: list[ComponentInstall] = []
    not_installed: list[ComponentNotInstalled] = []
    for component in wanted:
        installer = INSTALLERS[component]
        try:
            installed.append(installer.install())
        except RealityCheckError as error:
            not_installed.append(
                ComponentNotInstalled(
                    component=component,
                    code=error.code,
                    message=error.message,
                    remedy=error.remedy,
                    unsupported=error.code == installer.unsupported_code,
                )
            )
    # Named components are wanted here; otherwise one this machine cannot run is simply not part of everything.
    complete = all(not components and missing.unsupported for missing in not_installed)
    return Install(installed=installed, not_installed=not_installed, complete=complete)


def on_this_machine() -> str:
    """A Markdown section on what `install` does on this machine for each component, worked out now."""
    lines = ["## On this machine", "", f"This is {_platform()}. Here `reality-check install` does this:", ""]
    lines += [f"- `{component}`: {INSTALLERS[component].on_this_machine()}" for component in COMPONENTS]
    return "\n".join(lines)


def _platform() -> str:
    """The OS and architecture as a person names them, such as `Linux x86_64 under WSL`."""
    system = SYSTEMS.get(sys.platform, sys.platform)
    machine = ARCHITECTURES.get(platform.machine().lower(), platform.machine())
    return f"{system} {machine} under WSL" if is_wsl() else f"{system} {machine}"
