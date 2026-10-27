"""Finds every check on the machine through the projects starting a check records, and reads one with its evidence."""

import json
import os
from pathlib import Path
import subprocess
import sys
import time

from fakes import FakeIntelligence, finishes
import pytest
from typer.testing import CliRunner

from reality_check import lib
from reality_check.capabilities.check_software import check, checks, registry
from reality_check.cli import app
from reality_check.schemas import CheckRecord, RealityCheckError

runner = CliRunner()


@pytest.fixture(autouse=True)
def skills_cache(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(check, "SKILLS_CACHE_DIRECTORY", tmp_path_factory.mktemp("skills-cache"))
    monkeypatch.setattr(check, "POLL_SECONDS", 0.01)


async def ended_check(
    checks_directory: Path, request: str = "Check the page", resume: str | None = None
) -> lib.CheckRun:
    run = await lib.check_software(
        request, resume=resume, checks_directory=checks_directory, intelligence=FakeIntelligence(finishes())
    )
    await run.result()
    return run


async def test_starting_checks_registers_their_project_once_with_absolute_paths(
    tmp_path: Path, own_registry: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    await ended_check(Path(".agents/reality-check"))
    await ended_check(Path(".agents/reality-check"))

    projects = json.loads(own_registry.read_text(encoding="utf-8"))["projects"]

    assert projects == [{"root": str(tmp_path), "checks_directory": str(tmp_path / ".agents" / "reality-check")}]


def test_projects_registered_at_once_from_many_processes_are_all_kept(tmp_path: Path, own_registry: Path) -> None:
    script = (
        "import sys\nfrom pathlib import Path\nfrom reality_check.capabilities.check_software import registry\n"
        "registry.REGISTRY = Path(sys.argv[1])\n"
        "for index in range(10):\n    registry.register_project(Path(sys.argv[2]) / str(index))\n"
    )
    processes = [
        subprocess.Popen([sys.executable, "-c", script, str(own_registry), str(tmp_path / name)])
        for name in ("one", "two", "three")
    ]

    assert [process.wait() for process in processes] == [0, 0, 0]
    assert len(registry.registered_projects()) == 30


async def test_every_projects_checks_list_newest_first(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    first = await ended_check(tmp_path / "shop" / ".agents" / "reality-check", "Check the cart")
    second = await ended_check(tmp_path / "notes", "Check the editor")

    listed = lib.list_checks()

    assert [summary.check_id for summary in listed] == [second.check_id, first.check_id]
    assert listed[0].project.checks_directory == tmp_path / "notes"
    assert listed[1].project.checks_directory == tmp_path / "shop" / ".agents" / "reality-check"
    assert [summary.request for summary in lib.list_checks(tmp_path / "notes")] == ["Check the editor"]
    assert listed[0].has_report
    assert listed[0].state == "done"


async def test_a_running_check_whose_process_is_gone_lists_as_crashed(tmp_path: Path) -> None:
    run = await ended_check(tmp_path)
    process = subprocess.Popen([sys.executable, "-c", "pass"])
    process.wait()
    path = run.directory / "check.json"
    record = CheckRecord.model_validate_json(path.read_text(encoding="utf-8"))
    path.write_text(record.model_copy(update={"status": "running", "pid": process.pid}).model_dump_json(), "utf-8")

    assert [summary.state for summary in lib.list_checks()] == ["crashed"]


def test_a_registry_that_is_not_one_names_its_file(own_registry: Path) -> None:
    own_registry.write_text('{"projects": 3}', encoding="utf-8")

    with pytest.raises(RealityCheckError) as raised:
        lib.list_checks()

    assert raised.value.code == "bad-registry"
    assert str(own_registry) in raised.value.message


async def test_a_report_cites_evidence_by_paths_that_work_from_the_check(tmp_path: Path) -> None:
    run = await ended_check(tmp_path)
    evidence = run.directory / "evidence"
    for name in ("01-home.png", "02-cart.png", "03-console.log", "04-api.json", "unused.json"):
        (evidence / name).write_bytes(b"x")
    (run.directory / "report.md").write_text(
        f"![Home]({evidence / '01-home.png'})\n"
        f"Cart: .agents/reality-check/{run.check_id}/evidence/02-cart.png.\n"
        f"Console: file://{evidence}/03-console.log\n"
        f"Earlier: ../20261001-000000-aaaaaa/evidence/old.png\n"
        f"Evidence root: `{evidence}/`. API: `04-api.json`; not 04-api.json.bak\n",
        encoding="utf-8",
    )

    read = lib.read_check(run.check_id, checks_directory=tmp_path)

    assert read.report == (
        "![Home](evidence/01-home.png)\n"
        "Cart: evidence/02-cart.png.\n"
        "Console: evidence/03-console.log\n"
        "Earlier: ../20261001-000000-aaaaaa/evidence/old.png\n"
        "Evidence root: `evidence/`. API: `04-api.json`; not 04-api.json.bak\n"
    )
    assert {file.path: file.referenced for file in read.evidence} == {
        "evidence/01-home.png": True,
        "evidence/02-cart.png": True,
        "evidence/03-console.log": True,
        "evidence/04-api.json": True,
        "evidence/unused.json": False,
    }


async def test_a_resumed_check_names_the_check_it_continues(tmp_path: Path) -> None:
    first = await ended_check(tmp_path)
    second = await ended_check(tmp_path, "Go on", resume=first.check_id)

    read = lib.read_check(second.check_id, checks_directory=tmp_path)

    assert read.resumes is not None
    assert (read.resumes.check_id, read.resumes.checks_directory) == (first.check_id, tmp_path)
    assert lib.list_checks()[0].resume == first.check_id


@pytest.mark.parametrize(
    "destination",
    [
        "{evidence}/home screen.png",
        "file://{evidence}/home screen.png",
        "../My Project/.agents/reality-check/{check_id}/evidence/home screen.png",
        r"C:\My Project\.agents\reality-check\{check_id}\evidence\home screen.png",
        "evidence/home screen.png",
    ],
)
async def test_markdown_evidence_destinations_with_spaces_are_portable(tmp_path: Path, destination: str) -> None:
    checks_directory = tmp_path / "My Project" / ".agents" / "reality-check"
    run = await ended_check(checks_directory)
    evidence = run.directory / "evidence"
    (evidence / "home screen.png").write_bytes(b"x")
    link = destination.format(evidence=evidence, check_id=run.check_id)
    (run.directory / "report.md").write_text(
        f"![Home](<{link}>)\n[screen]: <{link}>\n![Other](</another project/evidence/home screen.png>)\n",
        encoding="utf-8",
    )

    read = lib.read_check(run.check_id, checks_directory)

    assert read.report == (
        "![Home](<evidence/home screen.png>)\n[screen]: <evidence/home screen.png>\n"
        "![Other](</another project/evidence/home screen.png>)\n"
    )
    assert len(read.evidence) == 1
    assert read.evidence[0].referenced


async def test_evidence_reads_only_files_in_the_evidence_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = await ended_check(tmp_path)
    evidence = run.directory / "evidence"
    (evidence / "01-home.png").write_bytes(b"\x89PNG")
    (evidence / "page.html").write_text("<b>1</b>", encoding="utf-8")
    (evidence / "page.xht").write_text("<b>1</b>", encoding="utf-8")
    (evidence / "big.bin").write_bytes(b"x" * 11)
    (run.directory / "session").mkdir(exist_ok=True)
    (run.directory / "session" / "token.json").write_text("{}", encoding="utf-8")
    outside = tmp_path / "secret.txt"
    outside.write_text("secret", encoding="utf-8")
    try:
        (evidence / "link.txt").symlink_to(outside)
        (evidence / "folder").symlink_to(tmp_path, target_is_directory=True)
    except OSError:
        pytest.skip("This machine does not allow symlinks.")
    monkeypatch.setattr(checks, "MAX_EVIDENCE_BYTES", 10)

    image = lib.read_check_evidence(run.check_id, "evidence/01-home.png", checks_directory=tmp_path)
    page = lib.read_check_evidence(run.check_id, "evidence/page.html", checks_directory=tmp_path)

    assert (image.media_type, image.content) == ("image/png", b"\x89PNG")
    assert page.media_type == "text/plain"
    assert lib.read_check_evidence(run.check_id, "evidence/page.xht", checks_directory=tmp_path).media_type == (
        "text/plain"
    )
    for path, code in [
        ("evidence/../session/token.json", "not-evidence"),
        ("evidence/..\\session\\token.json", "not-evidence"),
        ("evidence/C:\\Windows\\win.ini", "not-evidence"),
        ("session/token.json", "not-evidence"),
        ("report.md", "not-evidence"),
        (str(outside), "not-evidence"),
        ("evidence/link.txt", "not-evidence"),
        ("evidence/folder/secret.txt", "not-evidence"),
        ("evidence/missing.png", "not-evidence"),
        ("evidence/big.bin", "evidence-too-large"),
    ]:
        with pytest.raises(RealityCheckError) as raised:
            lib.read_check_evidence(run.check_id, path, checks_directory=tmp_path)
        assert raised.value.code == code, path
    assert "evidence/link.txt" not in [file.path for file in lib.read_check(run.check_id, tmp_path).evidence]


async def test_the_cli_lists_and_reads_checks(tmp_path: Path) -> None:
    run = await ended_check(tmp_path)
    directory = ["--checks-directory", str(tmp_path)]

    listed = runner.invoke(app, ["list-checks"])
    read = runner.invoke(app, ["read-check", "--check-id", run.check_id, *directory])

    assert [entry["check_id"] for entry in json.loads(listed.stdout)] == [run.check_id]
    assert json.loads(read.stdout)["report"] == "# Report\n\nGo: pass"


async def test_the_cli_writes_utf_8_to_a_pipe_whose_encoding_cannot_hold_the_check(tmp_path: Path) -> None:
    run = await lib.check_software(
        "Check the page", checks_directory=tmp_path, intelligence=FakeIntelligence(finishes("# Report\n\n\u25a0 done"))
    )
    await run.result()

    cli = "from reality_check.cli import main; raise SystemExit(main())"
    read = subprocess.run(
        [sys.executable, "-c", cli, "read-check", "--check-id", run.check_id, "--checks-directory", str(tmp_path)],
        capture_output=True,
        env={**os.environ, "PYTHONIOENCODING": "cp1252"},
        check=False,
    )

    assert read.returncode == 0, read.stderr.decode("utf-8", "replace")
    assert json.loads(read.stdout.decode("utf-8"))["report"] == "# Report\n\n\u25a0 done"


async def test_a_report_that_is_a_link_is_not_read(tmp_path: Path) -> None:
    run = await ended_check(tmp_path)
    report = run.directory / "report.md"
    report.unlink()
    try:
        report.symlink_to(run.directory / "check.json")
    except OSError:
        pytest.skip("This machine does not allow symlinks.")

    assert lib.read_check(run.check_id, checks_directory=tmp_path).report is None


async def test_a_long_report_line_is_read_at_once(tmp_path: Path) -> None:
    run = await ended_check(tmp_path)
    (run.directory / "report.md").write_text(f"![shot](data:image/png;base64,{'A' * 1_000_000})", encoding="utf-8")
    started = time.monotonic()

    lib.read_check(run.check_id, checks_directory=tmp_path)

    assert time.monotonic() - started < 2


async def test_a_check_starts_when_its_project_cannot_be_registered(tmp_path: Path, own_registry: Path) -> None:
    own_registry.write_text("not json", encoding="utf-8")

    run = await ended_check(tmp_path)

    assert (run.directory / "report.md").is_file()
