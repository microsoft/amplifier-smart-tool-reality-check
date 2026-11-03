"""Install the pinned agent-browser once, and make sure a browser it drives launches."""

import base64
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile

import platformdirs

from reality_check.capabilities.browser.target import Target, Unavailable, resolve_target
from reality_check.capabilities.install.download import Installing, build_in_place, fetch
from reality_check.core.skill import DISTRIBUTION
from reality_check.schemas import BrowserInstall, RealityCheckError

# Bumping the version takes the new release's binaries' SHA-256 and the npm package's `dist.integrity`.
VERSION = "0.41.1"
SHA256 = {
    "agent-browser-linux-x64": "2a89295b62ddd497986a9a80b52e1dbe4c1f6bd68ffde67eaae82eec2206af61",
    "agent-browser-linux-arm64": "f0b3bdaa40abf2a5111ec08e6d242110aaf56045ef5108cbc633bacc8e53ca17",
    "agent-browser-linux-musl-x64": "951c795e21fddab1d4091ad2ca4f0e69f1eea6534288e6a251598df11ca8e9af",
    "agent-browser-linux-musl-arm64": "3afdec8f37bfd80b2ecc30e2297c95c3bae9ddb3775ebe531534ea6e3662f44c",
    "agent-browser-darwin-x64": "7802f053e7fb25e10548ee10ca60d892c73d42ed2dbb7fc30c2d5925a5c82859",
    "agent-browser-darwin-arm64": "63b0a97b85a54b4c9b2871318af74104c29b80abd507b53a30316884e062854b",
    "agent-browser-win32-x64.exe": "ddab45e8bae84e5bc6aa1b084bceca9b579aff2e8272474d7d26953cf10965ee",
}
# The release binary carries no skills; the npm package does, under `package/skill-data`.
INTEGRITY = "sha512-9DhCeIhcpxu3Mj+f25Bolk6N+BT5SpOttRSZw0Ytz5MZ8zpKeVp2bv9Zxo1gajlvZE3l//rOoiRdq+qTYHBg1Q=="
RELEASE_URL = "https://github.com/vercel-labs/agent-browser/releases/download/v{version}/{asset}"
PACKAGE_URL = "https://registry.npmjs.org/agent-browser/-/agent-browser-{version}.tgz"
INSTALL_COMMAND = "reality-check install --component browser"
INSTALLING = Installing("browser", INSTALL_COMMAND)
VERSION_PATTERN = re.compile(r"^agent-browser (\d+\.\d+\.\d+)\b")
SKILLS = "skill-data"
PACKAGE_ROOT = "package/"
# Only doctor checks on finding and launching a browser decide whether one works; the rest are about other features.
LAUNCH_CHECKS = ("chrome.", "launch.")
LAUNCHED = "launch.elapsed"
VERSION_TIMEOUT_SECONDS = 15
DOCTOR_TIMEOUT_SECONDS = 90
BROWSER_TIMEOUT_SECONDS = 600
SUDO_TIMEOUT_SECONDS = 15
# Help waits on sudo only briefly; a sudo that takes longer is treated as asking for a password.
SUDO_PROBE_TIMEOUT_SECONDS = 2
OUTPUT_TAIL_CHARACTERS = 2000


def install_browser() -> BrowserInstall:
    """Find the pinned agent-browser, or download and verify it, then make sure a headless browser it drives launches."""
    target = resolve_target()
    if isinstance(target, Unavailable):
        raise RealityCheckError(
            code="browser-unsupported",
            message=f"agent-browser cannot run here. {target.reason}",
            remedy=target.remedy or "Run reality-check on a supported OS and architecture to check web apps' UIs.",
        )
    executable = own_executable(target)
    already = executable.is_file() and installed_version(executable) == VERSION
    if not already:
        _download(target)
    failures = launch_failures(executable)
    if failures:
        already = False
        with_dependencies = _install_browser(target, executable, failures)
        failures = launch_failures(executable)
        if failures:
            raise _does_not_launch(target, executable, with_dependencies, failures)
    return BrowserInstall(
        version=VERSION,
        executable=executable,
        skills_directory=skills_directory(),
        already_installed=already,
        remaining_step=_remaining_step(target, executable),
    )


