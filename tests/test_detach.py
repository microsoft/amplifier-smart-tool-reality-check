"""Runs detached checks in processes of their own, with the agent faked, and follows them through their files."""

import asyncio
from collections.abc import Callable
import json
import os
from pathlib import Path
import sys

import detached_agent
import psutil
import pytest
from typer.testing import CliRunner

from reality_check import lib
from reality_check.capabilities.check_software import check
from reality_check.capabilities.check_software.record import read_atomically
from reality_check.cli import app
from reality_check.schemas import CheckRecord, RealityCheckError

# A detached check starts a Python process of its own, which takes a while to import the library.
DETACHED_TIMEOUT_SECONDS = 30

runner = CliRunner()


@pytest.fixture(autouse=True)
def working_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(check, "POLL_SECONDS", 0.01)
    return tmp_path


@pytest.fixture
def detached(monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory) -> Callable[[str], None]:
    """Have detached checks fake their agent with the fake from fakes.py of that name."""
    cache = tmp_path_factory.mktemp("skills-cache")

    def use(name: str) -> None:
        monkeypatch.setattr(check, "BACKGROUND_COMMAND", detached_agent.command(name, cache))

    return use


def record_of(run: lib.CheckRun) -> CheckRecord:
    # Written by another process, which Windows refuses a read of in the moment of replacing it.
    return CheckRecord.model_validate_json(read_atomically(run.directory / "check.json"))


async def test_a_detached_check_runs_in_its_own_process_and_its_handle_follows_it(
    detached: Callable[[str], None],
) -> None:
    detached("prints")

    run = await lib.check_software("Check the page", origin="app", detach=True)
    record = record_of(run)
    await run.steer("Use the second account.")
    result = await asyncio.wait_for(run.result(), DETACHED_TIMEOUT_SECONDS)
    events = [event async for event in run.events()]

    assert isinstance(run, check.DetachedCheckRun)
    assert record.pid != os.getpid()
    assert (record.detached, record.origin) == (True, "app")
    assert (result.status, result.report) == ("done", "Did: Use the second account.")
    assert [event.kind for event in events] == ["started", "progress", "steered", "finished"]
    assert events[2].data["origin"] == "app"
    assert result.next == f'reality-check check-software --resume {run.check_id} --request "<your answer>"'
    log = (run.directory / "process.log").read_text(encoding="utf-8")
    assert "printed by the agent" in log
    assert "warned by the agent" in log


async def test_a_detached_check_outlives_its_handle_and_stops_when_cancelled(
    detached: Callable[[str], None],
) -> None:
    detached("works-forever")
    run = await lib.check_software("Check the page", detach=True)
    record = record_of(run)
    check_id = run.check_id
    del run

    if sys.platform != "win32":
        assert os.getpgid(record.pid or 0) != os.getpgrp()
    await asyncio.to_thread(lib.cancel_check, check_id)
    again = check.DetachedCheckRun(check_id, Path(".agents/reality-check").resolve() / check_id, "unknown", "")
    result = await asyncio.wait_for(again.result(), DETACHED_TIMEOUT_SECONDS)

    assert result.status == "cancelled"


async def test_a_detached_handle_cancels_its_check(detached: Callable[[str], None]) -> None:
    detached("works-forever")
    run = await lib.check_software("Check the page", detach=True)

    await asyncio.wait_for(run.cancel(), DETACHED_TIMEOUT_SECONDS)

    assert (await run.result()).status == "cancelled"


@pytest.mark.parametrize(
    ("name", "code"), [("not-configured", "gh-not-signed-in"), ("unavailable", "model-not-available")]
)
async def test_a_detached_check_that_cannot_start_raises_what_stopped_it(
    detached: Callable[[str], None], name: str, code: str
) -> None:
    detached(name)

    with pytest.raises(RealityCheckError) as failure:
        await lib.check_software("Check the page", detach=True)

    assert failure.value.code == code


async def test_a_killed_detached_check_has_crashed_and_names_its_process_log(detached: Callable[[str], None]) -> None:
    detached("works-forever")
    run = await lib.check_software("Check the page", detach=True)
    pid = record_of(run).pid
    assert pid is not None

    psutil.Process(pid).kill()
    with pytest.raises(RealityCheckError) as crashed:
        await asyncio.wait_for(run.result(), DETACHED_TIMEOUT_SECONDS)
    with pytest.raises(RealityCheckError) as refused:
        lib.steer_check(run.check_id, "Go on.")

    assert crashed.value.code == refused.value.code == "check-crashed"
    assert str(run.directory / "process.log") in crashed.value.remedy
    assert f"--resume {run.check_id}" in crashed.value.remedy


def test_the_cli_detached_prints_the_started_event_and_exits_0_or_1_with_why_it_did_not_start(
    detached: Callable[[str], None], working_directory: Path
) -> None:
    detached("finishes")
    started = runner.invoke(app, ["check-software", "--request", "Check the page", "--detach", "--origin", "app"])
    detached("unavailable")
    refused = runner.invoke(app, ["check-software", "--request", "Check the page", "--detach"])

    assert started.exit_code == 0, started.output
    [line] = [json.loads(line) for line in started.stdout.splitlines()]
    assert (line["kind"], line["data"]["origin"], line["data"]["detached"]) == ("started", "app", True)
    # main() prints a RealityCheckError to stderr and exits 1; the runner calls the app beneath it.
    assert refused.exit_code == 1
    assert isinstance(refused.exception, RealityCheckError)
    assert refused.exception.code == "model-not-available"
