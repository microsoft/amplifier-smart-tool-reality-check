"""One evaluation environment: a universe from `evaluations/environment`, driven from the host."""

import json
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import tarfile
import tempfile

from digital_twin_universe import lib as dtu
from digital_twin_universe.schemas import ExecResult
from harness import collect
from harness.tasks import EvaluationError

PROFILE = Path(__file__).resolve().parents[1] / "environment"
HOME = "/home/user"
PROJECT = f"{HOME}/project"
# The harness's own files in the twin, made only once the capability has finished.
WORK = str(collect.WORK)
UNIVERSE_PREFIX = "dtu-reality-check-evaluation-"
REPOSITORY_URL = "https://github.com/microsoft/amplifier-smart-tool-reality-check"
LAUNCH_TIMEOUT_SECONDS = 1200
EXPORT_MAX_BYTES = 8 * 1024**3
EXPORT_TIMEOUT_SECONDS = 1800
CAPTURE_MAX_BYTES = 16 * 1024**2


class Environment:
    """A launched evaluation environment; every command it runs is logged under `logs`."""

    def __init__(self, universe_id: str, logs: Path) -> None:
        self.id = universe_id
        self._logs = logs

    @classmethod
    def launch(cls, logs: Path) -> "Environment":
        """Launch a new environment, with Compose's progress kept in `logs/launch.log`.

        The launch runs as its own process, so runs launching at the same time keep their output apart.
        """
        logs.mkdir(parents=True, exist_ok=True)
        with (logs / "launch.log").open("w", encoding="utf-8") as log:
            launched = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "digital_twin_universe.cli",
                    "launch",
                    "--profile",
                    str(PROFILE),
                    "--timeout-seconds",
                    str(LAUNCH_TIMEOUT_SECONDS),
                ],
                stdout=subprocess.PIPE,
                stderr=log,
                text=True,
            )
        if launched.returncode != 0:
            raise EvaluationError(f"The evaluation environment did not launch; see {logs / 'launch.log'}.")
        return cls(json.loads(launched.stdout)["id"], logs)

    def run(self, name: str, command: str, timeout_seconds: int = 600, user: str | None = None) -> ExecResult:
        """Run a command in the twin from the user's project, logged as `logs/<name>.log`."""
        result = dtu.execute(self.id, command, user=user, workdir=PROJECT, timeout_seconds=timeout_seconds)
        with (self._logs / f"{name}.log").open("w", encoding="utf-8") as log:
            log.write(f"$ {command}\nexit code: {result.exit_code}\n\n--- stdout ---\n{result.stdout}\n")
            log.write(f"--- stderr ---\n{result.stderr}\n")
        return result

    def run_checked(self, name: str, command: str, timeout_seconds: int = 600, user: str | None = None) -> ExecResult:
        """`run`, failing when the command exits non-zero."""
        result = self.run(name, command, timeout_seconds=timeout_seconds, user=user)
        if result.exit_code != 0:
            raise EvaluationError(f"{name} exited {result.exit_code} in {self.id}; see {self._logs / f'{name}.log'}.")
        return result

    def capture(self, name: str, command: str, timeout_seconds: int) -> ExecResult:
        """`run` for a command whose output the caller keeps, so only its exit code and stderr are logged."""
        result = dtu.execute(
            self.id,
            command,
            workdir=PROJECT,
            timeout_seconds=timeout_seconds,
            max_output_bytes=CAPTURE_MAX_BYTES,
        )
        with (self._logs / f"{name}.log").open("w", encoding="utf-8") as log:
            log.write(f"$ {command}\nexit code: {result.exit_code}\nstdout truncated: {result.stdout_truncated}\n\n")
            log.write(f"--- stderr ---\n{result.stderr}\n")
        return result

    def load_images(self, archive: Path) -> None:
        """Load images saved on the host into the nested daemon, leaving no archive or build cache behind."""
        destination = f"/var/tmp/{secrets.token_hex(8)}.tar"
        self.push(archive, destination)
        self.run_checked(
            "load-images",
            f"docker load --input {destination} && rm -f {destination} && docker builder prune --all --force",
        )

    def push(self, source: Path, destination: str) -> None:
        """Copy a host file or directory to `destination` in the twin, owned by the twin's user."""
        dtu.push_files(self.id, source, destination)

    def pull(self, source: str, destination: Path) -> None:
        """Copy a file or directory in the twin to `destination` on the host, which must not exist yet."""
        with tempfile.TemporaryDirectory() as scratch:
            archive = dtu.export_files(
                self.id,
                source,
                Path(scratch) / "export.tar",
                max_bytes=EXPORT_MAX_BYTES,
                timeout_seconds=EXPORT_TIMEOUT_SECONDS,
            )
            extracted = Path(scratch) / "extracted"
            with tarfile.open(archive.destination) as tar:
                tar.extractall(extracted, filter=_links_kept_inside)
            [root] = list(extracted.iterdir())
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(root, destination)

    def container_logs(self, destination: Path) -> None:
        """The twin's own container output, which is the nested Docker daemon's log."""
        twin = f"{self.id}-twin-1"
        with destination.open("w", encoding="utf-8") as log:
            subprocess.run(["docker", "logs", twin], stdout=log, stderr=subprocess.STDOUT)

    def destroy(self) -> None:
        """Destroy the universe and the twin's image tag that its launch made; the shared layers stay cached."""
        dtu.destroy(self.id)
        _remove_image(f"{self.id}-twin")


def _links_kept_inside(member: tarfile.TarInfo, path: str) -> tarfile.TarInfo | None:
    """The `data` filter, except that a link pointing outside the archive, such as a venv's python, is skipped."""
    try:
        return tarfile.data_filter(member, path)
    except (tarfile.AbsoluteLinkError, tarfile.LinkOutsideDestinationError):
        return None


def destroy_leftovers() -> list[str]:
    """Destroy every evaluation environment on this machine, including ones a killed batch left."""
    destroyed = []
    # By id, since a universe id is the profile's name with a suffix, and listing measures every universe.
    for universe in dtu.recorded_ids():
        if universe.startswith(UNIVERSE_PREFIX):
            dtu.destroy(universe)
            destroyed.append(universe)
    images = subprocess.run(
        ["docker", "image", "ls", "--format", "{{.Repository}}"], capture_output=True, text=True
    ).stdout.split()
    for image in images:
        if image.startswith(UNIVERSE_PREFIX):
            _remove_image(image)
    return destroyed


def _remove_image(image: str) -> None:
    subprocess.run(["docker", "image", "rm", image], capture_output=True)
