"""Evaluate reality-check's capabilities on tasks, each run in its own evaluation environment, all tasks at once.

uv run evaluations/run.py list
uv run evaluations/run.py run --task excalidraw-01 --model gpt-6.1-sol --repeat 3
uv run evaluations/run.py cleanup
"""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
import importlib.util
import json
from pathlib import Path
import re
import secrets
import threading
import traceback
from types import ModuleType
from typing import Annotated

from common import providers
from common.context import EvaluationError, Live, RunContext, RunRecord, RunSpec
from common.environment import destroy_leftovers
import typer

from reality_check.schemas import DEFAULT_INTELLIGENCE_MODELS, AgentProvider, ReasoningEffort

EVALUATIONS = Path(__file__).resolve().parent
TASKS_DIRECTORY = EVALUATIONS / "tasks"
RUNS_DIRECTORY = EVALUATIONS / "runs"

TaskRun = Callable[[RunContext], None]

app = typer.Typer(add_completion=False, no_args_is_help=True)
_print_lock = threading.Lock()


def _print(line: str) -> None:
    with _print_lock:
        typer.echo(f"{datetime.now().strftime('%H:%M:%S')} {line}", err=True)


def task_names() -> list[str]:
    """Every task under the tasks directory, by name."""
    return sorted(path.parent.name for path in TASKS_DIRECTORY.glob("*/task.py"))


def load_task(name: str) -> ModuleType:
    """The named task's module, checked to have `DESCRIPTION` and `run`."""
    path = TASKS_DIRECTORY / name / "task.py"
    if not path.is_file():
        raise EvaluationError(f"No task {name!r}; the tasks are: {', '.join(task_names())}.")
    spec = importlib.util.spec_from_file_location(f"tasks.{name}", path)
    if spec is None or spec.loader is None:
        raise EvaluationError(f"{path} cannot be loaded as a module.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not isinstance(getattr(module, "DESCRIPTION", None), str) or not callable(getattr(module, "run", None)):
        raise EvaluationError(f"{path} must define DESCRIPTION, a string, and run(context).")
    return module


@app.command("list")
def list_tasks() -> None:
    """List every task with its description."""
    for name in task_names():
        typer.echo(f"{name}\n  {load_task(name).DESCRIPTION}\n")


@app.command()
def run(
    task: Annotated[
        list[str] | None, typer.Option("--task", help="A task to run; repeatable. Every task when omitted.")
    ] = None,
    agent_provider: Annotated[AgentProvider, typer.Option("--agent-provider")] = "copilot",
    model: Annotated[
        list[str] | None,
        typer.Option("--model", help="A model to run; repeatable. The provider's default when omitted."),
    ] = None,
    reasoning_effort: Annotated[ReasoningEffort, typer.Option("--reasoning-effort")] = "high",
    repeat: Annotated[int, typer.Option("--repeat", min=1, help="Runs of each task and model.")] = 1,
    parallel: Annotated[int, typer.Option("--parallel", min=1, help="Runs of one task at the same time.")] = 1,
    judge_agent_provider: Annotated[AgentProvider, typer.Option("--judge-agent-provider")] = "copilot",
    judge_model: Annotated[
        str | None, typer.Option("--judge-model", help="The judge provider's default when omitted.")
    ] = None,
    judge_reasoning_effort: Annotated[ReasoningEffort, typer.Option("--judge-reasoning-effort")] = "high",
    judge_timeout_seconds: Annotated[int, typer.Option("--judge-timeout-seconds", min=1)] = 1800,
    keep: Annotated[bool, typer.Option("--keep", help="Leave each evaluation environment running.")] = False,
) -> None:
    """Run every task x model x repeat, and write a batch directory under evaluations/runs.

    Tasks run at the same time as each other; the runs of one task run `--parallel` at a time.
    """
    try:
        tasks = {name: load_task(name).run for name in (task or task_names())}
        for name in dict.fromkeys([agent_provider, judge_agent_provider]):
            providers.export_credentials(name)
    except EvaluationError as error:
        raise typer.BadParameter(str(error)) from error
    specs = [
        RunSpec(
            task=name,
            agent_provider=agent_provider,
            model=each_model,
            reasoning_effort=reasoning_effort,
            repeat=index,
            judge_agent_provider=judge_agent_provider,
            judge_model=judge_model or DEFAULT_INTELLIGENCE_MODELS[judge_agent_provider],
            judge_reasoning_effort=judge_reasoning_effort,
            judge_timeout_seconds=judge_timeout_seconds,
            keep=keep,
        )
        for name in tasks
        for each_model in (model or [DEFAULT_INTELLIGENCE_MODELS[agent_provider]])
        for index in range(1, repeat + 1)
    ]
    batch = RUNS_DIRECTORY / f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(3)}"
    batch.mkdir(parents=True)
    live = Live()
    _print(f"batch {batch} with {len(specs)} runs of {len(tasks)} tasks, {parallel} at a time per task")
    try:
        records = run_batch(batch, tasks, specs, parallel, live)
    except KeyboardInterrupt:
        _print("interrupted; destroying the running evaluation environments")
        for universe in live.destroy_all():
            _print(f"destroyed {universe}")
        raise typer.Exit(130) from None
    for record in records.values():
        typer.echo(
            json.dumps(
                {
                    "run_id": record.run_id,
                    "status": record.status,
                    "score": record.score,
                    "capability_seconds": record.capability_seconds,
                    "aiu": record.usage.get("capability", {}).get("aiu"),
                    "usd": record.usage.get("capability", {}).get("usd"),
                    "error": record.error,
                }
            )
        )


