"""Reads a check's events from its files, as another process does, while it runs and after it ended."""

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
from reality_check.schemas import CheckEvent, CheckRecord, RealityCheckError, brief

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


async def finishes_check(tmp_path: Path) -> lib.CheckRun:
    run = await lib.check_software(
        "Check the page", checks_directory=tmp_path, intelligence=FakeIntelligence(finishes())
    )
    await run.result()
    return run


async def test_events_are_short_with_their_ids_and_without_usage(tmp_path: Path) -> None:
    run = await finishes_check(tmp_path)

    activity = lib.read_check_activity(run.check_id, checks_directory=tmp_path)

    assert [(event.id, event.kind) for event in activity.events] == [
        (1, "started"),
        (2, "progress"),
        (3, "reasoning"),
        (4, "tool"),
        (6, "tool"),
        (7, "finished"),
    ]
    started, said, reasoning, call, result, finished = activity.events
    assert (started.data["request"], started.data["origin"]) == ("Check the page", "unknown")
    assert "initial_message" not in started.data["agent_request"]
    assert started.data["model"] == "gpt-6.1-sol"
    assert said.text == "Opening the page."
    assert reasoning.text == "The page is the target."
    assert call.data == {"tool_call_id": "call-1", "tool_name": "bash", "phase": "call"}
    assert result.data == {"tool_call_id": "call-1", "success": True, "phase": "result"}
    assert result.text == f"{'x' * 500}...[cut at 500 of 2,000 chars; full: line 6 of events.jsonl]"
    assert finished.data["status"] == "done"
    assert activity.state == "done"
    assert activity.process_log is None


async def test_untruncated_events_are_as_events_jsonl_keeps_them_without_usage(tmp_path: Path) -> None:
    run = await finishes_check(tmp_path)
    lines = (run.directory / "events.jsonl").read_text(encoding="utf-8").splitlines()

    activity = lib.read_check_activity(run.check_id, truncate=False, checks_directory=tmp_path)

    kept = [CheckEvent.model_validate_json(line) for line in lines]
    assert activity.events == [event for event in kept if event.kind != "usage"]
    assert activity.events[3].data["arguments"] == {"command": "curl http://localhost"}
    assert activity.events[4].text == "x" * 2000


@pytest.mark.parametrize(
    ("after_event", "before_event", "tail_events", "ids"),
    [
        (None, None, None, [1, 2, 3, 4, 6, 7]),
        (3, None, None, [4, 6, 7]),
        (None, 4, None, [1, 2, 3]),
        (2, 6, None, [3, 4]),
        (None, None, 2, [6, 7]),
        (None, 6, 1, [4]),
        (None, None, 10, [1, 2, 3, 4, 6, 7]),
        (None, None, 0, []),
        (7, None, None, []),
    ],
)
async def test_events_are_picked_by_id_then_the_last_few(
    tmp_path: Path, after_event: int | None, before_event: int | None, tail_events: int | None, ids: list[int]
) -> None:
    run = await finishes_check(tmp_path)

    activity = lib.read_check_activity(
        run.check_id,
        after_event=after_event,
        before_event=before_event,
        tail_events=tail_events,
        checks_directory=tmp_path,
    )

    assert [event.id for event in activity.events] == ids
    assert activity.state == "done"


@pytest.mark.parametrize(
    ("after_event", "before_event", "tail_events", "code"),
    [
        (8, None, None, "event-not-found"),
        (-1, None, None, "bad-event-selection"),
        (None, -1, None, "bad-event-selection"),
        (None, None, -1, "bad-event-selection"),
    ],
)
async def test_an_event_past_the_last_or_a_negative_selection_is_refused(
    tmp_path: Path, after_event: int | None, before_event: int | None, tail_events: int | None, code: str
) -> None:
    run = await finishes_check(tmp_path)

    with pytest.raises(RealityCheckError) as failure:
        lib.read_check_activity(
            run.check_id,
            after_event=after_event,
            before_event=before_event,
            tail_events=tail_events,
            checks_directory=tmp_path,
        )

    assert failure.value.code == code


