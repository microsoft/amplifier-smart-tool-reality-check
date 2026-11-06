"""Chrome for Testing on Linux arm64, which `agent-browser install` refuses, and the system libraries Chromium needs."""

import contextlib
from pathlib import Path, PurePosixPath
import shlex
import shutil
import stat
import subprocess
import zipfile

from reality_check.capabilities.install.download import CHUNK_BYTES, Installing, build_in_place, fetch
from reality_check.schemas import RealityCheckError

# Google publishes no digest for Chrome for Testing, so bumping the version takes the SHA-256 of the zip as downloaded.
VERSION = "157.0.8103.38"
SHA256 = "5517510e61657ff43ee9ab804ecd1a499b3d5bd3caf72f097516bd6565ba5a17"
URL = "https://storage.googleapis.com/chrome-for-testing-public/{version}/linux-arm64/chrome-linux-arm64.zip"
ZIP_ROOT = "chrome-linux-arm64"
# agent-browser finds a browser it did not install when its folder starts with `chrome-` and holds `chrome`.
FOLDER = f"chrome-{VERSION}"
BINARY = "chrome"
# Copied from agent-browser's `install --with-deps`. The second apt name, always the first plus `t64`, is the one Debian
# and Ubuntu gave a library in the 64-bit time_t transition; where it exists, the first has no install candidate.
APT_PACKAGES: tuple[tuple[str, str | None], ...] = (
    ("libxcb-shm0", None),
    ("libx11-xcb1", None),
    ("libx11-6", None),
    ("libxcb1", None),
    ("libxext6", None),
    ("libxrandr2", None),
    ("libxcomposite1", None),
    ("libxcursor1", None),
    ("libxdamage1", None),
    ("libxfixes3", None),
    ("libxi6", None),
    ("libgtk-3-0", "libgtk-3-0t64"),
    ("libpangocairo-1.0-0", "libpangocairo-1.0-0t64"),
    ("libpango-1.0-0", "libpango-1.0-0t64"),
    ("libatk1.0-0", "libatk1.0-0t64"),
    ("libcairo-gobject2", "libcairo-gobject2t64"),
    ("libcairo2", "libcairo2t64"),
    ("libgdk-pixbuf-2.0-0", "libgdk-pixbuf-2.0-0t64"),
    ("libxrender1", None),
    ("libasound2", "libasound2t64"),
    ("libfreetype6", None),
    ("libfontconfig1", None),
    ("libdbus-1-3", "libdbus-1-3t64"),
    ("libnss3", None),
    ("libnss3-tools", None),
    ("libnspr4", None),
    ("libatk-bridge2.0-0", "libatk-bridge2.0-0t64"),
    ("libdrm2", None),
    ("libxkbcommon0", None),
    ("libatspi2.0-0", "libatspi2.0-0t64"),
    ("libcups2", "libcups2t64"),
    ("libxshmfence1", None),
    ("libgbm1", None),
    ("fonts-noto-color-emoji", None),
    ("fonts-noto-cjk", None),
    ("fonts-freefont-ttf", None),
)
DNF_PACKAGES = (
    "nss",
    "nss-tools",
    "nspr",
    "atk",
    "at-spi2-atk",
    "cups-libs",
    "libdrm",
    "libXcomposite",
    "libXdamage",
    "libXrandr",
    "mesa-libgbm",
    "pango",
    "alsa-lib",
    "libxkbcommon",
    "libxcb",
    "libX11-xcb",
    "libX11",
    "libXext",
    "libXcursor",
    "libXfixes",
    "libXi",
    "gtk3",
    "cairo-gobject",
    "google-noto-cjk-fonts",
    "google-noto-emoji-color-fonts",
    "liberation-fonts",
)
YUM_PACKAGES = (
    "nss",
    "nss-tools",
    "nspr",
    "atk",
    "at-spi2-atk",
    "cups-libs",
    "libdrm",
    "libXcomposite",
    "libXdamage",
    "libXrandr",
    "mesa-libgbm",
    "pango",
    "alsa-lib",
    "libxkbcommon",
    "google-noto-cjk-fonts",
    "liberation-fonts",
)
PACKAGE_MANAGERS = ("apt-get", "dnf", "yum")
# apt asks nothing when told it runs unattended, such as whether to keep a changed configuration file.
APT_ENVIRONMENT = ("env", "DEBIAN_FRONTEND=noninteractive")
APT_REMOVES = "Remv "
LOOKUP_TIMEOUT_SECONDS = 15
UPDATE_TIMEOUT_SECONDS = 300
PACKAGES_TIMEOUT_SECONDS = 600
OUTPUT_TAIL_CHARACTERS = 2000


def browsers_directory() -> Path:
    """Where agent-browser looks for the browsers it installed; no variable moves it."""
    return Path.home() / ".agent-browser" / "browsers"


def download_chrome(installing: Installing) -> Path:
    """Unpack the pinned Chrome for Testing where agent-browser finds it, unless it is there; returns its binary."""
    directory = browsers_directory() / FOLDER
    binary = directory / BINARY
    if binary.is_file():
        return binary
    if directory.exists():
        raise RealityCheckError(
            code=f"{installing.component}-install-broken",
            message=f"{directory} is there, but does not hold Chrome for Testing {VERSION}.",
            remedy=f"Move {directory} aside, then run `{installing.command}` again.",
        )

    def build(staging: Path) -> Path:
        archive = staging / "chrome.zip"
        fetch(installing, URL.format(version=VERSION), archive, "sha256", SHA256)
        built = staging / FOLDER
        _unpack(archive, built)
        return built

    build_in_place(installing, directory, build, f"Chrome for Testing {VERSION}")
    return binary


