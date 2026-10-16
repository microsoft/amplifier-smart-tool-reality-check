"""Evaluation tasks: what the capability is asked, what goes in the environment, and how the result is graded."""

from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints, ValidationError
import yaml

TASKS_DIRECTORY = Path(__file__).resolve().parents[1] / "tasks"
TASK_FILE = "task.yaml"
EXPECTED_FILE = "expected.md"
CRITERION_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"

Capability = Literal["check-software"]
# Criterion names become property names in the judge's submit schema.
CriterionName = Annotated[str, StringConstraints(pattern=CRITERION_PATTERN)]


class EvaluationError(Exception):
    """A failure of the evaluation harness itself, as opposed to a capability that did badly."""


class Criterion(BaseModel):
    """One rubric criterion, scored 0 to 100 by the judge."""

    weight: float = Field(gt=0)
    description: str


class Image(BaseModel):
    """A Docker image built on the host and loaded into the environment, so its build never enters it."""

    build: str = Field(description="The build context, a directory in the task directory")
    tag: str = Field(description="The image's name in the environment, which the task's profiles refer to")


class Task(BaseModel):
    """A task.yaml, with the directory it was read from."""

    name: str
    directory: Path
    capability: Capability
    description: str = Field(description="What the task is and how it is set up, for a person reading its results")
    request: str
    target: str | None = None
    files: dict[str, str] = Field(
        default_factory=dict, description="A path in the task directory, to a path relative to the user's project"
    )
    images: list[Image] = Field(default_factory=list)
    timeout_seconds: int = Field(gt=0)
    rubric: dict[CriterionName, Criterion] = Field(min_length=1)

    @property
    def expected(self) -> Path:
        return self.directory / EXPECTED_FILE


def task_names() -> list[str]:
    """Every task under the tasks directory, by name."""
    return sorted(path.parent.name for path in TASKS_DIRECTORY.glob(f"*/{TASK_FILE}"))


def load_task(name: str) -> Task:
    """The named task, validated, with every file it names checked to exist."""
    directory = TASKS_DIRECTORY / name
    path = directory / TASK_FILE
    if not path.is_file():
        raise EvaluationError(f"No task {name!r}; the tasks are: {', '.join(task_names())}.")
    with path.open(encoding="utf-8") as file:
        fields = yaml.safe_load(file)
    try:
        task = Task.model_validate({**fields, "name": name, "directory": directory})
    except ValidationError as error:
        raise EvaluationError(f"{path} is not a valid task:\n{error}") from error
    named = [*task.files, *(image.build for image in task.images)]
    missing = [source for source in named if not (directory / source).exists()]
    if not task.expected.is_file():
        missing.append(EXPECTED_FILE)
    if missing:
        raise EvaluationError(f"{path} names files that do not exist in {directory}: {', '.join(missing)}.")
    return task
