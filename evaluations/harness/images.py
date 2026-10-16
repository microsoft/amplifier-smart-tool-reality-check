"""Task images, built on the host so neither their build inputs nor their build cache enter an environment."""

from pathlib import Path
import subprocess

from harness.tasks import EvaluationError, Task


def build(task: Task, destination: Path, log: Path) -> Path | None:
    """Build the task's images with the host's Docker and save them to one archive in `destination`.

    The host's build cache makes every batch after the first fast.
    """
    if not task.images:
        return None
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("w", encoding="utf-8") as output:
        for image in task.images:
            built = subprocess.run(
                ["docker", "build", "--tag", image.tag, str(task.directory / image.build)],
                stdout=output,
                stderr=subprocess.STDOUT,
            )
            if built.returncode != 0:
                raise EvaluationError(f"Building {image.tag} for {task.name} failed; see {log}.")
    archive = destination / f"{task.name}.tar"
    saved = subprocess.run(
        ["docker", "save", "--output", str(archive), *(image.tag for image in task.images)],
        capture_output=True,
        text=True,
    )
    if saved.returncode != 0:
        raise EvaluationError(f"Saving the images of {task.name} failed: {saved.stderr.strip()}")
    return archive
