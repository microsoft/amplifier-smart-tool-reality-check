"""Drives check_software with a scripted intelligence, so no agent provider or network is needed."""

import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

from fakes import (
    SESSION,
    FakeIntelligence,
    FakeRun,
    Script,
    Unavailable,
    fails,
    finishes,
    waits_for_steering,
    works_forever,
)
import pytest
from typer.testing import CliRunner
import yaml

from reality_check import lib
from reality_check.capabilities.check_software import check
from reality_check.capabilities.check_software.record import process_started
from reality_check.cli import app
from reality_check.intelligence import interface
from reality_check.intelligence.schemas import AgentRequest, AgentResult
from reality_check.schemas import CheckEvent, CheckRecord, CheckTimeoutError, CheckUsage, RealityCheckError

REQUEST = "Check that notes.md is followed and the page shows a button labelled Go"

runner = CliRunner()


async def collect(run: lib.CheckRun) -> list[CheckEvent]:
    return [event async for event in run.events()]


async def started(run: lib.CheckRun) -> None:
    """Wait until the agent runs, so a message from another process has something to land in."""
    async for event in run.events():
        if event.kind == "progress":
            return


@pytest.fixture(autouse=True)
def skills_cache(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> Path:
    cache = tmp_path_factory.mktemp("skills-cache")
    monkeypatch.setattr(check, "SKILLS_CACHE_DIRECTORY", cache)
    return cache


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "notes.md").write_text("Sign in as demo.", encoding="utf-8")
    return tmp_path


