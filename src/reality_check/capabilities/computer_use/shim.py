"""The command a check's agent runs cua-driver through, with telemetry off however the agent's shell is set up."""

import hashlib
from pathlib import Path
import secrets
import shlex

from reality_check.capabilities.computer_use.target import TELEMETRY_OFF, Target


def write_shim(target: Target, executable: Path, cache_directory: Path) -> Path:
    """Write the shim for `executable` under `cache_directory`, named by its content so checks share it."""
    name, text = _shim(target, executable)
    path = cache_directory / hashlib.sha256(text.encode("utf-8")).hexdigest()[:16] / name
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        partial = path.with_name(f"{name}.{secrets.token_hex(3)}.tmp")
        partial.write_text(text, encoding="utf-8", newline="")
        partial.chmod(0o755)
        try:
            partial.replace(path)
        except PermissionError:
            # Windows refuses to replace a file another check has open; that file is this same shim.
            partial.unlink()
    return path


def _shim(target: Target, executable: Path) -> tuple[str, str]:
    if target.kind == "windows":
        lines = ["@echo off", *(f"set {name}={value}" for name, value in TELEMETRY_OFF.items())]
        lines += [f'"{executable}" %*', "exit /b %errorlevel%"]
        return "cua-driver.cmd", "\r\n".join(lines) + "\r\n"
    exports = " ".join(f"{name}={value}" for name, value in TELEMETRY_OFF.items())
    lines = ["#!/bin/sh", f"export {exports}"]
    if target.kind == "wsl":
        names = ":".join(TELEMETRY_OFF)
        lines.append(f'export WSLENV="${{WSLENV:+$WSLENV:}}{names}"')
    lines.append(f'exec {shlex.quote(str(executable))} "$@"')
    return "cua-driver", "\n".join(lines) + "\n"
