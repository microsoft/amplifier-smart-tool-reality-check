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
import zipfile

import pytest

from reality_check import lib
from reality_check.capabilities.browser import chrome, install, target
from reality_check.capabilities.browser.target import Target, Unavailable
from reality_check.capabilities.install import download

LINUX = Target("linux-x64")
LINUX_ARM = Target("linux-arm64")
MUSL = Target("linux-musl-arm64")
CHROME_URL = chrome.URL.format(version=chrome.VERSION)
# Each entry's bytes and Unix mode, as Chrome for Testing's zip has them: one top folder, and no symbolic links.
CHROME_ZIP: dict[str, tuple[bytes, int]] = {
    "chrome-linux-arm64/": (b"", stat.S_IFDIR | 0o755),
    "chrome-linux-arm64/chrome": (b"chrome", stat.S_IFREG | 0o755),
    "chrome-linux-arm64/deb.deps": (b"libnss3", stat.S_IFREG | 0o600),
    "chrome-linux-arm64/locales/en-US.pak": (b"pak", stat.S_IFREG | 0o644),
}
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


def doctor_report(launches: bool | str) -> str:
    """What `agent-browser doctor --offline --json` prints, with a failure unrelated to launching either way.

    `launches` is True, False for no browser, or "daemon" for a daemon that does not start.
    """
    checks = [
        {"category": "Environment", "id": "env.version", "message": "CLI version 0.41.1", "status": "pass"},
        {"category": "Recording", "id": "recording.ffmpeg", "message": "ffmpeg not found", "status": "fail"},
        {"category": "Chrome", "id": "chrome.cache_dir", "message": "Cache dir", "status": "info"},
    ]
    if launches == "daemon":
        checks += [
            {"category": "Chrome", "id": "chrome.installed", "message": "Chrome 147", "status": "pass"},
            {
                "category": "Launch test",
                "id": "launch.daemon",
                "message": "Could not start daemon: Session name 'doctor-1-2' is too long.",
                "status": "fail",
            },
        ]
    elif launches:
        checks += [
            {"category": "Chrome", "id": "chrome.installed", "message": "Chrome 147", "status": "pass"},
            {"category": "Launch test", "id": "launch.elapsed", "message": "Launched in 0.29s", "status": "pass"},
        ]
    else:
        checks += [
            {"category": "Chrome", "id": "chrome.installed", "message": "Chrome not found", "status": "fail"},
            {"category": "Launch test", "id": "launch.launch", "message": "No Chrome to launch", "status": "fail"},
        ]
    return json.dumps({"checks": checks, "fixed": [], "success": launches is True, "summary": {}})