async def test_a_check_streams_its_events_and_ends_with_the_agent_s_report(workspace: Path, skills_cache: Path) -> None:
    fake = FakeIntelligence(finishes())

    run = await lib.check_software(REQUEST, target="http://localhost:8000", intelligence=fake)
    events = await collect(run)
    result = await run.result()

    assert [event.kind for event in events] == [
        "started",
        "progress",
        "reasoning",
        "tool",
        "usage",
        "tool",
        "finished",
    ]
    assert events[0].data["directory"] == str(run.directory)
    assert events[2].data == {"reasoning_id": "r1"}
    assert events[3].data["arguments"] == {"command": "curl http://localhost"}
    assert events[5].data["phase"] == "result"
    assert events[5].text == "x" * 2000
    assert "result" not in events[5].data
    assert result.status == "done"
    assert result.report == "# Report\n\nGo: pass"
    assert result.session_id == SESSION
    assert result.agent_provider == "copilot"
    assert events[-1].data == result.model_dump(mode="json")
    assert run.directory.parent == workspace / ".agents" / "reality-check"
    lines = (run.directory / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert [CheckEvent.model_validate_json(line) for line in lines] == events
    assert [event.id for event in events] == list(range(1, len(lines) + 1))
    record = CheckRecord.model_validate_json((run.directory / "check.json").read_text(encoding="utf-8"))
    assert (record.status, record.session_id, record.model) == ("done", SESSION, "gpt-6.1-sol")

    request = fake.runs[0].request
    assert request.workspace is not None
    assert request.workspace.path == workspace
    assert request.resume is None
    assert REQUEST in request.initial_message
    assert "http://localhost:8000" in request.initial_message
    assert str(workspace / "notes.md") in request.initial_message
    assert (run.directory / "evidence").is_dir()
    assert f"Put every piece of evidence in `{run.directory / 'evidence'}`." in request.initial_message
    assert f"saved as `{run.directory / 'report.md'}`" in request.initial_message
    assert request.mcp_servers == {}
    assert check._dtu_command() in request.initial_message
    assert (check.HERE / "report-format.md").read_text(encoding="utf-8") in request.initial_message
    skills = {path.name for directory in request.skill_directories for path in directory.iterdir()}
    assert skills == {
        "reaching-software",
        "using-software",
        "using-computer-use",
        "gathering-evidence",
        "digital-twin-universe",
    }
    dtu_skills = request.skill_directories[-1]
    assert dtu_skills.parent == skills_cache
    dtu_skill = (dtu_skills / "digital-twin-universe" / "SKILL.md").read_text(encoding="utf-8")
    assert yaml.safe_load(dtu_skill.split("---")[1])["name"] == "digital-twin-universe"
    assert not (run.directory / "skills").exists()


async def test_checks_share_one_cached_digital_twin_universe_skill(tmp_path: Path, skills_cache: Path) -> None:
    for _ in range(2):
        run = await lib.check_software(REQUEST, checks_directory=tmp_path, intelligence=FakeIntelligence(finishes()))
        await run.result()

    assert [path.name for path in skills_cache.rglob("*") if path.is_file()] == ["SKILL.md"]


async def test_the_agent_s_final_message_is_the_report_and_is_kept_in_report_md(tmp_path: Path) -> None:
    run = await lib.check_software(
        REQUEST, checks_directory=tmp_path, intelligence=FakeIntelligence(finishes("What I need: a sign-in."))
    )
    events = await collect(run)
    result = await run.result()

    assert events[-1].kind == "finished"
    assert str(run.directory / "report.md") in events[-1].text
    assert result.status == "done"
    assert result.report == "What I need: a sign-in."
    assert (run.directory / "report.md").read_text(encoding="utf-8") == "What I need: a sign-in."
    assert result.next == (
        f'reality-check check-software --resume {run.check_id} --request "<your answer>" --checks-directory {tmp_path}'
    )


async def test_an_empty_final_message_ends_done_without_a_report_md(tmp_path: Path) -> None:
    run = await lib.check_software(REQUEST, checks_directory=tmp_path, intelligence=FakeIntelligence(finishes("")))
    result = await run.result()

    assert result.status == "done"
    assert result.report.startswith("No report: it ended before the agent wrote one.")
    assert not (run.directory / "report.md").exists()


async def test_a_steering_message_from_another_process_is_delivered(tmp_path: Path) -> None:
    fake = FakeIntelligence(waits_for_steering)
    run = await lib.check_software(REQUEST, checks_directory=tmp_path, intelligence=fake)

    lib.steer_check(run.check_id, "Use the second account.", checks_directory=tmp_path)
    events = await collect(run)
    result = await run.result()

    assert fake.runs[0].steered == ["Use the second account."]
    assert [event.text for event in events if event.kind == "steered"] == ["Use the second account."]
    assert result.report == "Did: Use the second account."
    assert not list((run.directory / "steer").iterdir())


async def test_a_cancel_from_another_process_ends_the_check_cancelled_without_an_empty_report(tmp_path: Path) -> None:
    run = await lib.check_software(
        REQUEST, checks_directory=tmp_path, intelligence=FakeIntelligence(works_forever, stopped_text="")
    )
    await started(run)
    running = CheckRecord.model_validate_json((run.directory / "check.json").read_text(encoding="utf-8"))

    lib.cancel_check(run.check_id, checks_directory=tmp_path)
    result = await run.result()
    finished = (await collect(run))[-1]

    assert (running.status, running.session_id) == ("running", SESSION)
    assert result.status == "cancelled"
    assert result.session_id == SESSION
    assert result.report.startswith("No report: it was cancelled before the agent wrote one.")
    assert f"--resume {run.check_id}" in result.report
    assert not (run.directory / "report.md").exists()
    assert finished.kind == "finished"
    assert "there is no report" in finished.text
    assert "report.md" not in finished.text
    for late in (
        lambda: lib.steer_check(run.check_id, "too late", checks_directory=tmp_path),
        lambda: lib.cancel_check(run.check_id, checks_directory=tmp_path),
    ):
        with pytest.raises(RealityCheckError) as failure:
            late()
        assert failure.value.code == "check-not-running"


async def test_resume_continues_the_session_on_the_same_agent_provider(tmp_path: Path) -> None:
    first = await lib.check_software(
        REQUEST, checks_directory=tmp_path, agent_provider="codex", intelligence=FakeIntelligence(finishes())
    )
    await first.result()
    fake = FakeIntelligence(finishes())

    with pytest.raises(RealityCheckError) as other:
        await lib.check_software(
            "Go on.", resume=first.check_id, checks_directory=tmp_path, agent_provider="copilot", intelligence=fake
        )
    second = await lib.check_software("Go on.", resume=first.check_id, checks_directory=tmp_path, intelligence=fake)
    result = await second.result()

    assert other.value.code == "resume-other-provider"
    assert result.agent_provider == "codex"
    request = fake.runs[0].request
    assert request.resume == SESSION
    assert "<request>\nGo on.\n</request>" in request.initial_message
    assert "your final message is the report" in request.initial_message
    assert (check.HERE / "report-format.md").read_text(encoding="utf-8") in request.initial_message
    assert f"Put every piece of evidence in `{second.directory / 'evidence'}`." in request.initial_message
    assert f"before this request is in `{first.directory / 'evidence'}`" in request.initial_message
    assert f"`../{first.check_id}/evidence/01-open-home.png`" in request.initial_message


async def test_a_check_past_its_timeout_fails_with_the_result_so_far(tmp_path: Path) -> None:
    run = await lib.check_software(
        REQUEST, checks_directory=tmp_path, timeout_seconds=1, intelligence=FakeIntelligence(works_forever)
    )

    with pytest.raises(CheckTimeoutError) as failure:
        await run.result()
    events = await collect(run)

    assert failure.value.code == "check-timeout"
    assert failure.value.result.report == "Stopped early."
    assert failure.value.result.session_id == SESSION
    assert events[-1].kind == "failed"
    assert events[-1].data["code"] == "check-timeout"
    assert events[-1].data["result"]["report"] == "Stopped early."
    assert failure.value.result.status == "timed-out"
    assert failure.value.result.timeout_seconds == 1
    record = CheckRecord.model_validate_json((run.directory / "check.json").read_text(encoding="utf-8"))
    assert (record.status, record.session_id, record.timeout_seconds) == ("timed-out", SESSION, 1)


async def test_a_check_near_its_timeout_tells_its_agent_to_report_with_the_time_left(tmp_path: Path) -> None:
    fake = FakeIntelligence(waits_for_steering)
    run = await lib.check_software(REQUEST, checks_directory=tmp_path, timeout_seconds=2, intelligence=fake)

    result = await run.result()
    steered = [event for event in await collect(run) if event.kind == "steered"]

    assert result.status == "done"
    assert fake.runs[0].steered[0].startswith("This check has 1 seconds left before it is stopped.")
    assert steered[0].data["origin"] == "reality-check"


async def test_a_check_without_a_timeout_has_no_deadline(tmp_path: Path) -> None:
    fake = FakeIntelligence(finishes())
    run = await lib.check_software(REQUEST, checks_directory=tmp_path, timeout_seconds=None, intelligence=fake)

    result = await run.result()

    assert result.timeout_seconds is None
    assert fake.runs[0].request.timeout_seconds is None
    record = CheckRecord.model_validate_json((run.directory / "check.json").read_text(encoding="utf-8"))
    assert record.timeout_seconds is None


async def test_a_check_sums_its_usage_the_same_way_for_every_agent_provider(tmp_path: Path) -> None:
    async def script(run: FakeRun) -> AgentResult:
        for _ in range(2):
            run.emit(
                "usage",
                data={
                    "input_tokens": 1000,
                    "fresh_input_tokens": 100,
                    "cache_read_tokens": 850,
                    "cache_write_tokens": 50,
                    "output_tokens": 20,
                    "billing": {"AIU": 1.5},
                },
            )
        return AgentResult(text="# Report", session_id=SESSION)

    run = await lib.check_software(REQUEST, checks_directory=tmp_path, intelligence=FakeIntelligence(script))
    result = await run.result()

    assert result.usage == CheckUsage(
        model_calls=2,
        fresh_input_tokens=200,
        cache_read_tokens=1700,
        cache_write_tokens=100,
        output_tokens=40,
        billing={"AIU": 3.0},
    )
    assert result.elapsed_seconds >= 0
    record = CheckRecord.model_validate_json((run.directory / "check.json").read_text(encoding="utf-8"))
    assert record.usage == result.usage


@pytest.mark.parametrize(("script", "exit_code", "status"), [(finishes(), 0, "done"), (fails, 1, None)])
def test_the_cli_prints_one_json_line_per_event_and_exits_by_how_the_check_ended(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, script: Script, exit_code: int, status: str | None
) -> None:
    monkeypatch.setattr(interface, "resolve_intelligence", lambda *arguments: FakeIntelligence(script))

    result = runner.invoke(
        app, ["check-software", "--request", REQUEST, "--checks-directory", str(tmp_path), "--ask-first", "never"]
    )

    lines = [json.loads(line) for line in result.stdout.splitlines()]
    assert result.exit_code == exit_code
    assert lines[0]["kind"] == "started"
    assert lines[-1]["kind"] == ("finished" if status else "failed")
    if status:
        assert lines[-1]["data"]["status"] == status
    else:
        assert "model unavailable" in result.stderr


class RefusingRun(FakeRun):
    async def steer(self, message: str) -> None:
        raise RealityCheckError("agent-steer-failed", "The steering message was not delivered.", "Send it again.")


class RefusesSteering(FakeIntelligence):
    async def start(self, request: AgentRequest) -> FakeRun:
        run = RefusingRun(request, works_forever, "")
        self.runs.append(run)
        return run


def record_of(run: lib.CheckRun) -> CheckRecord:
    return CheckRecord.model_validate_json((run.directory / "check.json").read_text(encoding="utf-8"))


def without_fake_resolution(monkeypatch: pytest.MonkeyPatch, script: Script | None = None) -> list[FakeIntelligence]:
    """Have the agent provider's own implementation be a fake, so the static model check runs as for a real one."""
    made: list[FakeIntelligence] = []

    def resolve(*arguments: Any) -> FakeIntelligence:
        made.append(FakeIntelligence(script or finishes()))
        return made[-1]

    monkeypatch.setattr(interface, "resolve_intelligence", resolve)
    return made


def dead_pid() -> int:
    process = subprocess.Popen([sys.executable, "-c", "pass"])
    process.wait()
    return process.pid


async def ended_running(tmp_path: Path, pid: int, pid_started: float | None) -> lib.CheckRun:
    """A check that ended, then made to look running in the process `pid`, as one whose process died mid-run."""
    run = await lib.check_software(REQUEST, checks_directory=tmp_path, intelligence=FakeIntelligence(finishes()))
    await run.result()
    record = record_of(run).model_copy(
        update={"status": "running", "ended_at": None, "pid": pid, "pid_started": pid_started}
    )
    (run.directory / "check.json").write_text(record.model_dump_json(), encoding="utf-8")
    return run


async def test_started_carries_the_whole_request_and_check_json_the_process_and_the_last_event(
    tmp_path: Path, workspace: Path
) -> None:
    image = workspace / "shot.png"
    image.write_bytes(b"png")
    fake = FakeIntelligence(finishes())

    run = await lib.check_software(
        REQUEST,
        checks_directory=tmp_path,
        model="any-model",
        reasoning_effort="high",
        images=[image],
        intelligence=fake,
    )
    running = record_of(run)
    events = await collect(run)
    ended = record_of(run)

    started = events[0].data
    assert started["request"] == REQUEST
    assert (started["model"], started["reasoning_effort"], started["origin"]) == ("any-model", "high", "unknown")
    assert started["images"] == [str(run.directory / "images" / "shot.png")]
    assert (started["pid"], started["detached"], started["implementation"]) == (os.getpid(), False, "fake")
    assert started["agent_request"]["initial_message"] == fake.runs[0].request.initial_message
    assert started["agent_request"]["session_directory"] == str(run.directory / "session")
    assert started["files"]["events"]["path"] == str(run.directory / "events.jsonl")
    assert started["files"]["report"]["path"] == str(run.directory / "report.md")
    assert "process_log" not in started["files"]
    assert (
        f"`reality-check read-check-activity --check-id {run.check_id} --after-event <N-1> --before-event <N+1> "
        f"--no-truncate --checks-directory {tmp_path}`" in started["files"]["events"]["use"]
    )
    assert (running.pid, running.origin) == (os.getpid(), "unknown")
    assert running.pid_started == process_started(os.getpid())
    assert running.last_event is not None
    assert ended.last_event == events[-1].time
    assert events[-1].time > running.last_event


async def test_images_are_copied_into_the_check_and_shown_to_the_agent(tmp_path: Path, workspace: Path) -> None:
    (workspace / "a").mkdir()
    for path in (workspace / "shot.png", workspace / "a" / "shot.png"):
        path.write_bytes(b"png")
    fake = FakeIntelligence(finishes())

    run = await lib.check_software(
        REQUEST, checks_directory=tmp_path, images=[Path("shot.png"), Path("a/shot.png")], intelligence=fake
    )
    await run.result()

    copied = [run.directory / "images" / "shot.png", run.directory / "images" / "shot-2.png"]
    assert fake.runs[0].request.images == copied
    assert record_of(run).images == copied
    assert all(path.read_bytes() == b"png" for path in copied)


@pytest.mark.parametrize(("name", "code"), [("missing.png", "image-not-found"), ("notes.md", "image-not-supported")])
async def test_an_image_that_is_missing_or_not_an_image_fails_before_the_check(
    tmp_path: Path, workspace: Path, name: str, code: str
) -> None:
    with pytest.raises(RealityCheckError) as failure:
        await lib.check_software(
            REQUEST,
            checks_directory=tmp_path / "checks",
            images=[Path(name)],
            intelligence=FakeIntelligence(finishes()),
        )

    assert failure.value.code == code
    assert not (tmp_path / "checks").exists()


@pytest.mark.parametrize(
    ("arguments", "code"),
    [
        ({"model": "gemini-4-argon"}, "model-not-allowed"),
        ({"model": "auto", "reasoning_effort": "low"}, "bad-reasoning-effort"),
        ({"reasoning_effort": "ultra"}, "bad-reasoning-effort"),
        ({"model": "auto", "images": [Path("shot.png")]}, "model-without-vision"),
    ],
)
async def test_a_model_or_effort_reality_check_does_not_run_fails_before_the_check(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, workspace: Path, arguments: dict[str, Any], code: str
) -> None:
    (workspace / "shot.png").write_bytes(b"png")
    without_fake_resolution(monkeypatch)

    with pytest.raises(RealityCheckError) as failure:
        await lib.check_software(REQUEST, checks_directory=tmp_path / "checks", agent_provider="copilot", **arguments)

    assert failure.value.code == code
    assert not (tmp_path / "checks").exists()
    if code == "model-not-allowed":
        assert "gpt-6.1-sol" in failure.value.remedy
        assert "list-intelligence-models" in failure.value.remedy


async def test_a_model_that_takes_no_effort_is_sent_none_and_the_default_model_high(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    made = without_fake_resolution(monkeypatch)

    auto = await lib.check_software(REQUEST, checks_directory=tmp_path, agent_provider="copilot", model="auto")
    default = await lib.check_software(REQUEST, checks_directory=tmp_path, agent_provider="copilot")
    await auto.result()
    await default.result()

    assert [fake.runs[0].request.reasoning_effort for fake in made] == [None, "high"]
    assert (record_of(auto).reasoning_effort, record_of(default).reasoning_effort) == (None, "high")


async def test_an_injected_intelligence_runs_any_model(tmp_path: Path) -> None:
    run = await lib.check_software(
        REQUEST, checks_directory=tmp_path, model="gemini-4-argon", intelligence=FakeIntelligence(finishes())
    )

    assert (await run.result()).status == "done"


async def test_a_failure_to_start_the_agent_ends_the_check_failed_with_its_code_and_remedy(tmp_path: Path) -> None:
    run = await lib.check_software(REQUEST, checks_directory=tmp_path, intelligence=Unavailable(finishes()))

    with pytest.raises(RealityCheckError) as failure:
        await run.result()
    events = await collect(run)

    assert failure.value.code == "model-not-available"
    assert (events[-1].kind, events[-1].data["code"], events[-1].data["remedy"]) == (
        "failed",
        "model-not-available",
        "Pick another.",
    )
    assert record_of(run).status == "failed"


async def test_resume_copies_the_session_into_the_new_check_and_leaves_the_old_one_alone(tmp_path: Path) -> None:
    first = await lib.check_software(REQUEST, checks_directory=tmp_path, intelligence=FakeIntelligence(finishes()))
    await first.result()
    state = first.directory / "session" / "session-state" / SESSION
    state.mkdir(parents=True)
    (state / "events.jsonl").write_text("{}\n", encoding="utf-8")
    (state / "inuse.lock").write_text("", encoding="utf-8")
    fake = FakeIntelligence(finishes())

    second = await lib.check_software("Go on.", resume=first.check_id, checks_directory=tmp_path, intelligence=fake)
    await second.result()

    copy = second.directory / "session" / "session-state" / SESSION
    assert fake.runs[0].request.session_directory == second.directory / "session"
    assert (copy / "events.jsonl").read_text(encoding="utf-8") == "{}\n"
    assert not (copy / "inuse.lock").exists()
    assert sorted(path.name for path in state.iterdir()) == ["events.jsonl", "inuse.lock"]


async def test_resume_of_a_check_that_kept_no_session_leaves_it_to_the_agent_provider(tmp_path: Path) -> None:
    first = await lib.check_software(REQUEST, checks_directory=tmp_path, intelligence=FakeIntelligence(finishes()))
    await first.result()
    fake = FakeIntelligence(finishes())

    second = await lib.check_software("Go on.", resume=first.check_id, checks_directory=tmp_path, intelligence=fake)
    await second.result()

    assert fake.runs[0].request.session_directory is None
    assert not (second.directory / "session").exists()


async def test_steering_carries_who_sent_it(tmp_path: Path) -> None:
    run = await lib.check_software(
        REQUEST, checks_directory=tmp_path, origin="app", intelligence=FakeIntelligence(waits_for_steering)
    )
    other = await lib.check_software(
        REQUEST, checks_directory=tmp_path, intelligence=FakeIntelligence(waits_for_steering)
    )

    await run.steer("Use the second account.")
    lib.steer_check(other.check_id, "Skip settings.", checks_directory=tmp_path, origin="claude-code:abc")
    steered = [event for event in await collect(run) if event.kind == "steered"]
    from_file = [event for event in await collect(other) if event.kind == "steered"]

    assert record_of(run).origin == "app"
    assert [event.data["origin"] for event in steered] == ["app"]
    assert [(event.text, event.data["origin"]) for event in from_file] == [("Skip settings.", "claude-code:abc")]


async def test_a_steering_message_that_is_not_delivered_is_steered_with_its_error(tmp_path: Path) -> None:
    run = await lib.check_software(REQUEST, checks_directory=tmp_path, intelligence=RefusesSteering(works_forever))
    await started(run)

    lib.steer_check(run.check_id, "Skip settings.", checks_directory=tmp_path, origin="app")
    async for event in run.events():
        if event.kind == "steered":
            break
    await run.cancel()

    assert event.text == "Skip settings."
    assert event.data["code"] == "agent-steer-failed"
    assert event.data["origin"] == "app"
    assert "not delivered" in event.data["error"]


@pytest.mark.parametrize("reused", [False, True])
async def test_a_running_check_whose_process_is_gone_has_crashed_and_refuses_steering_and_cancel(
    tmp_path: Path, reused: bool
) -> None:
    # A live process with another start time is a later process given the dead one's pid.
    pid, started_at = (os.getpid(), (process_started(os.getpid()) or 0) - 1000) if reused else (dead_pid(), 1.0)
    run = await ended_running(tmp_path, pid, started_at)
    before = sorted(path.name for path in run.directory.rglob("*"))

    for late in (
        lambda: lib.steer_check(run.check_id, "too late", checks_directory=tmp_path),
        lambda: lib.cancel_check(run.check_id, checks_directory=tmp_path),
    ):
        with pytest.raises(RealityCheckError) as failure:
            late()
        assert failure.value.code == "check-crashed"
        assert f"process {pid}" in failure.value.message
        assert f"--resume {run.check_id}" in failure.value.remedy
    assert sorted(path.name for path in run.directory.rglob("*")) == before


async def test_a_crashed_check_resumes_and_a_live_one_refuses_a_second_process(tmp_path: Path) -> None:
    crashed = await ended_running(tmp_path, dead_pid(), 1.0)
    live = await ended_running(tmp_path, os.getpid(), process_started(os.getpid()))
    fake = FakeIntelligence(finishes())

    resumed = await lib.check_software("Go on.", resume=crashed.check_id, checks_directory=tmp_path, intelligence=fake)
    with pytest.raises(RealityCheckError) as running:
        await lib.check_software("Go on.", resume=live.check_id, checks_directory=tmp_path, intelligence=fake)

    assert (await resumed.result()).status == "done"
    assert fake.runs[0].request.resume == SESSION
    assert running.value.code == "check-running"


async def test_detach_with_an_intelligence_is_refused(tmp_path: Path) -> None:
    with pytest.raises(RealityCheckError) as failure:
        await lib.check_software(
            REQUEST, checks_directory=tmp_path, detach=True, intelligence=FakeIntelligence(finishes())
        )

    assert failure.value.code == "detach-with-intelligence"


def test_the_cli_passes_images_and_origin_and_prints_tool_lines_without_their_full_content(
    tmp_path: Path, workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    made = without_fake_resolution(monkeypatch)
    for name in ("one.png", "two.png"):
        (workspace / name).write_bytes(b"png")

    result = runner.invoke(
        app,
        [
            *("check-software", "--request", REQUEST, "--checks-directory", str(tmp_path / "checks")),
            *("--image", "one.png", "--image", "two.png", "--origin", "app"),
        ],
    )

    lines = [json.loads(line) for line in result.stdout.splitlines()]
    assert result.exit_code == 0, result.output
    assert [path.name for path in made[0].runs[0].request.images] == ["one.png", "two.png"]
    assert lines[0]["data"]["origin"] == "app"
    tools = [line for line in lines if line["kind"] == "tool"]
    assert tools
    assert all("result" not in line["data"] and "arguments" not in line["data"] for line in tools)


def test_the_cli_prints_each_event_short_with_its_id_and_leaves_out_usage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(interface, "resolve_intelligence", lambda *arguments: FakeIntelligence(finishes()))

    result = runner.invoke(app, ["check-software", "--request", REQUEST, "--checks-directory", str(tmp_path)])

    lines = [json.loads(line) for line in result.stdout.splitlines()]
    assert result.exit_code == 0, result.output
    assert [line["kind"] for line in lines] == ["started", "progress", "reasoning", "tool", "tool", "finished"]
    assert [line["id"] for line in lines] == [1, 2, 3, 4, 6, 7]
    assert "initial_message" not in lines[0]["data"]["agent_request"]
    assert lines[4]["text"] == f"{'x' * 500}...[cut at 500 of 2,000 chars; full: line 6 of events.jsonl]"
    assert max(len(text) for line in lines for text in strings(line)) <= len(lines[4]["text"])


def strings(value: Any) -> list[str]:
    """Every string in a JSON value, however deep."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for item in value.values() for text in strings(item)]
    if isinstance(value, list):
        return [text for item in value for text in strings(item)]
    return []
