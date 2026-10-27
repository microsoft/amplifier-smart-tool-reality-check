"""Showing a folder to the person, in their platform's file manager."""

import os
from pathlib import Path
import shutil
import subprocess
import sys

from reality_check.schemas import RealityCheckError


def can_open_folders() -> bool:
    """Whether this machine has a file manager to show a folder in."""
    return sys.platform in {"win32", "darwin"} or _wsl_explorer() is not None or shutil.which("xdg-open") is not None


def open_folder(path: Path) -> None:
    """Open `path` in Explorer, Finder, or whatever `xdg-open` picks; under WSL, in Windows Explorer."""
    try:
        if sys.platform == "win32":
            os.startfile(path)
            return
        explorer = _wsl_explorer()
        if explorer is not None:
            windows_path = subprocess.run(
                ["wslpath", "-w", str(path)], capture_output=True, text=True, check=True
            ).stdout.strip()
            command = [explorer, windows_path]
        elif sys.platform == "darwin":
            command = ["open", str(path)]
        else:
            opener = shutil.which("xdg-open")
            if opener is None:
                raise OSError("no file manager found, xdg-open is not installed")
            command = [opener, str(path)]
        subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise RealityCheckError(
            code="cannot-open-folder",
            message=f"Could not open {path} in a file manager: {error}.",
            remedy="Open it from a terminal or file manager instead.",
        ) from None


def _wsl_explorer() -> str | None:
    # WSL's Linux side rarely has a file manager, but it can start Windows Explorer on the same files.
    if sys.platform != "linux" or "microsoft" not in os.uname().release.lower():
        return None
    if shutil.which("wslpath") is None:
        return None
    return shutil.which("explorer.exe")