def on_this_machine() -> str:
    """What installing the browser does here, from cheap local checks; never runs agent-browser or downloads."""
    target = resolve_target()
    if isinstance(target, Unavailable):
        return " ".join(
            part for part in ("Not supported here, so it is skipped.", target.reason, target.remedy) if part
        )
    executable = own_executable(target)
    if executable.is_file():
        lines = [f"agent-browser {VERSION} is already at `{executable}`, so nothing is downloaded when it runs."]
    else:
        lines = [f"Installs agent-browser {VERSION}, the `{target.asset}` release asset, into `{own_directory()}`."]
    if not target.chrome_for_testing:
        lines.append(
            f"Chrome for Testing has no `{target.label}` build, so a browser takes the distribution's Chromium, "
            "such as `sudo apt install chromium`."
        )
    elif not target.linux:
        lines.append("When no browser launches, it downloads Chrome for Testing into `~/.agent-browser/browsers`.")
    elif os.getuid() == 0 or _can_sudo(SUDO_PROBE_TIMEOUT_SECONDS):
        lines.append(
            "When no browser launches, it downloads Chrome for Testing and installs Chromium's system libraries, "
            "since this runs as root or sudo needs no password here."
        )
    else:
        lines.append(
            "When no browser launches, it downloads Chrome for Testing but cannot install Chromium's system "
            f"libraries, since sudo needs a password here; if it still does not launch, the failure names "
            f"`{executable} install --with-deps`."
        )
    if target.linux:
        if shutil.which("certutil") is None:
            lines.append("`certutil` is missing, so `remaining_step` names the package that provides it.")
        else:
            lines.append("`certutil` is there, so checks' browsers trust this machine's certificates.")
    return " ".join(lines)


def own_directory() -> Path:
    """Where reality-check keeps its own agent-browser; one on PATH may be any version, laid out any way."""
    return platformdirs.user_data_path(DISTRIBUTION, appauthor=False, roaming=False) / "agent-browser" / VERSION


def own_executable(target: Target) -> Path:
    return own_directory() / "bin" / target.executable_name


def skills_directory() -> Path:
    return own_directory() / SKILLS


def variables() -> dict[str, str]:
    """What every agent-browser process gets: its skills found where reality-check put them, no update check."""
    # agent-browser finds the skills only through this variable, not beside its binary.
    return {"AGENT_BROWSER_SKILLS_DIR": str(skills_directory()), "AGENT_BROWSER_NO_VERSION_CHECK": "1"}


def environment() -> dict[str, str]:
    """This process's environment for agent-browser, with `variables()`."""
    return {**os.environ, **variables()}


