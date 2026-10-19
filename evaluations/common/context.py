"""One run's spec, its run.json record, and the context a task's `run` drives it through."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
import threading
import time
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

from reality_check.schemas import AgentProvider, ReasoningEffort

RunStatus = Literal["running", "completed", "failed"]


class EvaluationError(Exception):
    """A failure of the evaluation itself, as opposed to a capability that did badly."""


class RunSpec(BaseModel):
    """What one run evaluates, and with which judge."""

    task: str
    agent_provider: AgentProvider
    model: str
    reasoning_effort: ReasoningEffort
    repeat: int
    judge_agent_provider: AgentProvider
    judge_model: str
    judge_reasoning_effort: ReasoningEffort
    judge_timeout_seconds: int
    keep: bool = False


class RunRecord(BaseModel):
    """A run's run.json: what ran, how it ended, how long each step took, its usage, and its score."""

    run_id: str
    spec: RunSpec
    capability: str | None = None
    status: RunStatus = "running"
    step: str = ""
    error: str | None = None
    universe_id: str | None = None
    versions: dict[str, Any] = Field(default_factory=dict)
    outcome: dict[str, Any] = Field(default_factory=dict, description="How the capability ended")
    task_outcome: dict[str, Any] = Field(default_factory=dict, description="Facts the task itself recorded")
    capability_seconds: float | None = Field(
        default=None, description="Wall clock of the capability alone, from its first event to its last"
    )
    timings: dict[str, float] = Field(default_factory=dict, description="Wall clock of each step, in seconds")
    usage: dict[str, Any] = Field(default_factory=dict)
    score: float | None = Field(default=None, ge=0, le=100)
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    ended_at: datetime | None = None


class Criterion(BaseModel):
    """One rubric criterion, scored 0 to 100 by the judge."""

    weight: float = Field(gt=0)
    description: str


class Destroyable(Protocol):
    id: str

    def destroy(self) -> None: ...


class Live:
    """The environments running now, so an interrupted batch can destroy them."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._environments: dict[str, Destroyable] = {}

    def add(self, environment: Destroyable) -> None:
        with self._lock:
            self._environments[environment.id] = environment

    def remove(self, environment: Destroyable) -> None:
        with self._lock:
            self._environments.pop(environment.id, None)

    def destroy_all(self) -> list[str]:
        with self._lock:
            environments = list(self._environments.values())
            self._environments.clear()
        for environment in environments:
            environment.destroy()
        return [environment.id for environment in environments]


class RunContext:
    """One run's spec, directory, and record, kept in `run.json` after every step."""

    def __init__(
        self, spec: RunSpec, directory: Path, live: Live, report: Callable[[str], None] = lambda line: None
    ) -> None:
        self.spec = spec
        self.directory = directory
        self.record = RunRecord(run_id=directory.name, spec=spec)
        self.live = live
        self.logs = directory / "logs" / "setup"
        self._report = report

    @contextmanager
    def step(self, name: str) -> Iterator[None]:
        """Mark `name` as the current step, and time it into `record.timings`."""
        self.record.step = name
        self.save()
        self.report(name)
        started = time.monotonic()
        try:
            yield
        finally:
            self.record.timings[name] = round(time.monotonic() - started, 1)
            self.save()

    def save(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        (self.directory / "run.json").write_text(self.record.model_dump_json(indent=2), encoding="utf-8")

    def report(self, line: str) -> None:
        """A progress line, prefixed with the run's id."""
        self._report(f"{self.record.run_id}: {line}")
