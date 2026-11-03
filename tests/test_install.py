"""Installs every component this machine supports, or the ones named, and says when that is not everything."""

from collections.abc import Callable
import json
from pathlib import Path
import subprocess
from typing import Any

import pytest
from typer.testing import CliRunner

from reality_check import lib
from reality_check.capabilities.browser import install as browser_install
from reality_check.capabilities.browser import target as browser_target
from reality_check.capabilities.computer_use import install as computer_use_install
from reality_check.capabilities.computer_use import target as computer_use_target
from reality_check.capabilities.install import download, install
from reality_check.cli import app
from reality_check.core.skill import CAPABILITIES
from reality_check.schemas import (
    COMPONENTS,
    BrowserInstall,
    Component,
    ComponentInstall,
    ComputerUseInstall,
    Install,
    RealityCheckError,
)

INSTALLED: dict[Component, ComponentInstall] = {
    "computer-use": ComputerUseInstall(
        target="wsl",
        version="0.36.0",
        executable=Path("/mnt/c/cua-driver.exe"),
        already_installed=True,
        remaining_step=None,
    ),
    "browser": BrowserInstall(
        version="0.41.1",
        executable=Path("/home/ada/.local/share/reality-check/agent-browser/0.41.1/bin/agent-browser"),
        skills_directory=Path("/home/ada/.local/share/reality-check/agent-browser/0.41.1/skill-data"),
        already_installed=False,
        remaining_step=None,
    ),
}

runner = CliRunner()


def installer(monkeypatch: pytest.MonkeyPatch, fails_with: str | None = None) -> list[str]:
    """Replace every installer with one that succeeds; computer use's fails with the given code. Returns the calls."""
    calls: list[str] = []

    def replacement(component: Component) -> Callable[[], ComponentInstall]:
        def install_component() -> ComponentInstall:
            calls.append(component)
            if component == "computer-use" and fails_with is not None:
                raise RealityCheckError(code=fails_with, message="It did not install.", remedy="Fix it.")
            return INSTALLED[component]

        return install_component

    for component, original in install.INSTALLERS.items():
        monkeypatch.setitem(install.INSTALLERS, component, original._replace(install=replacement(component)))
    return calls


def test_every_component_has_an_installer() -> None:
    assert set(install.INSTALLERS) == set(COMPONENTS)