def run_agent_browser(executable: Path, arguments: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
    """Run agent-browser once with nothing to read, so it never waits on a prompt; raises OSError and TimeoutExpired."""
    return subprocess.run(
        [str(executable), *arguments],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=environment(),
        timeout=timeout,
        check=False,
    )


def installed_version(executable: Path) -> str | None:
    """The version `executable --version` reports, or None when it does not run or says something else."""
    try:
        completed = run_agent_browser(executable, ["--version"], VERSION_TIMEOUT_SECONDS)
    except (OSError, subprocess.SubprocessError):
        return None
    match = VERSION_PATTERN.match(completed.stdout.strip())
    return match.group(1) if completed.returncode == 0 and match else None


def launch_failures(executable: Path) -> list[str]:
    """Why agent-browser cannot launch a headless browser, from its own doctor; empty when one launches."""
    try:
        completed = run_agent_browser(executable, ["doctor", "--offline", "--json"], DOCTOR_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        return [f"`agent-browser doctor` did not finish within {DOCTOR_TIMEOUT_SECONDS} seconds."]
    except OSError as error:
        return [f"`agent-browser doctor` did not run: {error}"]
    try:
        checks = json.loads(completed.stdout)["checks"]
        failures = [
            check["message"] for check in checks if check["id"].startswith(LAUNCH_CHECKS) and check["status"] == "fail"
        ]
        launched = any(check["id"] == LAUNCHED and check["status"] == "pass" for check in checks)
    except (ValueError, KeyError, TypeError):
        return [f"`agent-browser doctor` printed no report: {_tail(completed.stderr or completed.stdout)}"]
    if not failures and not launched:
        failures.append("The headless launch test did not pass.")
    return failures


def _download(target: Target) -> None:
    """Download the pinned binary and the npm package's skills, verify both, and move them into place whole."""
    directory = own_directory()
    if directory.exists():
        raise RealityCheckError(
            code="browser-install-broken",
            message=f"{directory} is there, but does not hold a working agent-browser {VERSION}.",
            remedy=f"Move {directory} aside, then run `{INSTALL_COMMAND}` again.",
        )

    def build(staging: Path) -> Path:
        built = staging / "agent-browser"
        binary = built / "bin" / target.executable_name
        binary.parent.mkdir(parents=True)
        url = RELEASE_URL.format(version=VERSION, asset=target.asset)
        fetch(INSTALLING, url, binary, "sha256", SHA256[target.asset])
        if sys.platform != "win32":
            binary.chmod(0o755)
        package = staging / "package.tgz"
        fetch(INSTALLING, PACKAGE_URL.format(version=VERSION), package, "sha512", _integrity_hex(INTEGRITY))
        _extract_package(package, built)
        return built

    build_in_place(INSTALLING, directory, build, f"agent-browser {VERSION}")
    executable = own_executable(target)
    if installed_version(executable) != VERSION:
        raise RealityCheckError(
            code="browser-install-broken",
            message=f"agent-browser {VERSION} was unpacked into {directory}, but {executable} does not run.",
            remedy=f"Run `{executable} --version` to see why.",
        )


def _integrity_hex(integrity: str) -> str:
    """The hex digest in an npm `sha512-<base64>` integrity string."""
    return base64.b64decode(integrity.removeprefix("sha512-")).hex()


def _extract_package(package: Path, into: Path) -> None:
    """Unpack only the skills and the license from the npm package, without its `package/` folder."""
    with tarfile.open(package) as untar:
        wanted = [
            member.replace(name=name, deep=False)
            for member in untar.getmembers()
            if member.name.startswith(PACKAGE_ROOT)
            and ((name := member.name.removeprefix(PACKAGE_ROOT)) == "LICENSE" or name.startswith(f"{SKILLS}/"))
        ]
        if not any(member.name.startswith(f"{SKILLS}/") for member in wanted):
            raise OSError(f"the npm package has no {SKILLS}")
        untar.extractall(into, members=wanted, filter="data")


def _install_browser(target: Target, executable: Path, failures: list[str]) -> bool:
    """Download Chrome for Testing, with its system libraries when sudo needs no password; returns whether it did."""
    if not target.chrome_for_testing:
        raise RealityCheckError(
            code="browser-no-browser",
            message=f"Chrome for Testing has no {target.label} build, and no system Chromium launches: "
            f"{' '.join(failures)}",
            remedy="Install Chromium from the system package manager, such as `sudo apt install chromium`, "
            f"`sudo dnf install chromium`, or `sudo apk add chromium`, then run `{INSTALL_COMMAND}` again.",
        )
    # agent-browser runs the package manager through sudo itself, so Chrome still lands in this user's home.
    with_dependencies = target.linux and _can_sudo(SUDO_TIMEOUT_SECONDS)
    arguments = ["install", "--with-deps"] if with_dependencies else ["install"]
    try:
        completed = run_agent_browser(executable, arguments, BROWSER_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as error:
        raise _not_downloaded(arguments, f"it did not finish within {BROWSER_TIMEOUT_SECONDS} seconds") from error
    except OSError as error:
        raise _not_downloaded(arguments, str(error)) from error
    if completed.returncode != 0:
        raise _not_downloaded(arguments, _tail(completed.stderr or completed.stdout))
    return with_dependencies


def _not_downloaded(arguments: list[str], why: str) -> RealityCheckError:
    return RealityCheckError(
        code="browser-download-failed",
        message=f"`agent-browser {' '.join(arguments)}` could not install a browser: {why}",
        remedy="Check that this machine reaches googlechromelabs.github.io and storage.googleapis.com, then run "
        f"`{INSTALL_COMMAND}` again.",
    )


def _can_sudo(timeout: float) -> bool:
    """Whether this process is root or can run sudo without a password, so nothing waits on one."""
    if os.getuid() == 0:
        return True
    if shutil.which("sudo") is None:
        return False
    try:
        return (
            subprocess.run(
                ["sudo", "-n", "true"],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=timeout,
                check=False,
            ).returncode
            == 0
        )
    except (OSError, subprocess.SubprocessError):
        return False


def _does_not_launch(
    target: Target, executable: Path, with_dependencies: bool, failures: list[str]
) -> RealityCheckError:
    if target.linux and not with_dependencies:
        return RealityCheckError(
            code="browser-missing-system-libraries",
            message=f"The headless browser agent-browser installed does not launch, most likely for want of the "
            f"system libraries Chromium needs: {' '.join(failures)}",
            remedy=f"Run `{executable} install --with-deps`, which installs Chromium's system libraries through "
            f"sudo, then run `{INSTALL_COMMAND}` again.",
        )
    return RealityCheckError(
        code="browser-launch-failed",
        message=f"agent-browser cannot launch a headless browser: {' '.join(failures)}",
        remedy=f"Run `{executable} doctor` to see why, then run `{INSTALL_COMMAND}` again.",
    )


def _remaining_step(target: Target, executable: Path) -> str | None:
    # agent-browser hands this machine's certificate authorities to Chromium through certutil.
    if not target.linux or shutil.which("certutil") is not None:
        return None
    return (
        "Install `libnss3-tools` (Debian/Ubuntu) or `nss-tools` (Fedora/RHEL) so checks' browsers trust the "
        f"certificates this machine trusts; `{executable} install --with-deps` also installs it."
    )


def _tail(output: str) -> str:
    return output.strip()[-OUTPUT_TAIL_CHARACTERS:]