def _unpack(archive: Path, into: Path) -> None:
    """Unpack the zip's one top folder into `into`, keeping each file's permissions; refuses anything else."""
    with zipfile.ZipFile(archive) as unzip:
        for entry in unzip.infolist():
            parts = PurePosixPath(entry.filename).parts
            mode = entry.external_attr >> 16
            if parts[:1] != (ZIP_ROOT,) or ".." in parts:
                raise OSError(f"the zip's {entry.filename!r} is outside {ZIP_ROOT}/")
            if stat.S_ISLNK(mode):
                raise OSError(f"the zip's {entry.filename!r} is a symbolic link")
            path = into.joinpath(*parts[1:])
            if entry.is_dir():
                path.mkdir(parents=True, exist_ok=True)
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            with unzip.open(entry) as source, path.open("wb") as file:
                shutil.copyfileobj(source, file, CHUNK_BYTES)
            # Only the permission bits; a set-user-ID bit from a download is never wanted.
            if mode & 0o777:
                path.chmod(mode & 0o777)
    if not (into / BINARY).is_file():
        raise OSError(f"the zip has no {ZIP_ROOT}/{BINARY}")


def install_system_libraries(installing: Installing, root: bool) -> bool:
    """Install Chromium's system libraries as agent-browser's `install --with-deps` does; False with no known manager.

    Runs as root, or through sudo that must not ask for a password.
    """
    manager = _package_manager()
    if manager is None:
        return False
    if manager == "apt-get":
        # A fresh image may have no package lists, and the t64 names resolve only against them; a failure leaves the
        # lists there were.
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            _run(_privileged(manager, ["update"], root), UPDATE_TIMEOUT_SECONDS)
    packages = _packages(manager)
    try:
        if manager == "apt-get":
            # agent-browser simulates first: on a system mid-transition, apt can propose removing what depends on the
            # old names.
            simulated = _run(_privileged(manager, ["install", "--simulate", *packages], root), PACKAGES_TIMEOUT_SECONDS)
            if simulated.returncode != 0:
                raise _not_installed(installing, _tail(simulated.stderr or simulated.stdout), manager, packages, root)
            removals = [line for line in simulated.stdout.splitlines() if line.startswith(APT_REMOVES)]
            if removals:
                why = f"apt would remove {len(removals)} packages to install them, such as {removals[0]}"
                raise _not_installed(installing, why, manager, packages, root)
        completed = _run(_privileged(manager, ["install", "-y", *packages], root), PACKAGES_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as error:
        why = f"it did not finish within {PACKAGES_TIMEOUT_SECONDS} seconds"
        raise _not_installed(installing, why, manager, packages, root) from error
    except OSError as error:
        raise _not_installed(installing, str(error), manager, packages, root) from error
    if completed.returncode != 0:
        raise _not_installed(installing, _tail(completed.stderr or completed.stdout), manager, packages, root)
    return True


def system_libraries_command() -> str | None:
    """What a person runs here to install Chromium's system libraries through sudo; None with no known manager."""
    manager = _package_manager()
    if manager is None:
        return None
    if manager != "apt-get":
        return _typed(manager, _packages(manager), root=False)
    named, undecided = _apt_names()
    return _typed(manager, named, root=False, undecided=tuple(undecided))


def _package_manager() -> str | None:
    return next((manager for manager in PACKAGE_MANAGERS if shutil.which(manager) is not None), None)


def _packages(manager: str) -> list[str]:
    if manager == "dnf":
        return list(DNF_PACKAGES)
    if manager == "yum":
        return list(YUM_PACKAGES)
    named, undecided = _apt_names()
    return [*named, *undecided]


def _apt_names() -> tuple[list[str], list[str]]:
    """The apt names of Chromium's libraries, and the libraries apt's lists here name under neither of their names."""
    named: list[str] = []
    undecided: list[str] = []
    for name, renamed in APT_PACKAGES:
        if renamed is not None and _apt_has(renamed):
            named.append(renamed)
        elif renamed is None or _apt_has(name):
            named.append(name)
        else:
            undecided.append(name)
    return named, undecided


def _apt_has(package: str) -> bool:
    try:
        return _run(["apt-cache", "show", package], LOOKUP_TIMEOUT_SECONDS).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _privileged(manager: str, arguments: list[str], root: bool) -> list[str]:
    environment = list(APT_ENVIRONMENT) if manager == "apt-get" else []
    return [*([] if root else ["sudo", "-n"]), *environment, manager, *arguments]


def _typed(manager: str, packages: list[str], root: bool, undecided: tuple[str, ...] = ()) -> str:
    sudo = [] if root else ["sudo"]
    install = shlex.join([*sudo, manager, "install", "-y", *packages])
    if manager != "apt-get":
        return install
    if undecided:
        # apt has no lists before `apt-get update`, which needs sudo, so the command picks these names after it runs.
        picked = 'apt-cache show "${p}t64" >/dev/null 2>&1 && echo "${p}t64" || echo "$p"'
        install += f" $(for p in {' '.join(undecided)}; do {picked}; done)"
    return f"{shlex.join([*sudo, manager, 'update'])} && {install}"


def _not_installed(
    installing: Installing, why: str, manager: str, packages: list[str], root: bool
) -> RealityCheckError:
    return RealityCheckError(
        code=f"{installing.component}-missing-system-libraries",
        message=f"Could not install the system libraries Chromium needs with {manager}: {why}",
        remedy=f"Run `{_typed(manager, packages, root)}`, then run `{installing.command}` again.",
    )


def _run(arguments: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
    """Run a command with nothing to read, so it never waits on a prompt; raises OSError and TimeoutExpired."""
    return subprocess.run(
        arguments,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )


def _tail(output: str) -> str:
    return output.strip()[-OUTPUT_TAIL_CHARACTERS:]
