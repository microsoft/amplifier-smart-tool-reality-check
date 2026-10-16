"""The evaluation harness's deterministic parts: tasks, the judge's schema and score, and usage totals."""

from harness import grading, usage
from harness.tasks import EvaluationError, load_task, task_names
import jsonschema
import pytest


def test_every_task_loads_with_the_files_it_names() -> None:
    assert task_names()
    for name in task_names():
        task = load_task(name)
        assert task.expected.is_file()
        assert all((task.directory / source).exists() for source in task.files)


def test_an_unknown_task_names_the_ones_there_are() -> None:
    with pytest.raises(EvaluationError, match="excalidraw-01"):
        load_task("no-such-task")


def test_the_submit_schema_takes_exactly_the_rubric_and_the_score_is_the_weighted_mean() -> None:
    task = load_task("excalidraw-01")
    schema = grading.schema(task)
    submitted = {
        "summary": "Found it.",
        "criteria": {
            name: {"score": 100 if name == "found-the-defect" else 0, "reason": "", "files": []} for name in task.rubric
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
    total = sum(criterion.weight for criterion in task.rubric.values())
    assert grading.score(task, submitted) == round(100 * task.rubric["found-the-defect"].weight / total, 1)


def test_the_judge_prompt_carries_the_answer_key_and_every_criterion() -> None:
    task = load_task("excalidraw-01")

    prompt = grading.prompt(task, "/p", "/p/r.md", "/p/record", "/s", "/c", "/dtu")

    assert task.expected.read_text(encoding="utf-8").strip() in prompt
    assert all(f"`{name}`" in prompt for name in task.rubric)
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
