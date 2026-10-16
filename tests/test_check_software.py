"""Drives check_software with a scripted intelligence, so no agent provider or network is needed."""

import asyncio
from collections.abc import AsyncIterator, Callable, Coroutine
import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner
import yaml

from reality_check import lib
from reality_check.capabilities.check_software import check
from reality_check.cli import app
from reality_check.intelligence import interface
from reality_check.intelligence.schemas import AgentEvent, AgentEventKind, AgentRequest, AgentResult, Steering
from reality_check.schemas import CheckEvent, CheckRecord, CheckTimeoutError, RealityCheckError

SESSION = "fake-session"
REQUEST = "Check that notes.md is followed and the page shows a button labelled Go"

runner = CliRunner()


class FakeRun:
    """An agent run whose work is a script, which a cancel interrupts the way a drained session ends."""

    def __init__(self, request: AgentRequest, script: "Script", stopped_text: str) -> None:
        self.request = request
        self.session_id: str | None = SESSION
        self._stopped_text = stopped_text
        self.steered: list[str] = []
        self.steer_arrived = asyncio.Event()
        self._events: list[AgentEvent] = []
        self._appended = asyncio.Event()
        self._cancelled = asyncio.Event()
        self._task = asyncio.create_task(self._drive(script))

    def emit(self, kind: AgentEventKind, text: str = "") -> None:
        self._events.append(AgentEvent(kind=kind, text=text))
        self._appended.set()
        self._appended = asyncio.Event()

    async def events(self) -> AsyncIterator[AgentEvent]:
        index = 0
        while True:
            appended = self._appended
            while index < len(self._events):
                index += 1
                yield self._events[index - 1]
                if self._events[index - 1].kind == "terminal":
                    return
            await appended.wait()

    async def steer(self, message: str) -> None:
        self.steered.append(message)
        self.steer_arrived.set()

    async def cancel(self) -> None:
        self._cancelled.set()
        await asyncio.wait([self._task])

    async def result(self) -> AgentResult:
        return await asyncio.shield(self._task)

    async def _drive(self, script: "Script") -> AgentResult:
        work = asyncio.create_task(script(self))
        cancelled = asyncio.create_task(self._cancelled.wait())
        await asyncio.wait([work, cancelled], return_when=asyncio.FIRST_COMPLETED)
        cancelled.cancel()
        if work.done():
            result = work.result()
        else:
            work.cancel()
            result = AgentResult(text=self._stopped_text, cancelled=True, session_id=SESSION)
        self.emit("terminal", result.text)
        return result


Script = Callable[[FakeRun], Coroutine[Any, Any, AgentResult]]


class FakeIntelligence:
    def __init__(self, script: Script, stopped_text: str = "Stopped early.") -> None:
        self.implementation = "fake"
        self._stopped_text = stopped_text
        self.steering: Steering = "mid-turn"
        self.runs: list[FakeRun] = []
        self._script = script

    def preflight(self) -> None:
        pass

    async def start(self, request: AgentRequest) -> FakeRun:
        run = FakeRun(request, self._script, self._stopped_text)
        self.runs.append(run)
        return run


def finishes(text: str = "# Report\n\nGo: pass") -> Script:
    async def script(run: FakeRun) -> AgentResult:
        run.emit("message", "Opening the page.")
        run.emit("tool_call", "bash curl http://localhost")
        run.emit("usage")
        run.emit("tool_result", "x" * 2000)
        return AgentResult(text=text, session_id=SESSION)

    return script


async def waits_for_steering(run: FakeRun) -> AgentResult:
    await run.steer_arrived.wait()
    return AgentResult(text=f"Did: {run.steered[0]}", session_id=SESSION)


async def works_forever(run: FakeRun) -> AgentResult:
    run.emit("message", "Working.")
    await asyncio.Event().wait()
    raise AssertionError("unreachable")


async def fails(run: FakeRun) -> AgentResult:
    return AgentResult(error="SessionError: model unavailable", session_id=SESSION)


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

    assert [event.kind for event in events] == ["started", "progress", "tool", "usage", "tool", "finished"]
    assert events[0].data["directory"] == str(run.directory)
    assert events[4].data["phase"] == "result"
    assert len(events[4].text) < 600
    assert result.status == "done"
    assert result.report == "# Report\n\nGo: pass"
    assert result.session_id == SESSION
    assert result.agent_provider == "copilot"
    assert events[-1].data == result.model_dump(mode="json")
    assert run.directory.parent == workspace / ".agents" / "reality-check"
    lines = (run.directory / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert [CheckEvent.model_validate_json(line) for line in lines] == events
    record = CheckRecord.model_validate_json((run.directory / "check.json").read_text(encoding="utf-8"))
    assert (record.status, record.session_id, record.model) == ("done", SESSION, "gpt-6.1-sol")

    request = fake.runs[0].request
    assert request.workspace is not None
    assert request.workspace.path == workspace
    assert request.resume is None
    assert REQUEST in request.prompt
    assert "http://localhost:8000" in request.prompt
    assert str(workspace / "notes.md") in request.prompt
    assert not (run.directory / "evidence").exists()
    assert request.mcp_servers == {}
    assert check._dtu_command() in request.prompt
    skills = {path.name for directory in request.skill_directories for path in directory.iterdir()}
    assert skills == {"reaching-software", "using-software", "gathering-evidence", "digital-twin-universe"}
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
    assert "<request>\nGo on.\n</request>" in request.prompt
    assert "your final message is the report" in request.prompt


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
    record = CheckRecord.model_validate_json((run.directory / "check.json").read_text(encoding="utf-8"))
    assert (record.status, record.session_id) == ("failed", SESSION)


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
