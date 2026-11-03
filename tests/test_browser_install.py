"""Picks the agent-browser build for this machine, installs it with its skills, and makes sure a browser launches."""

import base64
import hashlib
import io
import json
from pathlib import Path
import stat
import subprocess
import sys
import tarfile
from typing import Any

import pytest

from reality_check import lib
from reality_check.capabilities.browser import install, target
from reality_check.capabilities.browser.target import Target, Unavailable
from reality_check.capabilities.install import download

LINUX = Target("linux-x64")
LINUX_ARM = Target("linux-arm64")
BINARY = b"agent-browser binary"
PACKAGE = {
    "package/LICENSE": b"Apache License 2.0",
    "package/skill-data/core/SKILL.md": b"# agent-browser",
    "package/skill-data/core/templates/form.md": b"form",
    "package/README.md": b"readme",
    "package/bin/agent-browser.js": b"wrapper",
}


def platform_is(monkeypatch: pytest.MonkeyPatch, system: str, machine: str, libc: str = "glibc") -> None:
    monkeypatch.setattr(target.sys, "platform", system)
    monkeypatch.setattr(target.platform, "machine", lambda: machine)
    monkeypatch.setattr(target.platform, "libc_ver", lambda: (libc, "2.39" if libc else ""))


@pytest.mark.parametrize(
    ("system", "machine", "libc", "asset"),
    [
        ("linux", "x86_64", "glibc", "agent-browser-linux-x64"),
        ("linux", "aarch64", "glibc", "agent-browser-linux-arm64"),
        ("linux", "x86_64", "", "agent-browser-linux-musl-x64"),
        ("linux", "aarch64", "", "agent-browser-linux-musl-arm64"),
        ("darwin", "x86_64", "", "agent-browser-darwin-x64"),
        ("darwin", "arm64", "", "agent-browser-darwin-arm64"),
        ("win32", "AMD64", "", "agent-browser-win32-x64.exe"),
        ("win32", "ARM64", "", "agent-browser-win32-x64.exe"),
    ],
)
def test_each_platform_gets_its_build_and_every_build_has_a_pinned_hash(
    monkeypatch: pytest.MonkeyPatch, system: str, machine: str, libc: str, asset: str
) -> None:
    platform_is(monkeypatch, system, machine, libc)

    resolved = target.resolve_target()

    assert isinstance(resolved, Target)
    assert resolved.asset == asset
    assert asset in install.SHA256
    assert resolved.executable_name == ("agent-browser.exe" if system == "win32" else "agent-browser")


@pytest.mark.parametrize(("system", "machine"), [("freebsd14", "amd64"), ("linux", "i686"), ("win32", "x86")])
def test_an_os_or_architecture_without_a_build_is_unavailable(
    monkeypatch: pytest.MonkeyPatch, system: str, machine: str
) -> None:
    platform_is(monkeypatch, system, machine)

    resolved = target.resolve_target()

    assert isinstance(resolved, Unavailable)
    assert resolved.remedy is None


def doctor_report(launches: bool) -> str:
    """What `agent-browser doctor --offline --json` prints, with a failure unrelated to launching either way."""
    checks = [
        {"category": "Environment", "id": "env.version", "message": "CLI version 0.41.1", "status": "pass"},
        {"category": "Recording", "id": "recording.ffmpeg", "message": "ffmpeg not found", "status": "fail"},
        {"category": "Chrome", "id": "chrome.cache_dir", "message": "Cache dir", "status": "info"},
    ]
    if launches:
        checks += [
            {"category": "Chrome", "id": "chrome.installed", "message": "Chrome 147", "status": "pass"},
            {"category": "Launch test", "id": "launch.elapsed", "message": "Launched in 0.29s", "status": "pass"},
        ]
    else:
        checks += [
            {"category": "Chrome", "id": "chrome.installed", "message": "Chrome not found", "status": "fail"},
            {"category": "Launch test", "id": "launch.launch", "message": "No Chrome to launch", "status": "fail"},
        ]
    return json.dumps({"checks": checks, "fixed": [], "success": launches, "summary": {}})


