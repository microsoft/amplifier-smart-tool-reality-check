"""The app served on this machine: its pages, its view, and the read-only tools and evidence files the view reads."""

import base64
from collections.abc import Callable, Iterator
from pathlib import Path
import re
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from fakes import FakeIntelligence, finishes
from mcp import Client, MCPError
from mcp.types import BlobResourceContents, TextContent
import pytest

from reality_check import lib
from reality_check.capabilities.app import folders
from reality_check.capabilities.app import server as server_module
from reality_check.capabilities.check_software import check, registry
from reality_check.schemas import CheckActivity, CheckDetail, RealityCheckError

TIMEOUT_SECONDS = 5


@pytest.fixture(autouse=True)
def skills_cache(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(check, "SKILLS_CACHE_DIRECTORY", tmp_path_factory.mktemp("skills-cache"))
    monkeypatch.setattr(check, "POLL_SECONDS", 0.01)


@pytest.fixture
def built(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A built app: a host page, a sandbox page, an asset, and a view."""
    static = tmp_path_factory.mktemp("static")
    (static / "host" / "assets").mkdir(parents=True)
    (static / "host" / "index.html").write_text(
        '<meta name="reality-check-sandbox-port" content="{{sandbox_port}}">', encoding="utf-8"
    )
    (static / "host" / "sandbox.html").write_text("<p>{{host_port}}</p>", encoding="utf-8")
    (static / "host" / "assets" / "host.js").write_text("1", encoding="utf-8")
    (static / "view").mkdir()
    (static / "view" / "mcp_app.html").write_text('<meta content="{{version}}">', encoding="utf-8")
    monkeypatch.setattr(server_module, "HOST_STATIC", static / "host")
    monkeypatch.setattr(server_module, "VIEW", static / "view" / "mcp_app.html")
    return static


@pytest.fixture
def open_app() -> Iterator[Callable[..., lib.AppServer]]:
    opened: list[lib.AppServer] = []

    def open_with(directory: Path | None = None) -> lib.AppServer:
        app_server = lib.app_server(directory)
        app_server.open()
        opened.append(app_server)
        return app_server

    yield open_with
    for app_server in opened:
        app_server.close()


def get(url: str, origin: str | None = None) -> tuple[int, dict[str, str], str]:
    request = Request(url, headers={"Origin": origin} if origin else {})
    try:
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return response.status, {k.lower(): v for k, v in response.headers.items()}, response.read().decode("utf-8")
    except HTTPError as error:
        return error.code, {k.lower(): v for k, v in error.headers.items()}, error.read().decode("utf-8")


def text_of(result: Any) -> str:
    return "\n".join(block.text for block in result.content if isinstance(block, TextContent))


async def ended_check(checks_directory: Path) -> lib.CheckRun:
    run = await lib.check_software(
        "Check the page", checks_directory=checks_directory, intelligence=FakeIntelligence(finishes())
    )
    await run.result()
    return run


def test_the_host_page_points_at_a_sandbox_on_another_origin_with_the_view_s_policy(
    built: Path, open_app: Callable[..., lib.AppServer]
) -> None:
    url = open_app().open().url
    _, _, page = get(url)
    port = re.search(r'name="reality-check-sandbox-port" content="(\d+)"', page)
    assert port is not None
    sandbox = f"http://127.0.0.1:{port[1]}"

    status, headers, body = get(f"{sandbox}/sandbox.html")

    assert sandbox != url
    assert (status, body) == (200, f"<p>{url.rsplit(':', 1)[1]}</p>")
    assert headers["content-security-policy"] == server_module.VIEW_CSP
    assert get(f"{sandbox}/assets/host.js")[0] == 200
    assert get(f"{sandbox}/assets/..%2Findex.html")[0] == 404
    assert get(f"{url}/mcp", origin="http://evil.example")[0] in {403, 421}


def test_the_app_names_the_build_command_until_it_is_built(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, open_app: Callable[..., lib.AppServer]
) -> None:
    monkeypatch.setattr(server_module, "VIEW", tmp_path / "mcp_app.html")
    monkeypatch.setattr(server_module, "HOST_STATIC", tmp_path / "host")

    with pytest.raises(RealityCheckError, match=r"uv run build-app\.py") as raised:
        lib.app_view()
    status, _, body = get(open_app().open().url)

    assert raised.value.code == "app-not-built"
    assert (status, "uv run build-app.py" in body) == (503, True)


def test_the_view_carries_the_tool_s_version(built: Path) -> None:
    assert lib.app_view() == f'<meta content="{lib.version()}">'


def test_a_held_port_is_a_named_failure_until_close_frees_it() -> None:
    first = lib.app_server()
    port = int(first.open().url.rsplit(":", 1)[1])

    with pytest.raises(RealityCheckError) as raised:
        lib.app_server().open(port)

    assert raised.value.code == "port-held"
    first.close()
    second = lib.app_server()
    second.open(port)
    second.close()


async def test_the_view_reads_checks_and_their_evidence_and_nothing_else(
    tmp_path: Path, open_app: Callable[..., lib.AppServer]
) -> None:
    run = await ended_check(tmp_path / "checks")
    (run.directory / "evidence" / "01-home.png").write_bytes(b"\x89PNG")
    (run.directory / "session").mkdir(exist_ok=True)
    (run.directory / "session" / "token.json").write_text("{}", encoding="utf-8")
    directory = str(tmp_path / "checks")
    arguments = {"check_id": run.check_id, "checks_directory": directory}
    evidence = f"reality-check://checks/{quote(directory, safe='')}/{run.check_id}"

    async with Client(f"{open_app().open().url}/mcp") as client:
        listed = await client.call_tool("list_checks", {})
        read = await client.call_tool("read_check", arguments)
        activity = await client.call_tool("read_check_activity", {**arguments, "after": 0})
        image = (await client.read_resource(f"{evidence}/evidence/01-home.png")).contents[0]
        with pytest.raises(MCPError, match="not a path inside"):
            await client.read_resource(f"{evidence}/session/token.json")
        elsewhere = await client.call_tool("read_check", {**arguments, "checks_directory": str(tmp_path)})

    assert [check["check_id"] for check in (listed.structured_content or {})["checks"]] == [run.check_id]
    assert CheckDetail.model_validate(read.structured_content).evidence[0].path == "evidence/01-home.png"
    assert CheckActivity.model_validate(activity.structured_content).state == "done"
    assert isinstance(image, BlobResourceContents)
    assert (image.mime_type, base64.b64decode(image.blob)) == ("image/png", b"\x89PNG")
    assert elsewhere.is_error
    assert elsewhere.structured_content == {"code": "unknown-checks-directory"}


async def test_open_app_opens_on_the_check_it_names_found_in_any_project(
    tmp_path: Path, open_app: Callable[..., lib.AppServer]
) -> None:
    run = await ended_check(tmp_path / "checks")
    app_server = open_app()

    async with Client(app_server.server) as client:
        opened = await client.call_tool("open_app", {"check_id": run.check_id})
        listed = await client.call_tool("list_checks", {})
        missing = await client.call_tool("open_app", {"check_id": "20261001-000000-aaaaaa"})
        elsewhere = await client.call_tool(
            "open_app", {"check_id": run.check_id, "checks_directory": str(tmp_path / "elsewhere")}
        )

    focus = {"check_id": run.check_id, "checks_directory": str(tmp_path / "checks")}
    assert f"It opens on check {run.check_id}." in text_of(opened)
    assert (opened.structured_content or {})["focus"] == focus
    assert (listed.structured_content or {})["focus"] == focus
    assert (listed.structured_content or {})["opened"] == 1
    assert missing.is_error
    assert elsewhere.structured_content == {"code": "check-not-found"}
    assert [project.checks_directory for project in registry.registered_projects()] == [tmp_path / "checks"]


async def test_a_directory_given_to_the_app_is_added_and_opened_on_its_newest_check(
    tmp_path: Path, open_app: Callable[..., lib.AppServer], own_registry: Path
) -> None:
    run = await ended_check(tmp_path / "kept")
    own_registry.unlink()

    app_server = open_app(tmp_path / "kept")

    assert app_server.focus is not None
    assert app_server.focus.check_id == run.check_id
    assert [summary.project.checks_directory for summary in lib.list_checks()] == [tmp_path / "kept"]


async def test_the_view_opens_a_check_s_folder_and_names_the_failure_when_it_cannot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, open_app: Callable[..., lib.AppServer]
) -> None:
    run = await ended_check(tmp_path / "checks")
    opened: list[Path] = []
    monkeypatch.setattr(folders, "open_folder", opened.append)
    monkeypatch.setattr(folders, "can_open_folders", lambda: True)
    arguments = {"check_id": run.check_id, "checks_directory": str(tmp_path / "checks")}

    async with Client(open_app().server) as client:
        listed = await client.call_tool("list_checks", {})
        shown = await client.call_tool("open_check_folder", arguments)

    assert (listed.structured_content or {})["can_open_folders"] is True
    assert opened == [run.directory]
    assert shown.structured_content == {"opened": str(run.directory)}

    def fails(path: Path) -> None:
        raise RealityCheckError(code="cannot-open-folder", message="No file manager.", remedy="Open it yourself.")

    monkeypatch.setattr(folders, "open_folder", fails)
    async with Client(open_app().server) as client:
        refused = await client.call_tool("open_check_folder", arguments)

    assert refused.is_error
    assert refused.structured_content == {"code": "cannot-open-folder"}
