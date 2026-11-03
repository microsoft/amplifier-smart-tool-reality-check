"""Picks the desktop computer use drives and installs the pinned cua-driver for it, offline."""

import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile
from typing import Any
import zipfile

import pytest
from typer.testing import CliRunner

from reality_check import lib
from reality_check.capabilities.computer_use import install, target
from reality_check.capabilities.computer_use.target import Target, Unavailable
from reality_check.capabilities.install import download
from reality_check.capabilities.install import install as install_all
from reality_check.cli import app

WINDOWS = Target("windows", "windows-x86_64-binary", "zip")
WSL = Target("wsl", "windows-x86_64-binary", "zip")
LINUX = Target("linux", "linux-x86_64-binary", "tar.gz")
MACOS = Target("macos", "darwin-universal", "tar.gz")

runner = CliRunner()


def platform_is(
    monkeypatch: pytest.MonkeyPatch,
    system: str,
    machine: str = "x86_64",
    release: str = "6.8.0-generic",
    interop: bool = False,
    tmp_path: Path | None = None,
) -> None:
    monkeypatch.setattr(target.sys, "platform", system)
    monkeypatch.setattr(target.platform, "machine", lambda: machine)
    monkeypatch.setattr(target.platform, "release", lambda: release)
    binfmt = (tmp_path or Path("/nonexistent")) / "binfmt_misc"
    if tmp_path is not None:
        binfmt.mkdir(exist_ok=True)
        if interop:
            (binfmt / "WSLInterop").touch()
    monkeypatch.setattr(target, "BINFMT", binfmt)


@pytest.mark.parametrize(
    ("system", "machine", "expected"),
    [
        ("win32", "AMD64", WINDOWS),
        ("win32", "ARM64", Target("windows", "windows-arm64-binary", "zip")),
        ("linux", "aarch64", Target("linux", "linux-arm64-binary", "tar.gz")),
        ("darwin", "arm64", MACOS),
        ("darwin", "x86_64", MACOS),
    ],
)
def test_each_platform_gets_the_build_for_its_desktop(
    monkeypatch: pytest.MonkeyPatch, system: str, machine: str, expected: Target
) -> None:
    platform_is(monkeypatch, system, machine)
    monkeypatch.setenv("DISPLAY", ":0")

    assert target.resolve_target() == expected


