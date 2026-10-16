"""The judge's prompt and submit schema, built from the task, and the score computed from what it submits."""

from pathlib import Path
from string import Template
from typing import Any

from harness.tasks import Task

PROMPT = Path(__file__).resolve().parent / "judge-prompt.md"


def prompt(task: Task, project: str, report: str, record: str, session: str, changes: str, dtu: str) -> str:
    rubric = "\n".join(
        f"- `{name}` (weight {criterion.weight:g}): {criterion.description}" for name, criterion in task.rubric.items()
    )
    return Template(PROMPT.read_text(encoding="utf-8")).substitute(
        request=task.request,
        project=project,
        target=task.target or "named in the request",
        expected=task.expected.read_text(encoding="utf-8").strip(),
        rubric=rubric,
        report=report,
        record=record,
        session=session,
        changes=changes,
        dtu=dtu,
    )


def schema(task: Task) -> dict[str, Any]:
    """The submit tool's schema: exactly the rubric's criteria, each a 0 to 100 score with its reason and files."""
    criterion = {
        "type": "object",
        "properties": {
            "score": {"type": "integer", "minimum": 0, "maximum": 100},
            "reason": {"type": "string"},
            "files": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["score", "reason", "files"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "criteria": {
                "type": "object",
                "properties": dict.fromkeys(task.rubric, criterion),
                "required": list(task.rubric),
                "additionalProperties": False,
            },
        },
        "required": ["summary", "criteria"],
        "additionalProperties": False,
    }


def score(task: Task, submitted: dict[str, Any]) -> float:
    """The weighted mean of the criterion scores, 0 to 100."""
    criteria = submitted["criteria"]
    total = sum(criterion.weight for criterion in task.rubric.values())
    weighted = sum(criterion.weight * criteria[name]["score"] for name, criterion in task.rubric.items())
    return round(weighted / total, 1)