async def test_steering_and_a_failure_are_events_with_who_and_how(tmp_path: Path) -> None:
    steered = await finished_check(tmp_path)
    failed = await lib.check_software("Check", checks_directory=tmp_path, intelligence=Unavailable(finishes()))
    with pytest.raises(RealityCheckError):
        await failed.result()

    steering = lib.read_check_activity(steered.check_id, checks_directory=tmp_path).events
    failure = lib.read_check_activity(failed.check_id, checks_directory=tmp_path)

    [event] = [event for event in steering if event.kind == "steered"]
    assert (event.text, event.data) == ("Use the second account.", {"steering": "mid-turn", "origin": "app"})
    assert failure.state == "failed"
    assert (failure.events[-1].kind, failure.events[-1].data["code"]) == ("failed", "model-not-available")


def test_the_short_form_cuts_every_long_string_but_the_report_and_marks_its_line() -> None:
    long = "y" * 3319
    started = CheckEvent(
        id=1,
        check_id="c",
        kind="started",
        data={"request": long, "agent_request": {"initial_message": "prompt", "model": "m"}},
    )
    nested = CheckEvent(id=64, check_id="c", kind="steered", text=long, data={"a": [{"b": long}], "n": 3})
    finished = CheckEvent(id=9, check_id="c", kind="finished", data={"report": long, "next": long})
    marker = f"{'y' * 500}...[cut at 500 of 3,319 chars; full: line 64 of events.jsonl]"

    short_started = brief(started)
    short_nested = brief(nested)
    short_finished = brief(finished)

    assert brief(CheckEvent(id=2, check_id="c", kind="usage", data={"model": "m"})) is None
    assert brief(CheckEvent(id=2, check_id="c", kind="usage"), truncate=False) is None
    assert short_started is not None
    assert short_started.data["agent_request"] == {"model": "m"}
    assert short_started.data["request"].endswith("full: line 1 of events.jsonl]")
    assert short_nested is not None
    assert (short_nested.text, short_nested.data) == (marker, {"a": [{"b": marker}], "n": 3})
    assert short_finished is not None
    assert short_finished.data["report"] == long
    assert short_finished.data["next"].endswith("full: line 9 of events.jsonl]")
    assert brief(nested, truncate=False) == nested


async def test_a_running_check_whose_process_is_gone_reads_as_crashed(tmp_path: Path) -> None:
    run = await finished_check(tmp_path)
    process = subprocess.Popen([sys.executable, "-c", "pass"])
    process.wait()
    path = run.directory / "check.json"
    record = CheckRecord.model_validate_json(path.read_text(encoding="utf-8"))
    path.write_text(record.model_copy(update={"status": "running", "pid": process.pid}).model_dump_json(), "utf-8")

    assert lib.read_check_activity(run.check_id, checks_directory=tmp_path).state == "crashed"


async def test_the_cli_prints_the_activity_as_compact_json(tmp_path: Path) -> None:
    run = await finishes_check(tmp_path)
    read = ("read-check-activity", "--check-id", run.check_id, "--checks-directory", str(tmp_path))

    whole = runner.invoke(app, [*read])
    one = runner.invoke(app, [*read, "--after-event", "5", "--before-event", "7", "--no-truncate"])
    last = runner.invoke(app, [*read, "--tail-events", "1"])
    missing = runner.invoke(app, ["read-check-activity", "--check-id", "nope", "--checks-directory", str(tmp_path)])

    assert whole.exit_code == one.exit_code == last.exit_code == 0, whole.output + one.output + last.output
    assert whole.stdout.count("\n") == 1
    assert json.loads(whole.stdout)["state"] == "done"
    [event] = json.loads(one.stdout)["events"]
    assert (event["id"], event["text"]) == (6, "x" * 2000)
    assert [event["kind"] for event in json.loads(last.stdout)["events"]] == ["finished"]
    assert missing.exit_code == 1
