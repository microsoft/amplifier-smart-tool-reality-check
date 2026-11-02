"""The evaluations' deterministic parts: tasks, their profiles, the judge, usage totals, batches, and baselines."""

from datetime import UTC, datetime
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import threading
import time
from typing import Any
import urllib.request
import zipfile

from common import baselines, capability, collect_in_environment, idle, install, judge, usage
from common.context import Capability, Criterion, EvaluationError, Live, RunContext, RunRecord, RunSpec
from common.environment import HOME, PROFILE_PREFIX, Environment
from digital_twin_universe import lib as dtu
from digital_twin_universe.schemas import ExecResult
import jsonschema
import pytest
import run as runner
import yaml

COPILOT_OUTPUT = [
    {"type": "user.message", "data": {"content": "run: echo hello"}, "timestamp": "2026-01-01T00:00:00.000Z"},
    {"type": "assistant.message", "data": {"content": ""}, "timestamp": "2026-01-01T00:00:02.000Z"},
    {"type": "assistant.message", "data": {"content": "hello"}, "timestamp": "2026-01-01T00:00:04.700Z"},
    {"type": "result", "timestamp": "2026-01-01T00:00:04.700Z", "sessionId": "session-1", "exitCode": 0},
]
COPILOT_USAGE_RECORDS = [
    {
        "type": "session.usage_record",
        "data": {
            "usage": {
                "model": "m",
                "inputTokens": 100,
                "outputTokens": 10,
                "cacheReadTokens": 60,
                "cacheWriteTokens": 40,
                "reasoningTokens": 0,
                "cost": 1.0,
                "copilotUsage": {"totalNanoAiu": 1500000000},
            }
        },
    },
    {
        "type": "session.usage_record",
        "data": {
            "usage": {
                "model": "m",
                "inputTokens": 200,
                "outputTokens": 5,
                "cacheReadTokens": 150,
                "cacheWriteTokens": 50,
                "reasoningTokens": 0,
                "cost": 1.0,
                "copilotUsage": {"totalNanoAiu": 250000000},
            }
        },
    },
]
CLAUDE_OUTPUT = [
    {"type": "system", "subtype": "init", "session_id": "session-2"},
    {
        "type": "assistant",
        "message": {"id": "msg-1", "content": [{"type": "tool_use", "name": "Bash", "input": {}}]},
        "parent_tool_use_id": None,
        "timestamp": "2026-01-01T00:00:01.000Z",
    },
    {
        "type": "assistant",
        "message": {"id": "msg-2", "content": [{"type": "text", "text": "hello"}]},
        "parent_tool_use_id": None,
        "timestamp": "2026-01-01T00:00:03.500Z",
    },
    {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "duration_ms": 4200,
        "session_id": "session-2",
        "result": "hello",
        "total_cost_usd": 0.03,
    },
]
CLAUDE_TRANSCRIPT = [
    {
        "type": "assistant",
        "message": {
            "id": "msg-1",
            "model": "m",
            "usage": {
                "input_tokens": 2,
                "output_tokens": 3,
                "cache_read_input_tokens": 100,
                "cache_creation_input_tokens": 50,
            },
        },
    },
    {
        "type": "assistant",
        "message": {
            "id": "msg-1",
            "model": "m",
            "usage": {
                "input_tokens": 2,
                "output_tokens": 30,
                "cache_read_input_tokens": 100,
                "cache_creation_input_tokens": 50,
                "output_tokens_details": {"thinking_tokens": 10},
            },
        },
    },
    {
        "type": "assistant",
        "message": {
            "id": "msg-2",
            "model": "m",
            "usage": {
                "input_tokens": 4,
                "output_tokens": 5,
                "cache_read_input_tokens": 150,
                "cache_creation_input_tokens": 0,
            },
        },
    },
    {"type": "cost-state", "totalCostUSD": 0.03, "modelUsage": {"m": {"costUSD": 0.03}}},
]
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
    where = {"Its record of the run": "/p/record"}

    prompt = judge.render(
        judge.DEFAULT_PROMPT,
        request="Check it.",
        target=None,
        expected=expected,
        rubric=RUBRIC,
        report="/p/r.md",
        where=where,
        materials=materials,
        dtu="/bin/dtu",
    )

    assert "The arrow jumps." in prompt
    assert all(f"`{name}`" in prompt for name in RUBRIC)
    assert all(f"- {label}: `{path}`" in prompt for label, path in (where | materials).items())
    assert "`/p/r.md`" in prompt
    assert "`/bin/dtu`" in prompt
    assert "$" not in prompt


