"""Download pinned artifacts, check them against their pinned digests, and move what they make into place whole."""

from collections.abc import Callable
import contextlib
import hashlib
import os
from pathlib import Path
import secrets
import shutil
import ssl
import sys
from typing import NamedTuple
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import urlopen

import certifi

from reality_check.schemas import Component, RealityCheckError

DOWNLOAD_TIMEOUT_SECONDS = 60
CHUNK_BYTES = 1 << 20
DIGEST_NAMES = {"sha256": "SHA-256", "sha512": "SHA-512"}


class Installing(NamedTuple):
    """The component an install is for, which names its failures, and the command that runs it again."""

    component: Component
    command: str


def fetch(installing: Installing, url: str, path: Path, algorithm: str, expected: str) -> None:
    """Download `url` to `path`, hashing it as it streams; raises when it does not match its pinned hex digest."""
    digest = hashlib.new(algorithm)
    try:
        with (
            urlopen(url, timeout=DOWNLOAD_TIMEOUT_SECONDS, context=tls_context()) as response,
            path.open("wb") as file,
        ):
            while chunk := response.read(CHUNK_BYTES):
                digest.update(chunk)
                file.write(chunk)
    except (URLError, TimeoutError) as error:
        raise RealityCheckError(
            code=f"{installing.component}-download-failed",
            message=f"Could not download {url}: {error}",
            remedy=f"Check that this machine reaches {urlparse(url).hostname}, then run `{installing.command}` again.",
        ) from error
    if digest.hexdigest() != expected:
        raise RealityCheckError(
            code=f"{installing.component}-download-corrupt",
            message=f"{url} does not match its pinned {DIGEST_NAMES[algorithm]}: got {digest.hexdigest()}, "
            f"expected {expected}.",
            remedy=f"Run `{installing.command}` again; if it fails the same way, do not use this download.",
        )


def tls_context() -> ssl.SSLContext:
    """Trust the system's store where it is the one to trust, else certifi's, which has no proxy's authority."""
    # Windows' store, and a store named in SSL_CERT_FILE or SSL_CERT_DIR, hold a TLS-inspecting proxy's authority.
    if sys.platform == "win32" or os.environ.get("SSL_CERT_FILE") or os.environ.get("SSL_CERT_DIR"):
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=certifi.where())


def build_in_place(installing: Installing, directory: Path, build: Callable[[Path], Path], what: str) -> None:
    """Make `directory` from what `build` returns, built in a folder beside it, so it appears whole or not at all.

    `build` gets that empty folder and returns the folder inside it that becomes `directory`; `what` names the
    release in the failure when it cannot.
    """
    # Made here, so a failed install removes them again.
    made = [folder for folder in (directory.parent, *directory.parent.parents) if not folder.exists()]
    try:
        directory.parent.mkdir(parents=True, exist_ok=True)
        # Built beside its final place, so moving it there is one rename and no one ever sees half of it.
        staging = directory.parent / f".{directory.name}.{secrets.token_hex(3)}.tmp"
        staging.mkdir()
    except OSError as error:
        raise RealityCheckError(
            code=f"{installing.component}-install-failed",
            message=f"Could not write to {directory.parent}: {error}",
            remedy=f"Make {directory.parent} writable, then run `{installing.command}` again.",
        ) from error
    try:
        try:
            built = build(staging)
            try:
                built.rename(directory)
            except OSError:
                # Another install finished first; its copy is the same pinned release.
                if not directory.exists():
                    raise
        except OSError as error:
            raise RealityCheckError(
                code=f"{installing.component}-install-failed",
                message=f"Could not unpack {what} into {directory}: {error}",
                remedy=f"Run `{installing.command}` again; if it fails the same way, check the free space and "
                f"permissions of {directory.parent}.",
            ) from error
        finally:
            shutil.rmtree(staging, ignore_errors=True)
    except RealityCheckError:
        _remove_empty(made)
        raise


def _remove_empty(folders: list[Path]) -> None:
    for folder in folders:
        with contextlib.suppress(OSError):
            folder.rmdir()