@app.command()
def cleanup() -> None:
    """Destroy every evaluation environment on this machine, including ones a killed batch left running."""
    for universe in destroy_leftovers():
        typer.echo(f"destroyed {universe}")


def run_batch(
    batch: Path, tasks: dict[str, TaskRun], specs: list[RunSpec], parallel: int, live: Live
) -> dict[str, RunRecord]:
    """Run every spec: one thread per task, and up to `parallel` runs of a task at the same time."""
    records: dict[str, RunRecord] = {}
    lock = threading.Lock()
    stopped = threading.Event()

    def execute(spec: RunSpec) -> None:
        if stopped.is_set():
            return
        directory = batch / _slug(f"{spec.task}-{spec.agent_provider}-{spec.model}-{spec.repeat}")
        record = _execute(tasks[spec.task], RunContext(spec, directory, live, _print))
        with lock:
            records[record.run_id] = record
            _write_batch(batch, specs, records)

    def run_task(name: str) -> None:
        with ThreadPoolExecutor(max_workers=parallel) as runs:
            for future in [runs.submit(execute, spec) for spec in specs if spec.task == name]:
                future.result()

    executor = ThreadPoolExecutor(max_workers=max(len(tasks), 1))
    try:
        for future in [executor.submit(run_task, name) for name in tasks]:
            future.result()
    except KeyboardInterrupt:
        # Runs not started yet never start; the caller destroys the environments of the ones running.
        stopped.set()
        executor.shutdown(wait=False, cancel_futures=True)
        raise
    executor.shutdown()
    _write_batch(batch, specs, records)
    return records


def _execute(task: TaskRun, context: RunContext) -> RunRecord:
    """One run, start to end; a failure is recorded in the run, never raised."""
    context.save()
    try:
        task(context)
        context.record.status = "completed"
    except Exception as error:
        context.record.status = "failed"
        context.record.error = f"{type(error).__name__}: {error}" + (context.record.error or "")
        (context.directory / "logs").mkdir(parents=True, exist_ok=True)
        (context.directory / "logs" / "harness-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
    context.record.ended_at = datetime.now(UTC)
    context.save()
    kept = (
        f"; kept: digital-twin-universe destroy --id {context.record.universe_id}"
        if context.spec.keep and context.record.universe_id
        else ""
    )
    context.report(f"{context.record.status}, score {context.record.score}{kept}")
    return context.record


def _write_batch(batch: Path, specs: list[RunSpec], records: dict[str, RunRecord]) -> None:
    summary = {
        "runs": len(specs),
        "finished": len(records),
        "records": {
            run_id: record.model_dump(
                mode="json", include={"status", "score", "capability_seconds", "usage", "timings", "error"}
            )
            for run_id, record in sorted(records.items())
        },
    }
    (batch / "batch.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", text)


if __name__ == "__main__":
    app()