class Release:
    """A fake release and npm registry served by a fake `urlopen`, and a fake agent-browser, sudo, and doctor."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, chosen: Target, home: Path) -> None:
        self.target = chosen
        self.home = home
        self.downloads: list[str] = []
        self.runs: list[list[str]] = []
        self.environments: list[dict[str, str]] = []
        self.stdins: list[Any] = []
        # Whether each doctor run finds a browser that launches, in order; the last one repeats.
        self.launches = [True]
        self.install_exit = 0
        self.sudo_exit = 1
        self.package = self._package()
        self.served = {
            install.RELEASE_URL.format(version=install.VERSION, asset=chosen.asset): BINARY,
            install.PACKAGE_URL.format(version=install.VERSION): self.package,
        }
        self.which = {"sudo": "/usr/bin/sudo", "certutil": "/usr/bin/certutil"}
        monkeypatch.setattr(install, "resolve_target", lambda: chosen)
        monkeypatch.setattr(install, "SHA256", {chosen.asset: hashlib.sha256(BINARY).hexdigest()})
        integrity = base64.b64encode(hashlib.sha512(self.package).digest()).decode()
        monkeypatch.setattr(install, "INTEGRITY", f"sha512-{integrity}")
        monkeypatch.setattr(download, "urlopen", self._urlopen)
        monkeypatch.setattr(install.subprocess, "run", self._run)
        monkeypatch.setattr(install.shutil, "which", self.which.get)
        monkeypatch.setattr(install.os, "getuid", lambda: 1000, raising=False)
        monkeypatch.setattr(install.platformdirs, "user_data_path", lambda *args, **kwargs: home / "data")

    @property
    def directory(self) -> Path:
        return self.home / "data" / "agent-browser" / install.VERSION

    def _package(self) -> bytes:
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
            for name, data in PACKAGE.items():
                info = tarfile.TarInfo(name)
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
        return buffer.getvalue()

    def _urlopen(self, url: str, timeout: float, context: Any) -> io.BytesIO:
        self.downloads.append(url)
        return io.BytesIO(self.served[url])

    def _run(self, arguments: list[str], **options: Any) -> subprocess.CompletedProcess[str]:
        self.runs.append(arguments)
        self.stdins.append(options.get("stdin"))
        if arguments[0] == "sudo":
            return subprocess.CompletedProcess(arguments, self.sudo_exit, "", "")
        self.environments.append(options["env"])
        match arguments[1:]:
            case ["--version"]:
                works = Path(arguments[0]).read_bytes() == BINARY
                return subprocess.CompletedProcess(arguments, 0, f"agent-browser {install.VERSION}\n" if works else "")
            case ["doctor", "--offline", "--json"]:
                launches = self.launches.pop(0) if len(self.launches) > 1 else self.launches[0]
                return subprocess.CompletedProcess(arguments, 0 if launches else 1, doctor_report(launches), "")
            case ["install", *_]:
                return subprocess.CompletedProcess(arguments, self.install_exit, "", "Failed to download Chrome")
        raise AssertionError(f"unexpected run: {arguments}")

    def browser_installs(self) -> list[list[str]]:
        return [run[1:] for run in self.runs if run[1:2] == ["install"]]


def test_install_downloads_the_binary_and_only_the_skills_and_license_from_the_package(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    release = Release(monkeypatch, LINUX, tmp_path)

    installed = install.install_browser()

    assert release.downloads == [
        "https://github.com/vercel-labs/agent-browser/releases/download/v0.41.1/agent-browser-linux-x64",
        "https://registry.npmjs.org/agent-browser/-/agent-browser-0.41.1.tgz",
    ]
    assert installed.version == "0.41.1"
    assert installed.executable == release.directory / "bin" / "agent-browser"
    assert installed.executable.read_bytes() == BINARY
    if sys.platform != "win32":
        assert installed.executable.stat().st_mode & stat.S_IXUSR
    assert installed.skills_directory == release.directory / "skill-data"
    assert sorted(
        str(path.relative_to(release.directory)) for path in release.directory.rglob("*") if path.is_file()
    ) == [
        "LICENSE",
        "bin/agent-browser",
        "skill-data/core/SKILL.md",
        "skill-data/core/templates/form.md",
    ]
    assert not installed.already_installed
    assert installed.remaining_step is None
    assert release.browser_installs() == []
    assert list(tmp_path.rglob("*.tmp")) == []


def test_install_again_with_a_browser_that_launches_downloads_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    release = Release(monkeypatch, LINUX, tmp_path)
    install.install_browser()

    again = install.install_browser()

    assert len(release.downloads) == 2
    assert again.already_installed


def test_every_agent_browser_run_finds_its_skills_has_no_update_check_and_nothing_to_read(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    release = Release(monkeypatch, LINUX, tmp_path)
    monkeypatch.setenv("KEPT", "1")
    release.launches = [False, True]

    install.install_browser()

    assert release.environments
    for variables in release.environments:
        assert variables["AGENT_BROWSER_SKILLS_DIR"] == str(release.directory / "skill-data")
        assert variables["AGENT_BROWSER_NO_VERSION_CHECK"] == "1"
        assert variables["KEPT"] == "1"
    assert release.stdins == [subprocess.DEVNULL] * len(release.runs)


@pytest.mark.parametrize(
    ("root", "sudo_exit", "arguments"),
    [(False, 1, ["install"]), (False, 0, ["install", "--with-deps"]), (True, 1, ["install", "--with-deps"])],
)
def test_with_no_browser_it_installs_chrome_with_system_libraries_only_when_it_can_sudo_unasked(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, root: bool, sudo_exit: int, arguments: list[str]
) -> None:
    release = Release(monkeypatch, LINUX, tmp_path)
    release.launches = [False, True]
    release.sudo_exit = sudo_exit
    monkeypatch.setattr(install.os, "getuid", lambda: 0 if root else 1000)

    installed = install.install_browser()

    assert release.browser_installs() == [arguments]
    assert not installed.already_installed


def test_no_browser_without_system_libraries_names_the_command_that_installs_them(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    release = Release(monkeypatch, LINUX, tmp_path)
    release.launches = [False]

    missing = lib.install(components=["browser"]).not_installed[0]

    assert missing.code == "browser-missing-system-libraries"
    assert f"`{release.directory / 'bin' / 'agent-browser'} install --with-deps`" in missing.remedy
    assert "reality-check install --component browser" in missing.remedy
    assert "No Chrome to launch" in missing.message
    assert not missing.unsupported


def test_a_failed_chrome_download_says_what_agent_browser_said(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    release = Release(monkeypatch, LINUX, tmp_path)
    release.launches = [False]
    release.install_exit = 1

    missing = lib.install(components=["browser"]).not_installed[0]

    assert missing.code == "browser-download-failed"
    assert "Failed to download Chrome" in missing.message


def test_linux_arm64_with_no_chromium_names_the_package_manager_and_never_downloads_chrome(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    release = Release(monkeypatch, LINUX_ARM, tmp_path)
    release.launches = [False]

    missing = lib.install(components=["browser"]).not_installed[0]

    assert missing.code == "browser-no-browser"
    assert "sudo apt install chromium" in missing.remedy
    assert "reality-check install --component browser" in missing.remedy
    assert release.browser_installs() == []


def test_without_certutil_on_linux_the_remaining_step_names_its_package(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    release = Release(monkeypatch, LINUX, tmp_path)
    del release.which["certutil"]

    installed = install.install_browser()

    assert installed.remaining_step is not None
    assert "libnss3-tools" in installed.remaining_step
    assert "nss-tools" in installed.remaining_step


def test_a_binary_that_does_not_match_its_hash_installs_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    Release(monkeypatch, LINUX, tmp_path)
    monkeypatch.setattr(install, "SHA256", {LINUX.asset: "0" * 64})

    missing = lib.install(components=["browser"]).not_installed[0]

    assert missing.code == "browser-download-corrupt"
    assert "SHA-256" in missing.message
    assert not (tmp_path / "data").exists()


def test_a_package_that_does_not_match_its_integrity_installs_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    Release(monkeypatch, LINUX, tmp_path)
    monkeypatch.setattr(install, "INTEGRITY", "sha512-" + base64.b64encode(bytes(64)).decode())

    missing = lib.install(components=["browser"]).not_installed[0]

    assert missing.code == "browser-download-corrupt"
    assert "SHA-512" in missing.message
    assert not (tmp_path / "data").exists()


def test_an_install_folder_that_does_not_run_is_broken(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    release = Release(monkeypatch, LINUX, tmp_path)
    (release.directory / "bin").mkdir(parents=True)
    (release.directory / "bin" / "agent-browser").write_bytes(b"something else")

    missing = lib.install(components=["browser"]).not_installed[0]

    assert missing.code == "browser-install-broken"
    assert release.downloads == []
