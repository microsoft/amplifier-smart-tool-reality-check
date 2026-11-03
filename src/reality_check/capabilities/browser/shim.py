"""The command a check's agent runs agent-browser through, with its skills and this machine's certificates."""

from pathlib import Path
import shlex

from reality_check.capabilities.browser.install import variables
from reality_check.capabilities.browser.target import Target
from reality_check.capabilities.computer_use.shim import write_named_by_content

CA_BUNDLES = ("/etc/ssl/certs/ca-certificates.crt", "/etc/pki/tls/certs/ca-bundle.crt")


def write_shim(target: Target, executable: Path, cache_directory: Path) -> Path:
    """Write the shim for `executable` under `cache_directory`, named by its content so checks share it."""
    name, text = _shim(target, executable)
    return write_named_by_content(cache_directory, name, text)


def _shim(target: Target, executable: Path) -> tuple[str, str]:
    environment = variables()
    if target.windows:
        lines = ["@echo off", *(f"set {name}={value}" for name, value in environment.items())]
        lines += [f'"{executable}" %*', "exit /b %errorlevel%"]
        return "agent-browser.cmd", "\r\n".join(lines) + "\r\n"
    exports = " ".join(f"{name}={shlex.quote(value)}" for name, value in environment.items())
    lines = ["#!/bin/sh", f"export {exports}"]
    if target.linux:
        lines += _ca_bundle_lines()
    lines.append(f'exec {shlex.quote(str(executable))} "$@"')
    return "agent-browser", "\n".join(lines) + "\n"


def _ca_bundle_lines() -> list[str]:
    """Shell that hands this machine's certificate authorities to Chromium, decided on each run.

    Chromium on Linux trusts only its own NSS store, not the system's, and agent-browser imports a PEM bundle into a
    temporary one per launch with certutil. Without certutil, naming a bundle makes every launch fail. Deciding on each
    run rather than when the shim is written picks up a certutil the browser install brings during the check.
    """
    candidates = " ".join(['"${SSL_CERT_FILE:-}"', *(shlex.quote(bundle) for bundle in CA_BUNDLES)])
    return [
        'if [ -z "${AGENT_BROWSER_CA_CERT:-}" ] && command -v certutil >/dev/null 2>&1; then',
        f"  for bundle in {candidates}; do",
        '    if [ -n "$bundle" ] && [ -f "$bundle" ]; then',
        '      export AGENT_BROWSER_CA_CERT="$bundle"',
        "      break",
        "    fi",
        "  done",
        "fi",
    ]