def zipped(entries: dict[str, tuple[bytes, int]]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, (data, mode) in entries.items():
            info = zipfile.ZipInfo(name)
            info.create_system = 3
            info.external_attr = mode << 16
            archive.writestr(info, data)
    return buffer.getvalue()


class Release:
    """A fake release, npm registry, and Chrome for Testing served by a fake `urlopen`, and a fake agent-browser,
    sudo, doctor, and package managers."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, chosen: Target, home: Path) -> None:
        self.monkeypatch = monkeypatch
        self.target = chosen
        self.home = home
        self.downloads: list[str] = []
        self.runs: list[list[str]] = []
        self.environments: list[dict[str, str]] = []
        self.stdins: list[Any] = []
        # Whether each doctor run finds a browser that launches, in order; the last one repeats.
        self.launches: list[bool | str] = [True]
        self.install_exit = 0
        self.sudo_exit = 1
        # The packages `apt-cache show` knows, and what `apt-get install --simulate` prints.
        self.apt_known = {"libasound2t64", "libgtk-3-0t64"}
        self.simulated = "Inst libnss3\n"
        self.package = self._package()
        self.served = {
            install.RELEASE_URL.format(version=install.VERSION, asset=chosen.asset): BINARY,
            install.PACKAGE_URL.format(version=install.VERSION): self.package,
        }
        self.which = {"sudo": "/usr/bin/sudo", "certutil": "/usr/bin/certutil"}
        self.serve_chrome(CHROME_ZIP)
        monkeypatch.setenv("HOME", str(home / "home"))
        # agent-browser's sockets go under it, so these tests never make the short socket folder.
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(home / "run"))
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

    @property
    def chrome(self) -> Path:
        return self.home / "home" / ".agent-browser" / "browsers" / f"chrome-{chrome.VERSION}"

    def serve_chrome(self, entries: dict[str, tuple[bytes, int]]) -> None:
        data = zipped(entries)
        self.served[CHROME_URL] = data
        self.monkeypatch.setattr(chrome, "SHA256", hashlib.sha256(data).hexdigest())

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
        if arguments == ["sudo", "-n", "true"]:
            return subprocess.CompletedProcess(arguments, self.sudo_exit, "", "")
        command = arguments[2:] if arguments[:2] == ["sudo", "-n"] else arguments
        command = command[2:] if command[:1] == ["env"] else command
        match command:
            case ["apt-cache", "show", package]:
                return subprocess.CompletedProcess(arguments, 0 if package in self.apt_known else 100, "", "")
            case ["apt-get", "install", "--simulate", *_]:
                return subprocess.CompletedProcess(arguments, 0, self.simulated, "")
            case ["apt-get" | "dnf" | "yum", *_]:
                return subprocess.CompletedProcess(arguments, 0, "", "")
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

    def package_runs(self) -> list[list[str]]:
        return [run for run in self.runs if run != ["sudo", "-n", "true"] and run[0] in ("sudo", "env", "dnf", "yum")]


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


def test_linux_arm64_with_no_browser_unpacks_chrome_for_testing_where_agent_browser_finds_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    release = Release(monkeypatch, LINUX_ARM, tmp_path)
    release.launches = [False, True]

    installed = install.install_browser()

    assert release.downloads[-1] == (
        "https://storage.googleapis.com/chrome-for-testing-public/157.0.8103.38/linux-arm64/chrome-linux-arm64.zip"
    )
    assert sorted(str(path.relative_to(release.chrome)) for path in release.chrome.rglob("*") if path.is_file()) == [
        "chrome",
        "deb.deps",
        "locales/en-US.pak",
    ]
    if sys.platform != "win32":
        assert stat.S_IMODE(release.chrome.joinpath("chrome").stat().st_mode) == 0o755
        assert stat.S_IMODE(release.chrome.joinpath("deb.deps").stat().st_mode) == 0o600
    assert list(release.chrome.parent.iterdir()) == [release.chrome]
    assert release.browser_installs() == []
    assert release.package_runs() == []
    assert not installed.already_installed


def test_linux_arm64_with_chrome_for_testing_unpacked_downloads_it_again_never(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    release = Release(monkeypatch, LINUX_ARM, tmp_path)
    release.launches = [False, True]
    release.chrome.mkdir(parents=True)
    (release.chrome / "chrome").write_bytes(b"chrome")

    install.install_browser()

    assert CHROME_URL not in release.downloads


@pytest.mark.parametrize(
    ("name", "mode"),
    [
        ("chrome-linux-arm64/../escaped", stat.S_IFREG | 0o644),
        ("/escaped", stat.S_IFREG | 0o644),
        ("other/escaped", stat.S_IFREG | 0o644),
        ("chrome-linux-arm64/link", stat.S_IFLNK | 0o777),
    ],
)
def test_a_chrome_zip_entry_outside_its_folder_or_a_link_installs_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, name: str, mode: int
) -> None:
    release = Release(monkeypatch, LINUX_ARM, tmp_path)
    release.launches = [False]
    release.serve_chrome({**CHROME_ZIP, name: (b"/etc/passwd", mode)})

    missing = lib.install(components=["browser"]).not_installed[0]

    assert missing.code == "browser-install-failed"
    assert not release.chrome.exists()
    assert not list(tmp_path.rglob("escaped"))


@pytest.mark.parametrize(
    ("root", "managers", "expected"),
    [
        (
            False,
            ["apt-get"],
            [
                ["sudo", "-n", "env", "DEBIAN_FRONTEND=noninteractive", "apt-get", "update"],
                ["sudo", "-n", "env", "DEBIAN_FRONTEND=noninteractive", "apt-get", "install", "--simulate"],
                ["sudo", "-n", "env", "DEBIAN_FRONTEND=noninteractive", "apt-get", "install", "-y"],
            ],
        ),
        (
            True,
            ["apt-get"],
            [
                ["env", "DEBIAN_FRONTEND=noninteractive", "apt-get", "update"],
                ["env", "DEBIAN_FRONTEND=noninteractive", "apt-get", "install", "--simulate"],
                ["env", "DEBIAN_FRONTEND=noninteractive", "apt-get", "install", "-y"],
            ],
        ),
        (False, ["dnf", "yum"], [["sudo", "-n", "dnf", "install", "-y"]]),
        (True, ["yum"], [["yum", "install", "-y"]]),
    ],
)
def test_linux_arm64_installs_system_libraries_itself_when_it_can_sudo_unasked(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, root: bool, managers: list[str], expected: list[list[str]]
) -> None:
    release = Release(monkeypatch, LINUX_ARM, tmp_path)
    release.launches = [False, True]
    release.sudo_exit = 0
    release.which.update({manager: f"/usr/bin/{manager}" for manager in managers})
    monkeypatch.setattr(install.os, "getuid", lambda: 0 if root else 1000)

    install.install_browser()

    runs = release.package_runs()
    assert [run[: len(prefix)] for run, prefix in zip(runs, expected, strict=True)] == expected
    packages = runs[-1][len(expected[-1]) :]
    if managers[0] == "apt-get":
        assert "libasound2t64" in packages
        assert "libgtk-3-0t64" in packages
        assert "libcups2" in packages
        assert "libnss3" in packages
    else:
        assert packages == list(chrome.DNF_PACKAGES if managers[0] == "dnf" else chrome.YUM_PACKAGES)


def test_linux_arm64_installs_no_system_libraries_apt_would_remove_packages_for(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    release = Release(monkeypatch, LINUX_ARM, tmp_path)
    release.launches = [False]
    release.sudo_exit = 0
    release.which["apt-get"] = "/usr/bin/apt-get"
    release.simulated = "Remv libasound2 [1.2.11]\nInst libasound2t64\n"

    missing = lib.install(components=["browser"]).not_installed[0]

    assert missing.code == "browser-missing-system-libraries"
    assert "apt would remove 1 packages" in missing.message
    assert "sudo apt-get update && sudo apt-get install -y" in missing.remedy
    assert not any("-y" in run for run in release.package_runs())


def test_linux_arm64_without_sudo_names_this_machine_s_package_command(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    release = Release(monkeypatch, LINUX_ARM, tmp_path)
    release.launches = [False]
    release.which["apt-get"] = "/usr/bin/apt-get"
    release.apt_known |= {name for name, _ in chrome.APT_PACKAGES}

    missing = lib.install(components=["browser"]).not_installed[0]

    assert missing.code == "browser-missing-system-libraries"
    assert "sudo apt-get update && sudo apt-get install -y libxcb-shm0 " in missing.remedy
    assert " libasound2t64 " in missing.remedy
    assert " libcups2 " in missing.remedy
    assert "$(" not in missing.remedy
    assert "--with-deps" not in missing.remedy
    assert "reality-check install --component browser" in missing.remedy
    assert release.chrome.joinpath("chrome").is_file()
    assert [run for run in release.package_runs() if run[0] == "sudo"] == []


def test_linux_arm64_without_apt_lists_names_the_command_that_picks_the_libraries_names_after_the_update(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    release = Release(monkeypatch, LINUX_ARM, tmp_path)
    release.launches = [False]
    release.which["apt-get"] = "/usr/bin/apt-get"
    release.apt_known = set()

    missing = lib.install(components=["browser"]).not_installed[0]

    renamed = " ".join(name for name, t64 in chrome.APT_PACKAGES if t64 is not None)
    assert "sudo apt-get update && sudo apt-get install -y libxcb-shm0 " in missing.remedy
    assert f"$(for p in {renamed}; do apt-cache show " in missing.remedy
    assert "t64 " not in missing.remedy.split("$(")[0]


def test_linux_musl_with_no_chromium_names_the_package_manager_and_never_downloads_chrome(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    release = Release(monkeypatch, MUSL, tmp_path)
    release.launches = [False]

    missing = lib.install(components=["browser"]).not_installed[0]

    assert missing.code == "browser-no-browser"
    assert "musl" in missing.message
    assert "sudo apk add chromium" in missing.remedy
    assert "reality-check install --component browser" in missing.remedy
    assert release.browser_installs() == []
    assert CHROME_URL not in release.downloads


def test_a_daemon_that_does_not_start_fails_before_any_browser_install(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    release = Release(monkeypatch, LINUX_ARM, tmp_path)
    release.launches = ["daemon"]

    missing = lib.install(components=["browser"]).not_installed[0]

    assert missing.code == "browser-daemon-failed"
    assert "Could not start daemon: Session name 'doctor-1-2' is too long." in missing.message
    assert f"`{release.directory / 'bin' / 'agent-browser'} doctor`" in missing.remedy
    assert "AGENT_BROWSER_SOCKET_DIR" in missing.remedy
    assert release.browser_installs() == []
    assert CHROME_URL not in release.downloads


@pytest.fixture
def sockets(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """The short socket folder, under the test's own; with no socket variable set and a home that fits."""
    monkeypatch.delenv("AGENT_BROWSER_SOCKET_DIR", raising=False)
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    monkeypatch.setenv("HOME", "/home/me")
    directory = tmp_path / "rc-ab"
    monkeypatch.setattr(install, "SHORT_SOCKET_DIRECTORY", str(directory))
    return directory


def long_home(monkeypatch: pytest.MonkeyPatch) -> None:
    """A home whose `.agent-browser/<session>.sock` is one byte past the limit for the longest session."""
    length = install.SOCKET_PATH_BYTES - len("/.agent-browser/") - install.SESSION_BYTES - len(".sock") + 1
    monkeypatch.setenv("HOME", "/" + "h" * (length - 1))


@pytest.mark.skipif(sys.platform == "win32", reason="agent-browser uses no Unix sockets on Windows")
@pytest.mark.parametrize(
    ("variables", "long"),
    [
        ({"AGENT_BROWSER_SOCKET_DIR": "/s"}, True),
        ({"XDG_RUNTIME_DIR": "/run/user/1000"}, True),
        ({"AGENT_BROWSER_SOCKET_DIR": "", "XDG_RUNTIME_DIR": ""}, False),
    ],
)
def test_agent_browser_keeps_its_own_socket_folder_when_it_holds_every_session(
    monkeypatch: pytest.MonkeyPatch, sockets: Path, variables: dict[str, str], long: bool
) -> None:
    for name, value in variables.items():
        monkeypatch.setenv(name, value)
    if long:
        long_home(monkeypatch)

    assert install.socket_directory() is None
    assert "AGENT_BROWSER_SOCKET_DIR" not in install.variables()
    assert not sockets.exists()


@pytest.mark.skipif(sys.platform == "win32", reason="agent-browser uses no Unix sockets on Windows")
def test_a_home_too_long_for_agent_browser_s_sockets_gets_a_private_short_folder(
    monkeypatch: pytest.MonkeyPatch, sockets: Path
) -> None:
    monkeypatch.setenv("HOME", "/" + "h" * (len("/.agent-browser/") - 1))
    assert install.socket_directory() is None
    long_home(monkeypatch)
    # A umask that also takes the owner's write bit, which the folder must have back.
    previous = install.os.umask(0o277)

    try:
        directory = install.socket_directory()
    finally:
        install.os.umask(previous)

    assert directory == sockets
    assert stat.S_IMODE(sockets.stat().st_mode) == 0o700
    assert install.variables()["AGENT_BROWSER_SOCKET_DIR"] == str(sockets)
    assert install.socket_directory() == sockets


@pytest.mark.skipif(sys.platform == "win32", reason="agent-browser uses no Unix sockets on Windows")
@pytest.mark.parametrize("unsafe", ["link", "file", "open", "owner"])
def test_a_short_socket_folder_others_could_use_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, sockets: Path, unsafe: str
) -> None:
    long_home(monkeypatch)
    real = tmp_path / "real"
    real.mkdir(mode=0o700)
    if unsafe == "link":
        sockets.symlink_to(real)
    elif unsafe == "file":
        sockets.write_text("", encoding="utf-8")
    elif unsafe == "open":
        sockets.mkdir()
        sockets.chmod(0o755)
    else:
        sockets.mkdir(mode=0o700)
        uid = install.os.getuid()
        monkeypatch.setattr(install.os, "getuid", lambda: uid + 1)

    with pytest.raises(install.RealityCheckError) as raised:
        install.variables()

    assert raised.value.code == "browser-socket-directory"
    assert str(sockets) in raised.value.message
    assert "AGENT_BROWSER_SOCKET_DIR" in raised.value.remedy


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
