"""Reads a check's activity from its files, as another process does, while it runs and after it ended."""

import json
from pathlib import Path
import subprocess
import sys

from fakes import FakeIntelligence, Unavailable, finishes, waits_for_steering
import pytest
from typer.testing import CliRunner

from reality_check import lib
from reality_check.capabilities.check_software import check
from reality_check.cli import app
from reality_check.schemas import CheckRecord, RealityCheckError

runner = CliRunner()


@pytest.fixture(autouse=True)
def skills_cache(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(check, "SKILLS_CACHE_DIRECTORY", tmp_path_factory.mktemp("skills-cache"))
    monkeypatch.setattr(check, "POLL_SECONDS", 0.01)


async def finished_check(tmp_path: Path) -> lib.CheckRun:
    run = await lib.check_software(
        "Check the page", checks_directory=tmp_path, origin="app", intelligence=FakeIntelligence(waits_for_steering)
    )
    await run.steer("Use the second account.")
    await run.result()
    return run


async def test_each_event_is_an_entry_and_tool_entries_leave_out_the_full_content(tmp_path: Path) -> None:
    run = await lib.check_software(
        "Check the page", checks_directory=tmp_path, intelligence=FakeIntelligence(finishes())
    )
    await run.result()

    activity = lib.read_check_activity(run.check_id, checks_directory=tmp_path)

    kinds = [entry.kind for entry in activity.entries]
    assert kinds == ["request", "said", "reasoning", "tool", "usage", "tool-result", "ended"]
    request, said, reasoning, call, _, result, ended = activity.entries
    assert (request.text, request.origin) == ("Check the page", "unknown")
    assert "initial_message" not in request.data["agent_request"]
    assert request.data["model"] == "gpt-6.1-sol"
    assert said.text == "Opening the page."
    assert reasoning.text == "The page is the target."
    assert call.data == {"tool_call_id": "call-1", "tool_name": "bash"}
    assert result.data == {"tool_call_id": "call-1", "success": True}
    assert len(result.text) < 600
    assert ended.data == {"status": "done", "report": str(run.directory / "report.md")}
    assert activity.state == "done"
    assert activity.process_log is None
    assert activity.cursor == (run.directory / "events.jsonl").stat().st_size


async def test_steering_and_a_failure_are_entries_with_who_and_how(tmp_path: Path) -> None:
    steered = await finished_check(tmp_path)
    failed = await lib.check_software("Check", checks_directory=tmp_path, intelligence=Unavailable(finishes()))
    with pytest.raises(RealityCheckError):
        await failed.result()

    steering = lib.read_check_activity(steered.check_id, checks_directory=tmp_path).entries
    failure = lib.read_check_activity(failed.check_id, checks_directory=tmp_path)

    [entry] = [entry for entry in steering if entry.kind == "steered"]
    assert (entry.text, entry.origin, entry.data) == ("Use the second account.", "app", {"steering": "mid-turn"})
    assert failure.state == "failed"
    assert failure.entries[-1].data == {"code": "model-not-available", "remedy": "Pick another."}


async def test_a_cursor_reads_on_from_where_the_last_read_ended(tmp_path: Path) -> None:
    run = await finished_check(tmp_path)
    events = run.directory / "events.jsonl"
    whole = events.read_bytes()
    first_line = whole.index(b"\n") + 1
    events.write_bytes(whole[: first_line + 10])

    first = lib.read_check_activity(run.check_id, checks_directory=tmp_path)
    events.write_bytes(whole)
    rest = lib.read_check_activity(run.check_id, after=first.cursor, checks_directory=tmp_path)
    nothing = lib.read_check_activity(run.check_id, after=rest.cursor, checks_directory=tmp_path)

    assert [entry.kind for entry in first.entries] == ["request"]
    assert first.cursor == first_line
    assert [entry.kind for entry in rest.entries][-1] == "ended"
    assert len(first.entries) + len(rest.entries) == len(whole.splitlines())
    assert (nothing.entries, nothing.cursor) == ([], len(whole))


@pytest.mark.parametrize("after", [-1, 5, 10**9])
async def test_a_cursor_that_is_not_one_is_refused(tmp_path: Path, after: int) -> None:
    run = await finished_check(tmp_path)

    with pytest.raises(RealityCheckError) as failure:
        lib.read_check_activity(run.check_id, after=after, checks_directory=tmp_path)

    assert failure.value.code == "bad-cursor"


async def test_one_tool_call_reads_in_full_and_an_unknown_one_says_where_to_find_one(tmp_path: Path) -> None:
    run = await lib.check_software(
        "Check the page", checks_directory=tmp_path, intelligence=FakeIntelligence(finishes())
    )
    await run.result()

    call = lib.read_check_activity(run.check_id, tool_call_id="call-1", checks_directory=tmp_path)
    with pytest.raises(RealityCheckError) as failure:
        lib.read_check_activity(run.check_id, tool_call_id="call-9", checks_directory=tmp_path)

    assert [entry.kind for entry in call.entries] == ["tool", "tool-result"]
    assert call.entries[0].data["arguments"] == {"command": "curl http://localhost"}
    assert call.entries[1].data["result"] == "x" * 2000
    assert failure.value.code == "tool-call-not-found"
    assert f"--check-id {run.check_id}" in failure.value.remedy


async def test_a_running_check_whose_process_is_gone_reads_as_crashed(tmp_path: Path) -> None:
    run = await finished_check(tmp_path)
    process = subprocess.Popen([sys.executable, "-c", "pass"])
    process.wait()
    path = run.directory / "check.json"
    record = CheckRecord.model_validate_json(path.read_text(encoding="utf-8"))
    path.write_text(record.model_copy(update={"status": "running", "pid": process.pid}).model_dump_json(), "utf-8")

    assert lib.read_check_activity(run.check_id, checks_directory=tmp_path).state == "crashed"


async def test_the_cli_prints_the_activity_as_json(tmp_path: Path) -> None:
    run = await finished_check(tmp_path)

    whole = runner.invoke(app, ["read-check-activity", "--check-id", run.check_id, "--checks-directory", str(tmp_path)])
    call = runner.invoke(
        app,
        [
            *("read-check-activity", "--check-id", run.check_id, "--checks-directory", str(tmp_path)),
            *("--after", str(json.loads(whole.stdout)["cursor"])),
        ],
    )
    missing = runner.invoke(app, ["read-check-activity", "--check-id", "nope", "--checks-directory", str(tmp_path)])

    assert whole.exit_code == call.exit_code == 0, whole.output + call.output
    assert json.loads(whole.stdout)["state"] == "done"
    assert json.loads(call.stdout)["entries"] == []
    assert missing.exit_code == 1