def test_wsl_with_interop_always_drives_the_windows_desktop(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    platform_is(monkeypatch, "linux", release="6.6.87.2-microsoft-standard-WSL2", interop=True, tmp_path=tmp_path)
    monkeypatch.setenv("DISPLAY", ":0")

    assert target.resolve_target() == WSL


def test_a_container_on_a_wsl_host_is_linux(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    platform_is(monkeypatch, "linux", release="6.6.87.2-microsoft-standard-WSL2", interop=False, tmp_path=tmp_path)
    monkeypatch.setenv("DISPLAY", ":99")

    assert target.resolve_target() == LINUX


def test_headless_linux_is_unavailable_with_how_to_get_a_desktop(monkeypatch: pytest.MonkeyPatch) -> None:
    platform_is(monkeypatch, "linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)

    resolved = target.resolve_target()

    assert isinstance(resolved, Unavailable)
    assert "DISPLAY" in resolved.reason
    assert resolved.remedy is not None


def test_an_unknown_architecture_is_unavailable_without_a_remedy(monkeypatch: pytest.MonkeyPatch) -> None:
    platform_is(monkeypatch, "linux", machine="riscv64")
    monkeypatch.setenv("DISPLAY", ":0")

    resolved = target.resolve_target()

    assert isinstance(resolved, Unavailable)
    assert "riscv64" in resolved.reason
    assert resolved.remedy is None


def test_every_target_has_a_pinned_hash_for_its_asset() -> None:
    for each in (WINDOWS, Target("windows", "windows-arm64-binary", "zip"), LINUX, MACOS):
        assert each.asset(install.VERSION) in install.SHA256


def test_the_driver_runs_with_telemetry_off_and_wsl_passes_it_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WSLENV", "USERPROFILE/p:DO_NOT_TRACK")

    linux = target.environment(LINUX)
    wsl = target.environment(WSL)

    for variables in (linux, wsl):
        assert variables["DO_NOT_TRACK"] == "1"
        assert variables["CUA_DRIVER_RS_TELEMETRY_ENABLED"] == "0"
        assert variables["CUA_DRIVER_RS_UPDATE_CHECK"] == "0"
    assert wsl["WSLENV"] == "USERPROFILE/p:DO_NOT_TRACK:CUA_DRIVER_RS_TELEMETRY_ENABLED:CUA_DRIVER_RS_UPDATE_CHECK"
    assert linux["WSLENV"] == "USERPROFILE/p:DO_NOT_TRACK"


class Release:
    """A fake GitHub release: one archive per asset, served by a fake `urlopen`, with what each run reports."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, chosen: Target, home: Path) -> None:
        self.target = chosen
        self.downloads: list[str] = []
        self.versions: dict[Path, str] = {}
        self.archive = self._archive(chosen)
        self.hash = hashlib.sha256(self.archive).hexdigest()
        monkeypatch.setattr(install, "resolve_target", lambda: chosen)
        monkeypatch.setattr(install, "SHA256", {chosen.asset(install.VERSION): self.hash})
        monkeypatch.setattr(download, "urlopen", self._urlopen)
        monkeypatch.setattr(install, "run_driver", self._run)
        monkeypatch.setattr(install.shutil, "which", lambda name: None)
        monkeypatch.setattr(install.platformdirs, "user_data_path", lambda *args, **kwargs: home / "data")
        monkeypatch.setattr(install, "windows_folders", lambda: (home / "c" / "Local", home / "c" / "profile"))
        monkeypatch.setattr(install, "MACOS_APP", home / "Applications" / "CuaDriver.app")
        monkeypatch.setattr(target.Path, "home", lambda: home / "linux")
        monkeypatch.setenv("LOCALAPPDATA", str(home / "Local"))

    def _archive(self, chosen: Target) -> bytes:
        buffer = io.BytesIO()
        if chosen.archive == "zip":
            with zipfile.ZipFile(buffer, "w") as archive:
                archive.writestr(chosen.executable_name, "driver")
                archive.writestr("cua-driver-uia.exe", "helper")
            return buffer.getvalue()
        files = (
            {"cua-driver-rs-0.36.0-darwin-universal/CuaDriver.app/Contents/MacOS/cua-driver": b"driver"}
            if chosen.kind == "macos"
            else {"cua-driver": b"driver", "libcua_driver_sdk.so": b"sdk"}
        )
        with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
            for name, data in files.items():
                info = tarfile.TarInfo(name)
                info.size = len(data)
                info.mode = 0o755
                archive.addfile(info, io.BytesIO(data))
        return buffer.getvalue()

    def _urlopen(self, url: str, timeout: float, context: Any) -> io.BytesIO:
        self.downloads.append(url)
        return io.BytesIO(self.archive)

    def _run(self, chosen: Target, executable: Path, arguments: list[str], timeout: float) -> Any:
        assert arguments == ["--version"]
        version = self.versions.get(executable, install.VERSION if executable.read_text() == "driver" else "")
        return subprocess.CompletedProcess(arguments, 0, f"cua-driver {version}\n", "")


def installed_computer_use() -> lib.ComputerUseInstall:
    installed = lib.install(components=["computer-use"]).installed[0]
    assert isinstance(installed, lib.ComputerUseInstall)
    return installed


@pytest.mark.parametrize("chosen", [WINDOWS, WSL, LINUX, MACOS])
def test_install_downloads_the_pinned_asset_and_reports_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, chosen: Target
) -> None:
    release = Release(monkeypatch, chosen, tmp_path)

    installed = installed_computer_use()

    expected = {
        "windows": tmp_path / "data" / "cua-driver" / "0.36.0",
        "wsl": tmp_path / "c" / "Local" / "reality-check" / "cua-driver" / "0.36.0",
        "linux": tmp_path / "data" / "cua-driver" / "0.36.0",
        "macos": tmp_path / "Applications" / "CuaDriver.app" / "Contents" / "MacOS",
    }[chosen.kind]
    assert release.downloads == [
        f"https://github.com/trycua/cua/releases/download/cua-driver-rs-v0.36.0/{chosen.asset('0.36.0')}"
    ]
    assert installed.target == chosen.kind
    assert installed.version == "0.36.0"
    assert installed.executable == expected / chosen.executable_name
    assert installed.executable.read_text() == "driver"
    assert not installed.already_installed
    assert (installed.remaining_step is not None) == (chosen.kind == "macos")
    assert list(tmp_path.rglob("*.tmp")) == []


def test_install_again_reports_the_existing_install_without_downloading(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    release = Release(monkeypatch, WSL, tmp_path)
    first = installed_computer_use()

    again = installed_computer_use()

    assert len(release.downloads) == 1
    assert again.already_installed
    assert again.executable == first.executable


def test_an_install_of_the_pinned_version_on_path_is_used(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    release = Release(monkeypatch, LINUX, tmp_path)
    existing = tmp_path / "bin" / "cua-driver"
    existing.parent.mkdir()
    existing.write_text("driver")
    monkeypatch.setattr(install.shutil, "which", lambda name: str(existing))

    installed = installed_computer_use()

    assert release.downloads == []
    assert installed.executable == existing
    assert installed.already_installed


def test_an_install_of_another_version_is_ignored(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    release = Release(monkeypatch, WINDOWS, tmp_path)
    vendor = tmp_path / "Local" / "Programs" / "Cua" / "cua-driver" / "bin" / "cua-driver.exe"
    vendor.parent.mkdir(parents=True)
    vendor.write_text("driver")
    release.versions[vendor] = "0.35.0"

    installed = installed_computer_use()

    assert len(release.downloads) == 1
    assert installed.executable != vendor


def test_a_download_that_does_not_match_its_hash_installs_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    Release(monkeypatch, LINUX, tmp_path)
    monkeypatch.setattr(install, "SHA256", {LINUX.asset(install.VERSION): "0" * 64})

    result = lib.install(components=["computer-use"])

    assert not result.complete
    assert result.not_installed[0].code == "computer-use-download-corrupt"
    assert not (tmp_path / "data").exists()


def test_a_failed_download_names_the_fix(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    Release(monkeypatch, LINUX, tmp_path)

    def offline(url: str, timeout: float, context: Any) -> io.BytesIO:
        raise download.URLError("no route to host")

    monkeypatch.setattr(download, "urlopen", offline)

    result = lib.install(components=["computer-use"])

    assert not result.complete
    missing = result.not_installed[0]
    assert missing.code == "computer-use-download-failed"
    assert not missing.unsupported
    assert "reality-check install --component computer-use" in missing.remedy
    assert not (tmp_path / "data").exists()


def test_install_where_computer_use_cannot_run_says_why(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(install, "resolve_target", lambda: Unavailable("There is no desktop.", "Run in one."))

    result = lib.install(components=["computer-use"])

    assert not result.complete
    missing = result.not_installed[0]
    assert missing.component == "computer-use"
    assert missing.code == "computer-use-unsupported"
    assert missing.unsupported
    assert "There is no desktop." in missing.message
    assert missing.remedy == "Run in one."


@pytest.mark.parametrize("arguments", [["install"], ["install", "--component", "computer-use"]])
def test_the_cli_prints_the_install_as_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, arguments: list[str]
) -> None:
    Release(monkeypatch, WSL, tmp_path)
    browser_already_here(monkeypatch)

    result = runner.invoke(app, arguments)

    assert result.exit_code == 0
    printed = json.loads(result.stdout)
    assert printed["complete"]
    assert printed["not_installed"] == []
    assert printed["installed"][0]["component"] == "computer-use"
    assert printed["installed"][0]["target"] == "wsl"
    assert not printed["installed"][0]["already_installed"]


def browser_already_here(monkeypatch: pytest.MonkeyPatch) -> None:
    """The browser component reports itself installed, so installing everything downloads only computer use."""
    installed = lib.BrowserInstall(
        version="0.41.1",
        executable=Path("/agent-browser"),
        skills_directory=Path("/skill-data"),
        already_installed=True,
        remaining_step=None,
    )
    browser = install_all.INSTALLERS["browser"]
    monkeypatch.setitem(install_all.INSTALLERS, "browser", browser._replace(install=lambda: installed))
