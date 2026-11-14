"""A creation key recovers the same check without another agent run."""

import asyncio
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

from fakes import FakeIntelligence, NotConfigured, finishes
import pytest

from reality_check import lib
from reality_check.capabilities.check_software import check
from reality_check.schemas import RealityCheckError


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(check, "SKILLS_CACHE_DIRECTORY", tmp_path / "skills")
    monkeypatch.setattr(check, "POLL_SECONDS", 0.01)


async def test_concurrent_retries_start_one_check(tmp_path: Path) -> None:
    intelligence = FakeIntelligence(finishes())
    runs = await asyncio.gather(
        *(lib.check_software("Check export", request_key="export-1", intelligence=intelligence) for _ in range(6))
    )
    results = await asyncio.gather(*(run.result() for run in runs))

    assert len({run.check_id for run in runs}) == 1
    assert len(intelligence.runs) == 1
    assert all(result == results[0] for result in results)
    assert len(list((tmp_path / ".agents/reality-check").glob("*/check.json"))) == 1


async def test_a_lost_reply_is_recovered_in_a_new_process_without_provider_access(tmp_path: Path) -> None:
    run = await lib.check_software("Check export", request_key="export-1", intelligence=FakeIntelligence(finishes()))
    expected = await run.result()
    original = {path.name: path.read_bytes() for path in run.directory.iterdir() if path.is_file()}
    completed = await asyncio.to_thread(
        subprocess.run,
        [
            sys.executable,
            "-c",
            (
                "import asyncio; from reality_check import lib; "
                "run = asyncio.run(lib.check_software('Check export', request_key='export-1')); "
                "print(asyncio.run(run.result()).model_dump_json())"
            ),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )

    assert json.loads(completed.stdout) == expected.model_dump(mode="json")
    assert {path.name: path.read_bytes() for path in run.directory.iterdir() if path.is_file()} == original


@pytest.mark.parametrize(
    "changed",
    [
        {"request": "Check delete"},
        {"target": "other"},
        {"origin": "other"},
        {"model": "other"},
        {"timeout_seconds": 5},
        {"detach": True},
    ],
)
async def test_a_key_cannot_be_reused_for_changed_input(changed: dict[str, Any]) -> None:
    run = await lib.check_software("Check export", request_key="export-1", intelligence=FakeIntelligence(finishes()))
    await run.result()
    arguments: dict[str, Any] = {"request": "Check export", "request_key": "export-1", **changed}

    with pytest.raises(RealityCheckError) as refused:
        await lib.check_software(**arguments)

    assert refused.value.code == "request-key-conflict"
    assert lib.read_check(run.check_id).state == "done"


async def test_a_new_key_and_resume_create_separate_checks() -> None:
    intelligence = FakeIntelligence(finishes())
    first = await lib.check_software("Check export", request_key="export-1", intelligence=intelligence)
    await first.result()
    second = await lib.check_software("Check export", request_key="export-2", intelligence=intelligence)
    await second.result()
    continued = await lib.check_software(
        "Check again", resume=first.check_id, request_key="followup-1", intelligence=intelligence
    )
    await continued.result()
    recovered = await lib.check_software(
        "Check again", resume=first.check_id, request_key="followup-1", intelligence=NotConfigured(finishes())
    )

    assert len({first.check_id, second.check_id, continued.check_id}) == 3
    assert recovered.check_id == continued.check_id
    assert lib.read_check(continued.check_id).check.resume == first.check_id
    assert len(intelligence.runs) == 3


async def test_an_interrupted_start_is_not_run_again(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def interrupted(*args: object) -> None:
        raise RuntimeError("interrupted after the record was saved")

    intelligence = FakeIntelligence(finishes())
    monkeypatch.setattr(check, "prepare_browser", interrupted)
    with pytest.raises(RuntimeError, match="interrupted"):
        await lib.check_software("Check export", request_key="export-1", intelligence=intelligence)
    with pytest.raises(RealityCheckError) as unknown:
        await lib.check_software("Check export", request_key="export-1", intelligence=intelligence)

    assert unknown.value.code == "check-start-unknown"
    assert len(list((tmp_path / ".agents/reality-check").glob("*/check.json"))) == 1
    assert intelligence.runs == []


@pytest.mark.parametrize("key", ["", "   ", "x" * 257])
async def test_invalid_keys_do_not_start_checks(key: str) -> None:
    intelligence = FakeIntelligence(finishes())
    with pytest.raises(RealityCheckError) as refused:
        await lib.check_software("Check export", request_key=key, intelligence=intelligence)
    assert refused.value.code == "bad-request-key"
    assert intelligence.runs == []
