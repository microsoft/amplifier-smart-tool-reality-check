"""The evaluations' deterministic parts: tasks, their profiles, the judge, usage totals, and batch scheduling."""

from pathlib import Path
import threading
import time

from common import judge, usage
from common.context import Criterion, EvaluationError, Live, RunContext, RunSpec
from common.environment import PROFILE_PREFIX
from digital_twin_universe import lib as dtu
import jsonschema
import pytest
import run as runner
import yaml

RUBRIC = {
    "found-the-defect": Criterion(weight=4, description="Found it."),
    "evidence": Criterion(weight=3, description="Showed it."),
    "no-false-findings": Criterion(weight=1, description="Nothing else."),
}


def test_every_task_loads_with_its_answer_key() -> None:
    assert runner.task_names()
    for name in runner.task_names():
        task = runner.load_task(name)
        assert task.DESCRIPTION
        assert callable(task.run)
        assert (runner.TASKS_DIRECTORY / name / "expected.md").is_file()


def test_an_unknown_task_names_the_ones_there_are() -> None:
    with pytest.raises(EvaluationError, match="excalidraw-01"):
        runner.load_task("no-such-task")


@pytest.mark.parametrize("name", runner.task_names())
def test_every_task_profile_is_named_for_its_task_and_valid(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GH_TOKEN", "token")
    profile = runner.TASKS_DIRECTORY / name / "environment"
    with (profile / "compose.yaml").open(encoding="utf-8") as file:
        assert yaml.safe_load(file)["name"] == f"{PROFILE_PREFIX}{name}"

    report = dtu.validate_profile(profile)

    assert report.ok, report.errors


def test_the_submit_schema_takes_exactly_the_rubric_and_the_score_is_the_weighted_mean() -> None:
    schema = judge.schema(RUBRIC)
    submitted = {
        "summary": "Found it.",
        "criteria": {
            name: {"score": 100 if name == "found-the-defect" else 0, "reason": "", "files": []} for name in RUBRIC
        },
    }

    jsonschema.validate(submitted, schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            {**submitted, "criteria": {**submitted["criteria"], "extra": submitted["criteria"]["evidence"]}}, schema
        )
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            {**submitted, "criteria": {**submitted["criteria"], "evidence": {"score": 101, "reason": "", "files": []}}},
            schema,
        )
    assert judge.score(RUBRIC, submitted) == round(100 * 4 / 8, 1)


def test_a_criterion_name_must_be_kebab_case() -> None:
    with pytest.raises(EvaluationError, match="Found_It"):
        judge.schema({"Found_It": Criterion(weight=1, description="")})


def test_the_judge_prompt_carries_the_answer_key_every_criterion_and_every_material(tmp_path: Path) -> None:
    expected = tmp_path / "expected.md"
    expected.write_text("The arrow jumps.\n", encoding="utf-8")
    materials = {"The orders table": "/var/lib/evaluation/orders.json", "The server": "ssh home-server-2"}

    prompt = judge.render(
        judge.DEFAULT_PROMPT,
        request="Check it.",
        target=None,
        expected=expected,
        rubric=RUBRIC,
        report="/p/r.md",
        record="/p/record",
        materials=materials,
    )

    assert "The arrow jumps." in prompt
    assert all(f"`{name}`" in prompt for name in RUBRIC)
    assert all(f"- {label}: `{path}`" in prompt for label, path in materials.items())
    assert "$" not in prompt


def test_usage_sums_tokens_and_the_provider_s_cost_by_model() -> None:
    def call(model: str) -> dict:
        data = {
            "model": model,
            "input_tokens": 10,
            "output_tokens": 2,
            "cost": 1.0,
            "copilot_usage": {"totalNanoAiu": 5e8},
        }
        return {"kind": "usage", "data": data}

    summary = usage.summarize([call("a"), call("a"), call("b"), {"kind": "tool", "data": {}}])

    assert summary["calls"] == 3
    assert summary["input_tokens"] == 30
    assert summary["aiu"] == 1.5
    assert "multiplier" not in summary
    assert summary["by_model"]["a"]["calls"] == 2
    assert summary["by_model"]["a"]["multiplier"] == 1.0


def test_usage_sums_a_cost_reported_in_dollars() -> None:
    def call(dollars: float) -> dict:
        return {"kind": "usage", "data": {"model": "m", "input_tokens": 5, "cost": {"USD": dollars}}}

    summary = usage.summarize([call(0.25), call(0.5)])

    assert summary["usd"] == 0.75
    assert summary["by_model"]["m"]["usd"] == 0.75
    assert "multiplier" not in summary["by_model"]["m"]


def _spec(task: str, repeat: int) -> RunSpec:
    return RunSpec(
        task=task,
        agent_provider="copilot",
        model="m",
        reasoning_effort="medium",
        repeat=repeat,
        judge_agent_provider="copilot",
        judge_model="j",
        judge_reasoning_effort="high",
        judge_timeout_seconds=1,
    )


def test_runs_of_different_tasks_overlap_and_runs_of_one_task_do_not(tmp_path: Path) -> None:
    spans: dict[str, list[tuple[float, float]]] = {"a": [], "b": []}
    lock = threading.Lock()

    def stub(name: str) -> runner.TaskRun:
        def run(context: RunContext) -> None:
            started = time.monotonic()
            time.sleep(0.2)
            with lock:
                spans[name].append((started, time.monotonic()))

        return run

    def failing(context: RunContext) -> None:
        raise EvaluationError("broken")

    specs = [_spec(name, repeat) for name in ("a", "b", "c") for repeat in (1, 2)]

    records = runner.run_batch(tmp_path, {"a": stub("a"), "b": stub("b"), "c": failing}, specs, 1, Live())

    for name in ("a", "b"):
        first, second = sorted(spans[name])
        assert first[1] <= second[0]
    assert spans["a"][0][0] < spans["b"][0][1]
    assert spans["b"][0][0] < spans["a"][0][1]
    assert len(records) == 6
    assert {record.status for record in records.values() if record.spec.task != "c"} == {"completed"}
    failed = [record for record in records.values() if record.spec.task == "c"]
    assert all(record.status == "failed" and record.error == "EvaluationError: broken" for record in failed)
    assert all((tmp_path / record.run_id / "logs" / "harness-error.txt").is_file() for record in failed)
    assert (tmp_path / "batch.json").is_file()
