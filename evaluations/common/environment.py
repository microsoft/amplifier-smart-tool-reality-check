"""One evaluation environment: a universe from a task's profile, driven from the host."""

from collections.abc import Iterator
from contextlib import contextmanager
import json
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import tarfile
import tempfile
from typing import Any

from common import collect_in_environment
from common.context import EvaluationError, RunContext
from digital_twin_universe import lib as dtu
from digital_twin_universe.schemas import ExecResult

HOME = "/home/user"
PROJECT = f"{HOME}/project"
# The evaluation's own files in the twin, made only once the capability has finished.
WORK = str(collect_in_environment.WORK)
PROFILE_PREFIX = "reality-check-evaluation-"
UNIVERSE_PREFIX = f"dtu-{PROFILE_PREFIX}"
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
    def start(cls, profile: Path, logs: Path) -> "Environment":
        """Launch a new environment from `profile`, with Compose's progress kept in `logs/launch.log`.

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
                    str(profile),
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
        self._log(name, command, result)
        return result

    def run_checked(self, name: str, command: str, timeout_seconds: int = 600, user: str | None = None) -> ExecResult:
        """`run`, failing when the command exits non-zero."""
        return self._checked(name, self.run(name, command, timeout_seconds=timeout_seconds, user=user))

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

    def exec_service(
        self, service: str, name: str, command: str, user: str | None = None, timeout_seconds: int = 600
    ) -> ExecResult:
        """Run a shell command in another service of the universe, logged as `logs/<name>.log`."""
        arguments = ["docker", "exec", *(["--user", user] if user else []), self.container(service), "sh", "-lc"]
        try:
            completed = subprocess.run(
                [*arguments, command], capture_output=True, text=True, timeout=timeout_seconds, check=False
            )
            result = ExecResult(exit_code=completed.returncode, stdout=completed.stdout, stderr=completed.stderr)
        except subprocess.TimeoutExpired as error:
            result = ExecResult(exit_code=124, stdout=_text(error.stdout), stderr=_text(error.stderr))
        self._log(name, f"[{service}] {command}", result)
        return result

    def exec_service_checked(
        self, service: str, name: str, command: str, user: str | None = None, timeout_seconds: int = 600
    ) -> ExecResult:
        """`exec_service`, failing when the command exits non-zero."""
        return self._checked(name, self.exec_service(service, name, command, user, timeout_seconds))

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

    def push_json(self, value: dict[str, Any], destination: str) -> None:
        """Write `value` as JSON to `destination` in the twin."""
        with tempfile.TemporaryDirectory() as scratch:
            path = Path(scratch) / Path(destination).name
            path.write_text(json.dumps(value, indent=2), encoding="utf-8")
            self.push(path, destination)

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

    def push_service(self, service: str, source: Path, destination: str) -> None:
        """Copy a host file or directory to `destination` in another service, with `docker cp` semantics."""
        _docker_cp(str(source), f"{self.container(service)}:{destination}")

    def pull_service(self, service: str, source: str, destination: Path) -> None:
        """Copy a file or directory in another service to `destination` on the host, with `docker cp` semantics."""
        destination.parent.mkdir(parents=True, exist_ok=True)
        _docker_cp(f"{self.container(service)}:{source}", str(destination))

    def container(self, service: str) -> str:
        """The container that runs `service` in this universe."""
        return f"{self.id}-{service}-1"

    def container_logs(self, destination: Path) -> None:
        """The twin's own container output, which is the nested Docker daemon's log."""
        with destination.open("w", encoding="utf-8") as log:
            subprocess.run(["docker", "logs", self.container("twin")], stdout=log, stderr=subprocess.STDOUT)

    def destroy(self) -> None:
        """Destroy the universe and the image tags its launch made; the shared layers stay cached."""
        images = subprocess.run(
            ["docker", "image", "ls", "--format", "{{.Repository}}", "--filter", f"reference={self.id}-*"],
            capture_output=True,
            text=True,
        ).stdout.split()
        dtu.destroy(self.id)
        for image in images:
            _remove_image(image)

    def _log(self, name: str, command: str, result: ExecResult) -> None:
        with (self._logs / f"{name}.log").open("w", encoding="utf-8") as log:
            log.write(f"$ {command}\nexit code: {result.exit_code}\n\n--- stdout ---\n{result.stdout}\n")
            log.write(f"--- stderr ---\n{result.stderr}\n")

    def _checked(self, name: str, result: ExecResult) -> ExecResult:
        if result.exit_code != 0:
            raise EvaluationError(f"{name} exited {result.exit_code} in {self.id}; see {self._logs / f'{name}.log'}.")
        return result


@contextmanager
def launch(context: RunContext, profile: Path) -> Iterator[Environment]:
    """A new environment from `profile`, destroyed on exit unless the run keeps it."""
    with context.step("launch"):
        environment = Environment.start(profile, context.logs)
    context.live.add(environment)
    context.record.universe_id = environment.id
    context.save()
    try:
        yield environment
    finally:
        if not context.spec.keep:
            try:
                environment.destroy()
            except Exception as error:
                context.record.error = (context.record.error or "") + f" Destroying {environment.id} failed: {error}"
            context.live.remove(environment)


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


def _links_kept_inside(member: tarfile.TarInfo, path: str) -> tarfile.TarInfo | None:
    """The `data` filter, except that a link pointing outside the archive, such as a venv's python, is skipped."""
    try:
        return tarfile.data_filter(member, path)
    except (tarfile.AbsoluteLinkError, tarfile.LinkOutsideDestinationError):
        return None


def _docker_cp(source: str, destination: str) -> None:
    copied = subprocess.run(["docker", "cp", source, destination], capture_output=True, text=True)
    if copied.returncode != 0:
        raise EvaluationError(f"docker cp {source} {destination} failed: {copied.stderr.strip()}")


def _remove_image(image: str) -> None:
    subprocess.run(["docker", "image", "rm", image], capture_output=True)


def _text(output: bytes | str | None) -> str:
    if isinstance(output, bytes):
        return output.decode(errors="replace")
    return output or ""
