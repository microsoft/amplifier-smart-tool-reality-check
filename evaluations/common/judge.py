"""The host side of the judge: its prompt and submit schema, a run of it in the twin, and the score."""

import json
from pathlib import Path
import re
import shlex
from string import Template
from typing import Any

from common import capability, install, providers, usage
from common.capability import CapabilityResult
from common.collect import home
from common.context import Criterion, EvaluationError, RunContext
from common.environment import HOME, PROJECT, WORK, Environment

DEFAULT_PROMPT = Path(__file__).resolve().parent / "judge-prompt.md"
IN_ENVIRONMENT = Path(__file__).resolve().parent / "judge_in_environment.py"
# Criterion names become property names in the judge's submit schema.
CRITERION_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
# Time past the judge's own timeout for it to stop and write its result.
GRACE_SECONDS = 300


def grade(
    env: Environment,
    context: RunContext,
    request: str,
    expected: Path,
    rubric: dict[str, Criterion],
    result: CapabilityResult,
    target: str | None = None,
    materials: dict[str, str] | None = None,
    prompt: Path = DEFAULT_PROMPT,
) -> None:
    """Have a judge agent in the twin score every criterion, and write `grade.json` and the run's score.

    `materials` adds lines to the prompt's list of what is on the machine, label to path or note, for what the
    task collected itself.
    """
    record = result.record_directory or "(the capability left no record)"
    provider = providers.provider(context.spec.judge_agent_provider)
    config = {
        "agent_provider": context.spec.judge_agent_provider,
        "model": context.spec.judge_model,
        "reasoning_effort": context.spec.judge_reasoning_effort,
        "workspace": HOME,
        "timeout_seconds": context.spec.judge_timeout_seconds,
        "output_schema": schema(rubric),
        "prompt": render(
            prompt,
            request=request,
            target=target,
            expected=expected,
            rubric=rubric,
            report=f"{record}/report.md",
            record=record,
            materials=materials or {},
        ),
    }
    env.run_checked("judge-work", f"mkdir -p {WORK}/judge")
    env.push(IN_ENVIRONMENT, f"{WORK}/judge/judge.py")
    env.push_json(config, f"{WORK}/judge/config.json")
    requirement = shlex.quote(install.spec(provider.extra))
    env.run(
        "judge",
        f"cd {HOME} && uv run --no-project --with {requirement} python {WORK}/judge/judge.py {WORK}/judge/config.json",
        timeout_seconds=context.spec.judge_timeout_seconds + GRACE_SECONDS,
    )
    judged = context.directory / "judge"
    env.pull(f"{WORK}/judge", judged)
    context.record.usage["judge"] = usage.summarize(capability.events(judged / "events.jsonl"))
    result_path = judged / "result.json"
    if not result_path.is_file():
        raise EvaluationError(f"The judge wrote no result; see {context.logs / 'judge.log'}.")
    submitted = json.loads(result_path.read_text(encoding="utf-8"))
    if submitted.get("session_id"):
        env.pull(f"{home(provider.sessions)}/{submitted['session_id']}", judged / "session")
    if submitted.get("output") is None:
        raise EvaluationError(f"The judge submitted no grade: {submitted.get('error')}")
    context.record.score = score(rubric, submitted["output"])
    graded = {
        "judge": context.spec.model_dump(include={"judge_agent_provider", "judge_model", "judge_reasoning_effort"}),
        **submitted["output"],
        "score": context.record.score,
    }
    (context.directory / "grade.json").write_text(json.dumps(graded, indent=2), encoding="utf-8")


def render(
    prompt: Path,
    request: str,
    target: str | None,
    expected: Path,
    rubric: dict[str, Criterion],
    report: str,
    record: str,
    materials: dict[str, str],
) -> str:
    """The judge's prompt from the template at `prompt`."""
    criteria = "\n".join(
        f"- `{name}` (weight {criterion.weight:g}): {criterion.description}" for name, criterion in rubric.items()
    )
    return Template(prompt.read_text(encoding="utf-8")).substitute(
        request=request,
        project=PROJECT,
        target=target or "named in the request",
        expected=expected.read_text(encoding="utf-8").strip(),
        rubric=criteria,
        report=report,
        record=record,
        session=f"{WORK}/out/session",
        changes=f"{WORK}/out (changes.json, changes/, installed.diff, logs/)",
        dtu=install.DTU,
        materials="".join(f"\n- {label}: `{path}`" for label, path in materials.items()),
    )


def schema(rubric: dict[str, Criterion]) -> dict[str, Any]:
    """The submit tool's schema: exactly the rubric's criteria, each a 0 to 100 score with its reason and files."""
    invalid = [name for name in rubric if not CRITERION_PATTERN.match(name)]
    if not rubric or invalid:
        raise EvaluationError(f"A rubric needs criteria named in lowercase kebab case; these are not: {invalid}.")
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
                "properties": dict.fromkeys(rubric, criterion),
                "required": list(rubric),
                "additionalProperties": False,
            },
        },
        "required": ["summary", "criteria"],
        "additionalProperties": False,
    }


def score(rubric: dict[str, Criterion], submitted: dict[str, Any]) -> float:
    """The weighted mean of the criterion scores, 0 to 100."""
    criteria = submitted["criteria"]
    total = sum(criterion.weight for criterion in rubric.values())
    weighted = sum(criterion.weight * criteria[name]["score"] for name, criterion in rubric.items())
    return round(weighted / total, 1)