def test_the_judge_prompt_names_no_capability_s_own_files(tmp_path: Path) -> None:
    expected = tmp_path / "expected.md"
    expected.write_text("The arrow jumps.\n", encoding="utf-8")

    prompt = judge.render(
        judge.DEFAULT_PROMPT,
        request="Check it.",
        target=None,
        expected=expected,
        rubric=RUBRIC,
        report="/var/lib/evaluation/report.md",
        where={},
        materials={},
        dtu="/bin/dtu",
    )

    assert "check.json" not in prompt
    assert "evidence/" not in prompt


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


def _spec(task: str, repeat: int, capability: Capability = "reality-check") -> RunSpec:
    return RunSpec(
        task=task,
        capability=capability,
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

    records = runner.run_batch(tmp_path, {"a": stub("a"), "b": stub("b"), "c": failing}, specs, 1, None, Live())

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


def test_max_parallel_caps_the_runs_of_the_whole_batch(tmp_path: Path) -> None:
    running = 0
    most = 0
    lock = threading.Lock()

    def run(context: RunContext) -> None:
        nonlocal running, most
        with lock:
            running += 1
            most = max(most, running)
        time.sleep(0.1)
        with lock:
            running -= 1

    names = ("a", "b", "c", "d")
    specs = [_spec(name, repeat) for name in names for repeat in (1, 2)]

    records = runner.run_batch(tmp_path, dict.fromkeys(names, run), specs, 2, 3, Live())

    assert most == 3
    assert {record.status for record in records.values()} == {"completed"}
    assert len(records) == 8


def test_a_baseline_run_s_directory_names_its_capability_and_a_reality_check_run_s_does_not() -> None:
    assert runner.run_name(_spec("excalidraw-01", 2)) == "excalidraw-01-copilot-m-2"
    assert runner.run_name(_spec("excalidraw-01", 2, "baseline")) == "excalidraw-01-baseline-copilot-m-2"
    assert runner.run_name(_spec("excalidraw-01", 2, "installed")) == "excalidraw-01-installed-copilot-m-2"


def test_a_batch_skips_the_tasks_that_do_not_support_its_capability() -> None:
    tasks = {name: runner.load_task(name) for name in ("desktop-app-03", "excalidraw-01")}

    baseline, skipped = runner.supporting(tasks, "baseline")
    reality_check, none = runner.supporting(tasks, "reality-check")

    assert list(baseline) == ["excalidraw-01"]
    assert skipped == ["desktop-app-03"]
    assert list(reality_check) == ["desktop-app-03", "excalidraw-01"]
    assert none == []


def test_only_the_trigger_tasks_run_installed_and_they_do_not_run_reality_check() -> None:
    triggers = ["trigger-fix-01", "trigger-unit-tests-01", "trigger-verify-01"]
    tasks = {name: runner.load_task(name) for name in runner.task_names()}

    installed, skipped = runner.supporting(tasks, "installed")
    reality_check, _ = runner.supporting(tasks, "reality-check")
    baseline, _ = runner.supporting(tasks, "baseline")

    assert list(installed) == triggers
    assert "desktop-app-03" in skipped
    assert not set(triggers) & set(reality_check)
    assert set(baseline) == set(tasks) - {"desktop-app-03"}


def test_only_the_judge_of_a_baseline_needs_its_own_digital_twin_universe() -> None:
    assert install.dtu("baseline") == install.STANDALONE_DTU
    assert install.dtu("reality-check") == install.DTU
    assert install.dtu("installed") == install.DTU


class _Listing(Environment):
    def __init__(self, result: ExecResult) -> None:
        super().__init__("universe", Path())
        self.result = result

    def run(self, name: str, command: str, timeout_seconds: int = 600, user: str | None = None) -> ExecResult:
        return self.result


def test_an_installed_run_finds_the_checks_the_agent_ran() -> None:
    listed = [
        {"check_id": "c1", "project": {"root": "/home/user/project", "checks_directory": "/p/.agents/reality-check"}},
        {"check_id": "c2", "project": {"root": "/tmp/x", "checks_directory": "/tmp/x/checks"}},
    ]

    found = capability.agent_checks(_Listing(ExecResult(exit_code=0, stdout=json.dumps(listed), stderr="")))
    broken = capability.agent_checks(_Listing(ExecResult(exit_code=127, stdout="", stderr="not found")))

    assert found == ["/p/.agents/reality-check/c1", "/tmp/x/checks/c2"]
    assert broken == []


class _Recording(Environment):
    def __init__(self) -> None:
        super().__init__("universe", Path())
        self.commands: dict[str, str] = {}

    def run_checked(self, name: str, command: str, timeout_seconds: int = 600, user: str | None = None) -> ExecResult:
        self.commands[name] = command
        return ExecResult(exit_code=0, stdout="[]", stderr="")


@pytest.mark.parametrize(
    ("capability_name", "extra", "setups"),
    [("installed", "copilot", ["setup-claude", "setup-copilot"]), ("reality-check", "claude", ["setup-claude"])],
)
def test_an_installed_run_s_reality_check_runs_its_checks_on_copilot_whatever_the_cli(
    capability_name: Capability, extra: str, setups: list[str], tmp_path: Path
) -> None:
    spec = _spec("t", 1, capability_name).model_copy(
        update={"agent_provider": "claude", "judge_agent_provider": "claude"}
    )
    env = _Recording()

    install.provider_and_reality_check(env, RunContext(spec, tmp_path, Live()))

    assert [name for name in env.commands if name.startswith("setup-")] == setups
    assert f"reality-check[{extra}] @" in env.commands["install"]


def test_a_session_kept_as_a_transcript_is_copied_with_its_subagents(tmp_path: Path) -> None:
    sessions = tmp_path / "projects"
    (sessions / "-home-user-project" / "s1" / "subagents").mkdir(parents=True)
    (sessions / "-home-user-project" / "s1.jsonl").write_text("{}\n", encoding="utf-8")
    (sessions / "-home-user-project" / "s1" / "subagents" / "agent-a.jsonl").write_text("{}\n", encoding="utf-8")
    (sessions / "-home-user-project" / "s2.jsonl").write_text("{}\n", encoding="utf-8")

    collect_in_environment.transcript(sessions, "s1", tmp_path / "session")
    collect_in_environment.transcript(sessions, "missing", tmp_path / "none")

    copied = sorted(
        path.relative_to(tmp_path / "session").as_posix() for path in (tmp_path / "session").rglob("*.jsonl")
    )
    assert copied == ["s1.jsonl", "s1/subagents/agent-a.jsonl"]
    assert not (tmp_path / "none").exists()


def _todo_api(port: int, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
    sent = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(sent, timeout=5) as response:
        read = response.read()
    return json.loads(read) if read else None


def test_the_todo_app_s_server_adds_completes_and_deletes_by_id(tmp_path: Path) -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    with zipfile.ZipFile(runner.EVALUATIONS / "data" / "todo-app.zip") as archive:
        archive.extractall(tmp_path / "todo-app")
    app = tmp_path / "todo-app" / "app.py"
    server = subprocess.Popen(
        [sys.executable, str(app), "--port", str(port), "--data", str(tmp_path / "todos.json")],
        stdout=subprocess.PIPE,
        env=os.environ | {"PYTHONDONTWRITEBYTECODE": "1"},
    )
    try:
        assert server.stdout is not None
        assert str(port) in server.stdout.readline().decode()
        first, second, third = (_todo_api(port, "POST", "/api/todos", {"title": title}) for title in "ABC")
        _todo_api(port, "PATCH", f"/api/todos/{first['id']}", {"completed": True})
        _todo_api(port, "DELETE", f"/api/todos/{third['id']}")

        todos = _todo_api(port, "GET", "/api/todos")
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as page:
            html = page.read().decode()
    finally:
        server.terminate()
        server.wait(timeout=10)

    assert todos == [
        {"id": first["id"], "title": "A", "completed": True},
        {"id": second["id"], "title": "B", "completed": False},
    ]
    assert "app.js" in html


def test_the_baseline_is_given_the_request_with_the_target_added() -> None:
    assert baselines.prompt("Check it.", None) == "Check it."
    assert baselines.prompt("Check it.", "GitHub Desktop") == "Check it.\n\nTarget: GitHub Desktop"


def test_the_baseline_names_the_providers_it_can_run() -> None:
    with pytest.raises(EvaluationError, match="it runs: copilot, claude"):
        baselines.baseline("codex")


def test_copilot_s_output_reads_into_its_outcome_report_and_time() -> None:
    copilot = baselines.baseline("copilot")

    reading = copilot.read(COPILOT_OUTPUT, "")

    assert reading.outcome == {"status": "done", "session_id": "session-1"}
    assert reading.report == "hello"
    assert reading.seconds == 4.7


def test_copilot_output_without_a_result_is_a_failure_with_the_cli_s_error() -> None:
    copilot = baselines.baseline("copilot")
    found = COPILOT_OUTPUT[:2]

    reading = copilot.read(found, 'Error: Model "m" from --model flag is not available.\n')

    assert reading.outcome["status"] == "failed"
    assert reading.outcome["error"] == 'Error: Model "m" from --model flag is not available.'
    assert reading.report == ""


def test_copilot_s_usage_records_sum_like_reality_check_s_usage_events() -> None:
    copilot = baselines.baseline("copilot")

    records = "".join(json.dumps(record) + "\n" for record in COPILOT_USAGE_RECORDS)

    summary = copilot.read_usage(records + "not json\n")

    assert summary["calls"] == 2
    assert summary["input_tokens"] == 300
    assert summary["cache_read_tokens"] == 210
    assert summary["aiu"] == pytest.approx(1.75)
    assert summary["by_model"]["m"]["multiplier"] == 1.0


def test_claude_runs_headless_with_no_approvals_its_effort_and_the_session_id() -> None:
    claude = baselines.baseline("claude")

    command = claude.command("Check it.", "m", "xhigh", "session-2")

    assert command[:3] == ["claude", "-p", "Check it."]
    for flag, value in (("--model", "m"), ("--effort", "xhigh"), ("--output-format", "stream-json")):
        assert command[command.index(flag) + 1] == value
    assert command[command.index("--session-id") + 1] == "session-2"
    assert {"--dangerously-skip-permissions", "--verbose"} <= set(command)
    assert json.loads(command[command.index("--settings") + 1]) == {"env": {"DISABLE_AUTOUPDATER": "1"}}


def test_claude_s_output_reads_into_its_outcome_report_and_time() -> None:
    claude = baselines.baseline("claude")

    reading = claude.read(CLAUDE_OUTPUT, "")
    untimed = claude.read([event for event in CLAUDE_OUTPUT if "timestamp" not in event], "")

    assert reading.outcome == {"status": "done", "session_id": "session-2"}
    assert reading.report == "hello"
    assert reading.seconds == 2.5
    assert untimed.seconds == 4.2


def test_claude_output_with_a_failed_result_or_none_is_a_failure_with_its_error() -> None:
    claude = baselines.baseline("claude")
    failed = {**CLAUDE_OUTPUT[-1], "subtype": "error_during_execution", "is_error": True, "errors": ["it broke"]}

    errored = claude.read([*CLAUDE_OUTPUT[:-1], failed], "")
    ended = claude.read(CLAUDE_OUTPUT[:2], "Error: Invalid API key\n")

    assert errored.outcome == {"status": "failed", "session_id": "session-2", "error": "it broke"}
    assert errored.report == "hello"
    assert ended.outcome == {"status": "failed", "session_id": None, "error": "Error: Invalid API key"}
    assert ended.report == ""


def test_claude_s_transcript_sums_each_call_once_like_reality_check_s_usage_events() -> None:
    claude = baselines.baseline("claude")

    records = "".join(json.dumps(record) + "\n" for record in CLAUDE_TRANSCRIPT)

    summary = claude.read_usage(records + "not json\n")

    assert summary["calls"] == 2
    assert summary["input_tokens"] == 6
    assert summary["output_tokens"] == 35
    assert summary["cache_read_tokens"] == 250
    assert summary["cache_write_tokens"] == 50
    assert summary["reasoning_tokens"] == 10
    assert summary["usd"] == pytest.approx(0.03)
    assert summary["by_model"]["m"]["usd"] == pytest.approx(0.03)


def test_an_installed_run_s_skill_goes_where_its_cli_loads_skills() -> None:
    assert baselines.baseline("copilot").skills == f"{HOME}/.agents/skills"
    assert baselines.baseline("claude").skills == f"{HOME}/.claude/skills"


# Copilot's session as it ends its turn, then as it starts its next, and a tool call under way.
COPILOT_SESSION = [
    {"type": "assistant.message", "data": {"content": "Done."}, "timestamp": "2026-11-02T15:18:04.700Z"},
    {"type": "assistant.turn_end", "data": {"turnId": "24"}, "timestamp": "2026-11-02T15:18:04.719Z"},
    {"type": "session.usage_checkpoint", "data": {}, "timestamp": "2026-11-02T15:18:04.732Z"},
]
COPILOT_NEXT_TURN = [
    {
        "type": "system.notification",
        "data": {"kind": {"type": "shell_completed"}},
        "timestamp": "2026-11-02T15:22:05.245Z",
    },
    {"type": "assistant.message", "data": {"content": ""}, "timestamp": "2026-11-02T15:22:05.246Z"},
    {"type": "tool.execution_start", "data": {"toolName": "read_bash"}, "timestamp": "2026-11-02T15:22:05.247Z"},
]
# Claude Code's transcript lines for a tool call, its result, and the agent's last message.
CLAUDE_SESSION = [
    {
        "type": "assistant",
        "message": {"stop_reason": "tool_use", "content": [{"type": "tool_use", "name": "Bash"}]},
        "timestamp": "2026-11-02T15:54:47.978Z",
    },
    {
        "type": "user",
        "message": {"content": [{"type": "tool_result"}]},
        "timestamp": "2026-11-02T15:54:48.038Z",
    },
    {
        "type": "assistant",
        "message": {"stop_reason": "end_turn", "content": [{"type": "text", "text": "DONE"}]},
        "timestamp": "2026-11-02T15:54:48.537Z",
    },
]
# Copilot's printed events around an operator's stop: its turn ends, its background shell changes, and SIGTERM.
COPILOT_STOPPED_OUTPUT = [
    {"type": "user.message", "data": {"content": "Start it."}, "timestamp": "2026-11-02T15:32:45.000Z"},
    {"type": "assistant.message", "data": {"content": "DONE"}, "timestamp": "2026-11-02T15:32:51.463Z"},
    {"type": "assistant.turn_end", "data": {"turnId": "1"}, "timestamp": "2026-11-02T15:32:51.465Z"},
    {"type": "session.usage_checkpoint", "data": {}, "timestamp": "2026-11-02T15:32:51.468Z"},
    {"type": "assistant.idle", "data": {}, "ephemeral": True, "timestamp": "2026-11-02T15:32:51.469Z"},
    {"type": "session.background_tasks_changed", "ephemeral": True, "timestamp": "2026-11-02T15:33:40.695Z"},
    {"type": "abort", "data": {"reason": "user_initiated"}, "timestamp": "2026-11-02T15:33:40.696Z"},
    {"type": "assistant.idle", "data": {"aborted": True}, "ephemeral": True, "timestamp": "2026-11-02T15:33:40.697Z"},
    {"type": "session.background_tasks_changed", "ephemeral": True, "timestamp": "2026-11-02T15:33:40.700Z"},
    {"type": "result", "timestamp": "2026-11-02T15:33:40.702Z", "sessionId": "session-1", "exitCode": 0},
]
STOP = {"by": "operator", "at": "2026-11-02T15:33:40.500000+00:00", "forced": False, "idle_seconds": 48.0}


def test_copilot_s_session_shows_its_turn_ended_until_the_next_starts() -> None:
    copilot = baselines.baseline("copilot")

    ended = copilot.turn(COPILOT_SESSION)
    woken = copilot.turn(COPILOT_SESSION + COPILOT_NEXT_TURN)
    working = copilot.turn(COPILOT_SESSION[:1])

    assert ended.ended == datetime(2026, 11, 2, 15, 18, 4, 719000, tzinfo=UTC)
    assert ended.active == datetime(2026, 11, 2, 15, 18, 4, 732000, tzinfo=UTC)
    assert woken.ended is None
    assert woken.active == datetime(2026, 11, 2, 15, 22, 5, 247000, tzinfo=UTC)
    assert working.ended is None
    assert copilot.turn([]) == baselines.Turn(ended=None, active=None)


def test_claude_s_transcript_shows_its_turn_ended_at_its_end_turn_message() -> None:
    claude = baselines.baseline("claude")

    ended = claude.turn(CLAUDE_SESSION)
    calling = claude.turn(CLAUDE_SESSION[:1])
    answered = claude.turn(CLAUDE_SESSION[:2])

    assert ended.ended == datetime(2026, 11, 2, 15, 54, 48, 537000, tzinfo=UTC)
    assert calling.ended is None
    assert answered.ended is None
    assert answered.active == datetime(2026, 11, 2, 15, 54, 48, 38000, tzinfo=UTC)


def test_the_cli_process_patterns_match_the_cli_alone() -> None:
    for name in ("copilot", "claude"):
        cli = baselines.baseline(name)
        command = " ".join(cli.command("Check it.", "m", "high", "1f0c8a52-2b7e-4c3e-9a51-0d6f1c2b9e11"))
        pattern = re.compile(cli.process("1f0c8a52-2b7e-4c3e-9a51-0d6f1c2b9e11"))

        assert pattern.search(command)
        assert pattern.search(f"/home/user/.local/bin/{command}")
        assert not pattern.search(f"timeout --kill-after=30 1800 {command}")
        assert not pattern.search(f"bash -lc pgrep -o -f {pattern.pattern}")


def test_a_stopped_copilot_run_s_time_ends_at_its_last_event_before_the_stop(tmp_path: Path) -> None:
    (tmp_path / idle.STOPPED).write_text(json.dumps(STOP), encoding="utf-8")

    stop = idle.read_stop(tmp_path, baselines.baseline("copilot").worked(COPILOT_STOPPED_OUTPUT))
    unstopped = idle.read_stop(tmp_path / "none", None)

    assert stop is not None
    stopped, seconds = stop
    assert seconds == 6.5
    assert stopped == STOP | {"idle_seconds": 49.0}
    assert unstopped is None


class _Capturing(Environment):
    def __init__(self, directory: Path, stdout: str, exit_code: int) -> None:
        super().__init__("universe", directory / "logs")
        self.directory = directory
        self.stdout = stdout
        self.exit_code = exit_code
        self.saved: dict[str, Any] = {}
        self.command = ""

    def capture(self, name: str, command: str, timeout_seconds: int) -> ExecResult:
        if name != "capability":
            return ExecResult(exit_code=0, stdout="", stderr="")
        self.saved = json.loads((self.directory / "run.json").read_text(encoding="utf-8"))
        self.command = command
        return ExecResult(exit_code=self.exit_code, stdout=self.stdout, stderr="")


@pytest.mark.parametrize(
    ("provider", "output", "exit_code", "seconds"),
    [
        ("copilot", COPILOT_STOPPED_OUTPUT, 0, 6.5),
        ("claude", [*CLAUDE_OUTPUT, {"type": "system", "subtype": "task_notification", "status": "stopped"}], 143, 2.5),
    ],
)
def test_a_stopped_run_is_done_by_the_cli_s_result_with_the_stop_in_its_outcome(
    provider: str, output: list[dict[str, Any]], exit_code: int, seconds: float, tmp_path: Path
) -> None:
    spec = _spec("t", 1, "baseline").model_copy(update={"agent_provider": provider})
    context = RunContext(spec, tmp_path, Live())
    (tmp_path / "logs").mkdir()
    (tmp_path / idle.STOPPED).write_text(json.dumps(STOP), encoding="utf-8")
    env = _Capturing(tmp_path, "".join(json.dumps(event) + "\n" for event in output), exit_code)

    result = capability.baseline(env, context, "Check it.")

    assert f"--session-id {env.saved['outcome']['session_id']}" in env.command
    assert result.outcome["status"] == "done"
    assert result.outcome["exit_code"] == exit_code
    assert result.outcome["stopped"]["by"] == "operator"
    assert result.seconds == seconds
    assert context.record.capability_seconds == seconds


def _running(**changes: Any) -> RunRecord:
    record = RunRecord(
        run_id="r",
        spec=_spec("t", 1, "installed"),
        step="capability",
        universe_id="u",
        outcome={"session_id": "s"},
    )
    return record.model_copy(update=changes)


def test_a_run_s_cli_is_stopped_only_while_it_runs_and_its_agent_has_ended_its_turn() -> None:
    now = datetime(2026, 11, 2, 15, 0, tzinfo=UTC)
    cli = idle.Process(pid=7, seconds=60, command="copilot -p ...")
    ended = idle.Look(turn=baselines.Turn(ended=now, active=now), cli=cli, under=[])
    working = idle.Look(turn=baselines.Turn(ended=None, active=now), cli=cli, under=[])

    assert idle.refusal(_running()) is None
    assert idle.refusal(_running(), ended) is None
    assert "has not ended its turn" in str(idle.refusal(_running(), working))
    assert idle.refusal(_running(), working, force=True) is None
    assert "no copilot process" in str(idle.refusal(_running(), ended._replace(cli=None), force=True))
    assert "at the judge step" in str(idle.refusal(_running(step="judge")))
    assert "is completed" in str(idle.refusal(_running(status="completed")))
    assert "only a baseline or installed run" in str(idle.refusal(_running(spec=_spec("t", 1))))
    assert "has not recorded" in str(idle.refusal(_running(outcome={})))


def test_stop_refuses_a_run_stopped_already_and_one_past_its_cli(tmp_path: Path) -> None:
    (tmp_path / "run.json").write_text(_running(step="collect").model_dump_json(), encoding="utf-8")

    with pytest.raises(EvaluationError, match="at the collect step"):
        idle.stop(tmp_path)
    (tmp_path / idle.STOPPED).write_text("{}", encoding="utf-8")
    with pytest.raises(EvaluationError, match="stopped already"):
        idle.stop(tmp_path)


def test_the_processes_under_the_cli_are_every_descendant_of_it() -> None:
    listed = """\
      1       0   900 /sbin/init
     40       1   600 timeout --kill-after=30 1800 copilot -p Check it.
     41      40   600 copilot -p Check it. --session-id s
     52      41   300 /bin/bash
     53      52   299 reality-check app --port 8080
     60       1    10 sleep 5
"""

    cli, under = idle.processes(listed, 41)
    gone, none = idle.processes(listed, 99)

    assert cli == idle.Process(pid=41, seconds=600, command="copilot -p Check it. --session-id s")
    assert [process.pid for process in under] == [52, 53]
    assert under[1].command == "reality-check app --port 8080"
    assert (gone, none) == (None, [])


def test_waiting_names_the_newest_batch_even_while_it_runs_or_the_one_given(tmp_path: Path) -> None:
    for name in ("20261101T000000Z-aaaaaa", "20261102T000000Z-bbbbbb"):
        (tmp_path / name / "run-1").mkdir(parents=True)
        (tmp_path / name / "run-1" / "run.json").write_text("{}", encoding="utf-8")
    (tmp_path / "20261101T000000Z-aaaaaa" / "batch.json").write_text("{}", encoding="utf-8")

    assert idle.batch(tmp_path, None).name == "20261102T000000Z-bbbbbb"
    assert idle.batch(tmp_path, "20261101T000000Z-aaaaaa").name == "20261101T000000Z-aaaaaa"
    assert idle.batch(tmp_path, str(tmp_path / "20261101T000000Z-aaaaaa")) == tmp_path / "20261101T000000Z-aaaaaa"
    with pytest.raises(EvaluationError, match="No batch 'nope'"):
        idle.batch(tmp_path, "nope")


def test_waiting_describes_the_agent_s_turn_and_what_runs_under_its_cli() -> None:
    now = datetime(2026, 11, 2, 15, 22, 5, tzinfo=UTC)
    cli = idle.Process(pid=41, seconds=900, command="copilot -p " + "x" * 300)
    server = idle.Process(pid=53, seconds=245, command="reality-check app")
    seen = idle.Look(
        turn=baselines.Turn(ended=datetime(2026, 11, 2, 15, 18, 4, tzinfo=UTC), active=None), cli=cli, under=[server]
    )

    described = idle.describe(_running(), seen, now)

    assert described.splitlines()[0] == "r: ended its turn 4m01s ago"
    assert described.splitlines()[1].endswith("...")
    assert described.splitlines()[2] == "  under      53      4m05s  reality-check app"
