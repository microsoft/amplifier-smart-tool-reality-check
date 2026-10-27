"""The app's MCP server: the tool that opens the app, the tools its view calls, and the view as an MCP App resource."""

import asyncio
import base64
from collections.abc import Callable
import json
import os
from pathlib import Path
import threading
from typing import Any
from urllib.parse import unquote

from mcp import MCPError
from mcp.server import Server, ServerRequestContext
from mcp.server.apps import APP_MIME_TYPE, EXTENSION_ID, client_supports_apps
from mcp.types import (
    INVALID_PARAMS,
    BlobResourceContents,
    CallToolRequestParams,
    CallToolResult,
    ListResourcesResult,
    ListResourceTemplatesResult,
    ListToolsResult,
    PaginatedRequestParams,
    ReadResourceRequestParams,
    ReadResourceResult,
    TextContent,
    TextResourceContents,
)
from pydantic import BaseModel

from reality_check.capabilities.app.server import App, serve_app, view
from reality_check.capabilities.app.tools import (
    EVIDENCE_FILE,
    EVIDENCE_PREFIX,
    OPEN_APP,
    VIEW,
    VIEW_META,
    VIEW_TOOLS,
    VIEW_URI,
)
from reality_check.schemas import (
    CheckActivity,
    CheckDetail,
    CheckReference,
    CheckSummary,
    EvidenceFile,
    Project,
    RealityCheckError,
)

INSTRUCTIONS = """\
Reality Check has an app where the user sees every check on this machine, past and running, with its report, \
evidence, and what its agent did. Call `open_app` with a check's ID after starting a check, so the user can watch it, \
or when they ask to see their checks. The app only shows checks: start, steer, and cancel them with the tool."""


class AppState(BaseModel):
    """What the view lists, and the check the app was last asked to open, counted so the view moves to it once."""

    checks: list[CheckSummary]
    focus: CheckReference | None
    opened: int
    can_open_folders: bool


