"""Install the pinned cua-driver once, and find it again for every check."""

from collections.abc import Iterator
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import zipfile

import platformdirs

from reality_check.capabilities.computer_use.target import (
    Target,
    Unavailable,
    resolve_target,
    run_driver,
    windows_folders,
)
from reality_check.capabilities.install.download import Installing, build_in_place, fetch
from reality_check.core.skill import DISTRIBUTION
from reality_check.schemas import ComputerUseInstall, RealityCheckError

# Bumping the version takes the new release's SHA256SUMS for every asset below.
VERSION = "0.36.0"
SHA256 = {
    "cua-driver-rs-0.36.0-windows-x86_64-binary.zip": "f8c47024b626f4e0e70f8428d2998df39e4879110c5722a29d5fd03e367353ad",
    "cua-driver-rs-0.36.0-windows-arm64-binary.zip": "520ea584cf11c074bccc4fd2328e8f2b34ec43de9328d97afb7fd03f761b55ee",
    "cua-driver-rs-0.36.0-linux-x86_64-binary.tar.gz": "05dae2160c86bdf4855c279d30898213d7a150edb1992b7470afdd69f0df4064",
    "cua-driver-rs-0.36.0-linux-arm64-binary.tar.gz": "f64a33889605944a4e5af0e6036496137a25d6375f041d7c56e65c3be456aab2",
    "cua-driver-rs-0.36.0-darwin-universal.tar.gz": "2a83cf9c3a2fa7ae27f3fe62e426aeca5acf76511bb14dd64d10ccb2de6aecae",
}
# A pre-release tag, so never `releases/latest`.
RELEASE_URL = "https://github.com/trycua/cua/releases/download/cua-driver-rs-v{version}/{asset}"
INSTALL_COMMAND = "reality-check install --component computer-use"
INSTALLING = Installing("computer-use", INSTALL_COMMAND)
# macOS grants Accessibility and Screen Recording to the app where it is, and the vendor's own installer puts it here.
MACOS_APP = Path("/Applications/CuaDriver.app")
MACOS_EXECUTABLE = Path("Contents/MacOS/cua-driver")
VERSION_PATTERN = re.compile(r"^cua-driver (\d+\.\d+\.\d+)\b")
VERSION_TIMEOUT_SECONDS = 15
DESKTOPS = {
    "windows": "this Windows desktop",
    "wsl": "the Windows desktop",
    "linux": "this Linux desktop",
    "macos": "this Mac's desktop",
}


def install_computer_use() -> ComputerUseInstall:
    """Find the pinned cua-driver, or download, verify, and unpack it where reality-check keeps it."""
    target = resolve_target()
    if isinstance(target, Unavailable):
        raise RealityCheckError(
            code="computer-use-unsupported",
            message=f"Computer use cannot run here. {target.reason}",
            remedy=target.remedy or "Run reality-check on a supported desktop to check desktop apps.",
        )
    found = locate(target)
    if found is None:
        found = _download(target)
        already = False
    else:
        already = True
    return ComputerUseInstall(
        target=target.kind,
        version=VERSION,
        executable=found,
        already_installed=already,
        remaining_step=_remaining_step(target, found),
    )


def on_this_machine() -> str:
    """What installing computer use does here, from cheap local checks; never runs cua-driver or downloads."""
    target = resolve_target()
    if isinstance(target, Unavailable):
        return " ".join(
            part for part in ("Not supported here, so it is skipped.", target.reason, target.remedy) if part
        )
    match target.kind:
        case "wsl":
            # Finding the Windows user's folders starts cmd.exe, which is too slow for help.
            where = f"the Windows build (`{target.asset(VERSION)}`) into the Windows user's LocalAppData"
        case "macos":
            where = f"`{MACOS_APP.name}` into `{MACOS_APP.parent}`"
        case _:
            where = f"the `{target.asset(VERSION)}` build into `{own_directory(target)}`"
    lines = [f"Installs cua-driver {VERSION}, {where}; checks drive {DESKTOPS[target.kind]}."]
    on_path = shutil.which(target.executable_name)
    if on_path:
        lines.append(f"`{on_path}` is on PATH and is used instead when it is cua-driver {VERSION}.")
    if target.kind != "wsl" and own_executable(target).is_file():
        lines.append(f"`{own_executable(target)}` is already there, so nothing is downloaded when it runs.")
    remaining = _remaining_step(target, own_executable(target))
    if remaining:
        lines.append(remaining)
    return " ".join(lines)