def test_install_with_nothing_named_installs_every_component(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = installer(monkeypatch)

    result = lib.install()

    assert calls == ["computer-use", "browser"]
    assert result.installed == [INSTALLED["computer-use"], INSTALLED["browser"]]
    assert result.not_installed == []
    assert result.complete


def test_install_installs_only_the_named_components_once_each(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = installer(monkeypatch)

    result = lib.install(components=["browser", "computer-use", "browser"])

    assert calls == ["computer-use", "browser"]
    assert result.installed == [INSTALLED["computer-use"], INSTALLED["browser"]]
    assert result.complete


@pytest.mark.parametrize(
    ("named", "code", "complete"),
    [
        (False, "computer-use-unsupported", True),
        (True, "computer-use-unsupported", False),
        (False, "computer-use-download-failed", False),
        (True, "computer-use-download-failed", False),
    ],
)
def test_a_component_not_installed_is_reported_and_completes_only_when_unsupported_and_not_named(
    monkeypatch: pytest.MonkeyPatch, named: bool, code: str, complete: bool
) -> None:
    installer(monkeypatch, fails_with=code)

    result = lib.install(components=["computer-use"] if named else None)

    assert result.installed == ([] if named else [INSTALLED["browser"]])
    missing = result.not_installed[0]
    assert (missing.component, missing.code, missing.message, missing.remedy) == (
        "computer-use",
        code,
        "It did not install.",
        "Fix it.",
    )
    assert missing.unsupported == (code == "computer-use-unsupported")
    assert result.complete == complete


@pytest.mark.parametrize(
    ("arguments", "fails_with", "exit_code"),
    [
        (["install"], None, 0),
        (["install"], "computer-use-unsupported", 0),
        (["install", "--component", "computer-use"], "computer-use-unsupported", 1),
        (["install"], "computer-use-download-failed", 1),
    ],
)
def test_the_cli_exits_1_when_the_install_is_not_complete(
    monkeypatch: pytest.MonkeyPatch, arguments: list[str], fails_with: str | None, exit_code: int
) -> None:
    installer(monkeypatch, fails_with=fails_with)

    result = runner.invoke(app, arguments)

    assert result.exit_code == exit_code
    assert json.loads(result.stdout)["complete"] == (exit_code == 0)


def test_the_cli_rejects_a_component_it_does_not_know(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = installer(monkeypatch)

    result = runner.invoke(app, ["install", "--component", "printer"])

    assert result.exit_code == 2
    assert calls == []


def test_the_cli_help_is_the_install_skill() -> None:
    result = runner.invoke(app, ["install", "--help"])

    assert result.exit_code == 0
    assert "reality-check install" in result.stdout
    assert "--component" in result.stdout


def test_the_install_round_trips_through_json_with_each_component_told_apart(monkeypatch: pytest.MonkeyPatch) -> None:
    installer(monkeypatch)

    result = runner.invoke(app, ["install"])

    parsed = Install.model_validate_json(result.stdout)
    assert parsed == lib.install()
    assert [type(each) for each in parsed.installed] == [ComputerUseInstall, BrowserInstall]
    assert json.loads(result.stdout)["installed"][1]["skills_directory"].endswith("skill-data")


@pytest.mark.parametrize(
    ("variables", "store"),
    [({}, "certifi"), ({"SSL_CERT_FILE": "/etc/dtu/ca.crt"}, "system"), ({"SSL_CERT_DIR": "/etc/ssl/certs"}, "system")],
)
def test_downloads_trust_a_store_the_environment_names(
    monkeypatch: pytest.MonkeyPatch, variables: dict[str, str], store: str
) -> None:
    monkeypatch.setattr(download.sys, "platform", "linux")
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.delenv("SSL_CERT_DIR", raising=False)
    for name, value in variables.items():
        monkeypatch.setenv(name, value)
    loaded: list[str | None] = []
    monkeypatch.setattr(download.ssl, "create_default_context", lambda cafile=None: loaded.append(cafile))

    download.tls_context()

    assert loaded == [download.certifi.where() if store == "certifi" else None]


class Machine:
    """A machine for help to describe; anything that would download or run a binary other than sudo fails the test."""

    def __init__(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        system: str,
        machine: str,
        wsl: bool = False,
        sudo: bool = False,
        on_path: tuple[str, ...] = (),
    ) -> None:
        self.runs: list[list[str]] = []
        self.sudo = sudo
        binfmt = tmp_path / "binfmt_misc"
        binfmt.mkdir()
        if wsl:
            (binfmt / "WSLInterop").touch()
        self.data = tmp_path / "data"
        monkeypatch.setattr(computer_use_target.sys, "platform", system)
        monkeypatch.setattr(computer_use_target.platform, "machine", lambda: machine)
        monkeypatch.setattr(
            computer_use_target.platform, "release", lambda: "6.6.0-microsoft-standard-WSL2" if wsl else "6.8.0"
        )
        monkeypatch.setattr(browser_target.platform, "libc_ver", lambda: ("glibc", "2.39"))
        monkeypatch.setattr(computer_use_target, "BINFMT", binfmt)
        monkeypatch.setenv("DISPLAY", ":0")
        monkeypatch.setattr(browser_install.os, "getuid", lambda: 1000, raising=False)
        monkeypatch.setattr(browser_install.shutil, "which", lambda name: f"/usr/bin/{name}" if name in on_path else None)
        monkeypatch.setattr(browser_install.platformdirs, "user_data_path", lambda *args, **kwargs: self.data)
        monkeypatch.setattr(computer_use_install, "MACOS_APP", tmp_path / "Applications" / "CuaDriver.app")
        monkeypatch.setattr(subprocess, "run", self._run)
        monkeypatch.setattr(download, "urlopen", self._urlopen)

    def _run(self, arguments: list[str], **options: Any) -> subprocess.CompletedProcess[bytes]:
        self.runs.append(arguments)
        assert arguments == ["sudo", "-n", "true"], f"help ran {arguments}"
        assert options["stdin"] == subprocess.DEVNULL
        return subprocess.CompletedProcess(arguments, 0 if self.sudo else 1, b"", b"")

    def _urlopen(self, *args: Any, **kwargs: Any) -> None:
        raise AssertionError("help used the network")


def test_on_this_machine_under_wsl_with_passwordless_sudo(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    machine = Machine(monkeypatch, tmp_path, "linux", "x86_64", wsl=True, sudo=True, on_path=("sudo", "certutil"))

    section = install.on_this_machine()

    assert section.startswith("## On this machine\n\nThis is Linux x86_64 under WSL.")
    assert "the Windows build (`cua-driver-rs-0.36.0-windows-x86_64-binary.zip`)" in section
    assert "Windows user's LocalAppData; checks drive the Windows desktop." in section
    assert "`agent-browser-linux-x64` release asset" in section
    assert "installs Chromium's system libraries" in section
    assert "`certutil` is there" in section
    assert machine.runs == [["sudo", "-n", "true"]]


def test_on_this_machine_on_linux_arm64_needs_the_distributions_chromium(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    machine = Machine(monkeypatch, tmp_path, "linux", "aarch64", on_path=("sudo",))
    executable = machine.data / "agent-browser" / browser_install.VERSION / "bin" / "agent-browser"
    executable.parent.mkdir(parents=True)
    executable.touch()

    section = install.on_this_machine()

    assert "This is Linux arm64." in section
    assert "`cua-driver-rs-0.36.0-linux-arm64-binary.tar.gz` build" in section
    assert "checks drive this Linux desktop" in section
    assert f"agent-browser 0.41.1 is already at `{executable}`" in section
    assert "Chrome for Testing has no `linux-arm64` build" in section
    assert "`certutil` is missing" in section
    assert machine.runs == []


def test_on_this_machine_on_macos_names_the_permissions_and_no_linux_steps(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    machine = Machine(monkeypatch, tmp_path, "darwin", "arm64")

    section = install.on_this_machine()

    assert "This is macOS arm64." in section
    assert "`CuaDriver.app`" in section
    assert "permissions grant` and allow Accessibility and Screen Recording" in section
    assert "`agent-browser-darwin-arm64` release asset" in section
    assert "certutil" not in section
    assert "sudo" not in section
    assert machine.runs == []


def test_on_this_machine_says_why_each_component_is_skipped_where_none_runs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    machine = Machine(monkeypatch, tmp_path, "linux", "riscv64")

    section = install.on_this_machine()

    assert "This is Linux riscv64." in section
    assert "- `computer-use`: Not supported here, so it is skipped. cua-driver has no build for the riscv64" in section
    assert "- `browser`: Not supported here, so it is skipped. agent-browser has no build for the riscv64" in section
    assert machine.runs == []


def test_only_the_install_skill_says_what_it_does_on_this_machine(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    Machine(monkeypatch, tmp_path, "linux", "x86_64", wsl=True)

    assert lib.skill("install").endswith(f"{install.on_this_machine()}\n</skill_content>")
    assert "## On this machine" in runner.invoke(app, ["install", "--help"]).stdout
    for capability in CAPABILITIES:
        if capability.name != "install":
            assert "## On this machine" not in lib.skill(capability.name)
    assert "## On this machine" not in lib.skill()