class AppServer:
    """The app's MCP server, and the browser host page once it is open.

    Serve `server` over any MCP transport. Several at once share this state, so the browser host page reaches the
    same server the agent's session does. The capabilities the view calls are passed in, so this stays a surface.
    """

    def __init__(
        self,
        server_name: str,
        version: str,
        focus: CheckReference | None,
        list_checks: Callable[[], list[CheckSummary]],
        read_check: Callable[[str, Path], CheckDetail],
        read_check_activity: Callable[[str, int | None, str | None, Path], CheckActivity],
        read_check_evidence: Callable[[str, str, Path], EvidenceFile],
        can_open_folders: Callable[[], bool],
        open_folder: Callable[[Path], None],
        register_project: Callable[[Path], Project],
        registered_projects: Callable[[], list[Project]],
    ) -> None:
        self.focus = focus
        self.opened = 0 if focus is None else 1
        self._list_checks = list_checks
        self._read_check = read_check
        self._read_check_activity = read_check_activity
        self._read_check_evidence = read_check_evidence
        self._can_open_folders = can_open_folders
        self._open_folder = open_folder
        self._register_project = register_project
        self._registered_projects = registered_projects
        self._lock = threading.Lock()
        self._app: App | None = None
        self.server = Server(
            server_name,
            version=version,
            instructions=INSTRUCTIONS,
            on_list_tools=self._list_tools,
            on_call_tool=self._call_tool_or_explain,
            on_list_resources=self._list_resources,
            on_list_resource_templates=self._list_resource_templates,
            on_read_resource=self._read_resource,
        )
        self.server.extensions[EXTENSION_ID] = {}

    def open(self, port: int | None = None) -> App:
        """Serve the browser host page, unless it already is, and return it."""
        with self._lock:
            if self._app is None:
                self._app = serve_app(self.server, port)
            return self._app

    def close(self) -> None:
        """Stop serving the browser host page, if it was opened."""
        with self._lock:
            if self._app is not None:
                self._app.stop()
                self._app = None

    async def _list_tools(
        self, ctx: ServerRequestContext[Any], params: PaginatedRequestParams | None
    ) -> ListToolsResult:
        # Tools only the view calls stay hidden from clients that would show them to the model.
        return ListToolsResult(tools=[OPEN_APP, *VIEW_TOOLS] if client_supports_apps(ctx) else [OPEN_APP])

    async def _list_resources(
        self, ctx: ServerRequestContext[Any], params: PaginatedRequestParams | None
    ) -> ListResourcesResult:
        return ListResourcesResult(resources=[VIEW] if client_supports_apps(ctx) else [])

    async def _list_resource_templates(
        self, ctx: ServerRequestContext[Any], params: PaginatedRequestParams | None
    ) -> ListResourceTemplatesResult:
        return ListResourceTemplatesResult(resource_templates=[EVIDENCE_FILE] if client_supports_apps(ctx) else [])

    async def _read_resource(
        self, ctx: ServerRequestContext[Any], params: ReadResourceRequestParams
    ) -> ReadResourceResult:
        try:
            if params.uri == VIEW_URI:
                contents = TextResourceContents(uri=VIEW_URI, mime_type=APP_MIME_TYPE, text=view(), _meta=VIEW_META)
                return ReadResourceResult(contents=[contents])
            if params.uri.startswith(EVIDENCE_PREFIX):
                return await asyncio.to_thread(self._evidence_file, params.uri)
        except RealityCheckError as error:
            raise MCPError(INVALID_PARAMS, str(error)) from None
        raise MCPError(
            INVALID_PARAMS,
            f"'{params.uri}' is not a resource of this server. It has {VIEW_URI}, and each check's evidence files at "
            f"{EVIDENCE_FILE.uri_template}.",
        )

    def _evidence_file(self, uri: str) -> ReadResourceResult:
        folder, _, rest = uri.removeprefix(EVIDENCE_PREFIX).partition("/")
        check_id, _, path = rest.partition("/")
        checks_directory = self._known(unquote(folder))
        read = self._read_check_evidence(unquote(check_id), unquote(path), checks_directory)
        data = base64.b64encode(read.content).decode("ascii")
        return ReadResourceResult(contents=[BlobResourceContents(uri=uri, mime_type=read.media_type, blob=data)])

    async def _call_tool_or_explain(
        self, ctx: ServerRequestContext[Any], params: CallToolRequestParams
    ) -> CallToolResult:
        # A low-level handler's exception is a protocol error the model never reads, so a named failure is a result.
        try:
            return await self._call_tool(ctx, params)
        except RealityCheckError as error:
            # The code rides along, so the view words the failure for the person rather than showing the message,
            # which names commands and arguments for an agent.
            return CallToolResult(
                content=[TextContent(type="text", text=str(error))],
                structured_content={"code": error.code},
                is_error=True,
            )

    async def _call_tool(self, ctx: ServerRequestContext[Any], params: CallToolRequestParams) -> CallToolResult:
        arguments = params.arguments or {}
        if params.name == OPEN_APP.name:
            return await self._open_app(ctx, arguments)
        if params.name not in {tool.name for tool in VIEW_TOOLS}:
            raise MCPError(INVALID_PARAMS, f"No tool {params.name!r}. The tools are open_app and the view's.")
        if params.name == "list_checks":
            checks = await asyncio.to_thread(self._list_checks)
            state = AppState(
                checks=checks, focus=self.focus, opened=self.opened, can_open_folders=self._can_open_folders()
            )
            return _structured(state.model_dump(mode="json"))
        check_id = str(arguments.get("check_id", ""))
        checks_directory = self._known(str(arguments.get("checks_directory", "")))
        if params.name == "read_check":
            detail = await asyncio.to_thread(self._read_check, check_id, checks_directory)
            return _structured(detail.model_dump(mode="json"))
        if params.name == "read_check_activity":
            after = arguments.get("after")
            tool_call_id = arguments.get("tool_call_id")
            activity = await asyncio.to_thread(
                self._read_check_activity,
                check_id,
                after if isinstance(after, int) else None,
                tool_call_id if isinstance(tool_call_id, str) else None,
                checks_directory,
            )
            return _structured(activity.model_dump(mode="json"))
        detail = await asyncio.to_thread(self._read_check, check_id, checks_directory)
        await asyncio.to_thread(self._open_folder, detail.directory)
        return _structured({"opened": str(detail.directory)})

    async def _open_app(self, ctx: ServerRequestContext[Any], arguments: dict[str, Any]) -> CallToolResult:
        check_id = arguments.get("check_id")
        directory = arguments.get("checks_directory")
        if isinstance(check_id, str) and check_id:
            self.focus = await asyncio.to_thread(
                self._find, check_id, directory if isinstance(directory, str) else None
            )
            self.opened += 1
        app = await asyncio.to_thread(self.open)
        if client_supports_apps(ctx):
            where = f"The app is shown to the user inline, and at {app.url} for a browser."
        else:
            where = f"Give the user this URL to open the app: {app.url}"
        on = f" It opens on check {self.focus.check_id}." if self.focus is not None else ""
        focus = self.focus.model_dump(mode="json") if self.focus is not None else None
        return CallToolResult(
            content=[TextContent(type="text", text=f"{where}{on}")],
            structured_content={"url": app.url, "focus": focus},
        )

    def _find(self, check_id: str, directory: str | None) -> CheckReference:
        if directory is not None:
            # Read before it is registered, so a folder that holds no such check never joins the projects.
            self._read_check(check_id, Path(directory).resolve())
            checks_directory = self._register_project(Path(directory)).checks_directory
            return CheckReference(check_id=check_id, checks_directory=checks_directory)
        for summary in self._list_checks():
            if summary.check_id == check_id:
                return CheckReference(check_id=check_id, checks_directory=summary.project.checks_directory)
        raise RealityCheckError(
            code="check-not-found",
            message=f"No check {check_id!r} in any project checks were started from.",
            remedy="Pass the check's checks_directory too, or take a check_id from `reality-check list-checks`.",
        )

    def _known(self, checks_directory: str) -> Path:
        """A registered project's checks directory, so the view reads no other folder on the machine."""
        for project in self._registered_projects():
            if os.path.normcase(project.checks_directory) == os.path.normcase(checks_directory):
                return project.checks_directory
        raise RealityCheckError(
            code="unknown-checks-directory",
            message=f"{checks_directory!r} is not the checks directory of a project checks were started from.",
            remedy="Take it from a check's `project.checks_directory` in `list_checks`.",
        )


def _structured(structured: dict[str, Any]) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(structured))], structured_content=structured
    )