def locate(target: Target) -> Path | None:
    """The pinned cua-driver where the user or reality-check installed it, or None; never downloads."""
    for candidate in _candidates(target):
        if candidate.is_file() and installed_version(target, candidate) == VERSION:
            return candidate
    return None


def installed_version(target: Target, executable: Path) -> str | None:
    """The version `executable --version` reports, or None when it does not run or says something else."""
    try:
        completed = run_driver(target, executable, ["--version"], VERSION_TIMEOUT_SECONDS)
    except (OSError, subprocess.SubprocessError):
        return None
    match = VERSION_PATTERN.match(completed.stdout.strip())
    return match.group(1) if completed.returncode == 0 and match else None


def own_directory(target: Target) -> Path:
    """Where reality-check unpacks the pinned cua-driver; on macOS, the app's own place."""
    if target.kind == "macos":
        return MACOS_APP
    if target.kind == "wsl":
        local, _ = windows_folders()
        return local / DISTRIBUTION / "cua-driver" / VERSION
    return platformdirs.user_data_path(DISTRIBUTION, appauthor=False, roaming=False) / "cua-driver" / VERSION


def own_executable(target: Target) -> Path:
    if target.kind == "macos":
        return MACOS_APP / MACOS_EXECUTABLE
    return own_directory(target) / target.executable_name


def _candidates(target: Target) -> Iterator[Path]:
    """Where cua-driver may be: on PATH, where the vendor's installer puts it, then reality-check's own copy."""
    on_path = shutil.which(target.executable_name)
    if on_path:
        yield Path(on_path)
    match target.kind:
        case "windows" | "wsl":
            if target.kind == "windows":
                local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
                profile = Path.home()
            else:
                local, profile = windows_folders()
            yield local / "Programs" / "Cua" / "cua-driver" / "bin" / target.executable_name
            yield profile / ".cua-driver" / "packages" / "current" / target.executable_name
        case "linux":
            yield Path.home() / ".local" / "bin" / target.executable_name
            yield Path.home() / ".cua-driver" / "packages" / "current" / target.executable_name
        case "macos":
            pass
    yield own_executable(target)


def _download(target: Target) -> Path:
    """Download the pinned asset, check it against its pinned hash, and move it into place whole."""
    directory = own_directory(target)
    if directory.exists():
        raise RealityCheckError(
            code="computer-use-install-broken",
            message=f"{directory} is there, but does not hold a working cua-driver {VERSION}.",
            remedy=f"Move {directory} aside, then run `{INSTALL_COMMAND}` again.",
        )

    def build(staging: Path) -> Path:
        asset = target.asset(VERSION)
        archive = staging / asset
        fetch(INSTALLING, RELEASE_URL.format(version=VERSION, asset=asset), archive, "sha256", SHA256[asset])
        unpacked = staging / "unpacked"
        _extract(archive, unpacked)
        return _unpacked_root(target, unpacked)

    build_in_place(INSTALLING, directory, build, f"cua-driver {VERSION}")
    executable = own_executable(target)
    if installed_version(target, executable) != VERSION:
        raise RealityCheckError(
            code="computer-use-install-broken",
            message=f"cua-driver {VERSION} was unpacked into {directory}, but {executable} does not run.",
            remedy=f"Run `{executable} --version` to see why.",
        )
    return executable


def _extract(archive: Path, into: Path) -> None:
    if archive.name.endswith(".zip"):
        with zipfile.ZipFile(archive) as unzip:
            unzip.extractall(into)
        return
    with tarfile.open(archive) as untar:
        untar.extractall(into, filter="data")


def _unpacked_root(target: Target, unpacked: Path) -> Path:
    """What moves into place: the flat binary archive's contents, or the app from the macOS archive."""
    if target.kind != "macos":
        return unpacked
    app = next(unpacked.glob(f"*/{MACOS_APP.name}"), None)
    if app is None:
        raise OSError(f"the archive has no {MACOS_APP.name}")
    return app


def _remaining_step(target: Target, executable: Path) -> str | None:
    if target.kind != "macos":
        return None
    # Only a running daemon can tell whether the grants are there, so the step is always named.
    return (
        f"Once, unless already done: run `{executable} permissions grant` and allow Accessibility and Screen "
        "Recording for CuaDriver."
    )
