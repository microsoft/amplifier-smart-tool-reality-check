"""Evaluate reality-check's capabilities on tasks, each run in its own evaluation environment, many at once.

uv run evaluations/run.py run --task excalidraw-01 --model gpt-6.1-sol --repeat 3 --parallel 3
uv run evaluations/run.py cleanup
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
import json
from pathlib import Path
import re
import secrets
import tempfile
import threading
from typing import Annotated

from harness import images, providers
from harness.environment import destroy_leftovers
from harness.evaluation import Live, Run, RunRecord, RunSpec
from harness.tasks import EvaluationError, Task, load_task, task_names
import typer

from reality_check.schemas import DEFAULT_INTELLIGENCE_MODELS, AgentProvider, ReasoningEffort

RUNS_DIRECTORY = Path(__file__).resolve().parent / "runs"

app = typer.Typer(add_completion=False, no_args_is_help=True)
_print_lock = threading.Lock()


def _print(line: str) -> None:
    with _print_lock:
        typer.echo(f"{datetime.now().strftime('%H:%M:%S')} {line}", err=True)


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
    reasoning_effort: Annotated[ReasoningEffort, typer.Option("--reasoning-effort")] = "medium",
    repeat: Annotated[int, typer.Option("--repeat", min=1, help="Runs of each task and model.")] = 1,
    parallel: Annotated[int, typer.Option("--parallel", min=1, help="Runs at the same time.")] = 2,
    judge_agent_provider: Annotated[AgentProvider, typer.Option("--judge-agent-provider")] = "copilot",
    judge_model: Annotated[
        str | None, typer.Option("--judge-model", help="The judge provider's default when omitted.")
    ] = None,
    judge_reasoning_effort: Annotated[ReasoningEffort, typer.Option("--judge-reasoning-effort")] = "high",
    judge_timeout_seconds: Annotated[int, typer.Option("--judge-timeout-seconds", min=1)] = 1800,
    keep: Annotated[bool, typer.Option("--keep", help="Leave each evaluation environment running.")] = False,
) -> None:
    """Run every task x model x repeat, and write a batch directory under evaluations/runs."""
    try:
        tasks = [load_task(name) for name in (task or task_names())]
        for name in dict.fromkeys([agent_provider, judge_agent_provider]):
            providers.export_credentials(name)
    except EvaluationError as error:
        raise typer.BadParameter(str(error)) from error
    specs = [
        RunSpec(
            task=each.name,
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
        for each in tasks
        for each_model in (model or [DEFAULT_INTELLIGENCE_MODELS[agent_provider]])
        for index in range(1, repeat + 1)
    ]
    batch = RUNS_DIRECTORY / f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(3)}"
    batch.mkdir(parents=True)
    with tempfile.TemporaryDirectory() as scratch:
        archives = {}
        for each in tasks:
            if each.images:
                _print(f"building the images of {each.name}")
            try:
                archives[each.name] = images.build(each, Path(scratch), batch / "logs" / f"images-{each.name}.log")
            except EvaluationError as error:
                raise typer.BadParameter(str(error)) from error
        _run_batch(batch, tasks, specs, archives, parallel)


def _run_batch(
    batch: Path, tasks: list[Task], specs: list[RunSpec], archives: dict[str, Path | None], parallel: int
) -> None:
    by_name = {each.name: each for each in tasks}
    live = Live()
    records: dict[str, RunRecord] = {}
    runs = [
        Run(
            spec,
            by_name[spec.task],
            batch / _slug(f"{spec.task}-{spec.agent_provider}-{spec.model}-{spec.repeat}"),
            archives[spec.task],
            live,
            _print,
        )
        for spec in specs
    ]
    _print(f"batch {batch} with {len(runs)} runs, {parallel} at a time")
    executor = ThreadPoolExecutor(max_workers=parallel)
    try:
        futures = {executor.submit(each.execute): each for each in runs}
        for future in as_completed(futures):
            record = future.result()
            records[record.run_id] = record
            _write_batch(batch, specs, records)
    except KeyboardInterrupt:
        _print("interrupted; destroying the running evaluation environments")
        executor.shutdown(wait=False, cancel_futures=True)
        for universe in live.destroy_all():
            _print(f"destroyed {universe}")
        raise typer.Exit(130) from None
    executor.shutdown()
    _write_batch(batch, specs, records)
    for record in records.values():
        typer.echo(
            json.dumps(
                {
                    "run_id": record.run_id,
                    "status": record.status,
                    "score": record.score,
                    "capability_seconds": record.capability_seconds,
                    "aiu": record.usage.get("capability", {}).get("aiu"),
                    "error": record.error,
                }
            )
        )


@app.command()
def cleanup() -> None:
    """Destroy every evaluation environment on this machine, including ones a killed batch left running."""
    for universe in destroy_leftovers():
        typer.echo(f"destroyed {universe}")


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
