"""GitHub Copilot SDK implementation of the intelligence interface."""

import asyncio
from collections.abc import AsyncIterator
import contextlib
from datetime import UTC
from importlib.metadata import version
import json
import shutil
import subprocess
from typing import Any

from copilot import (
    CopilotClient,
    CopilotSession,
    MCPServerConfig,
    MCPStdioServerConfig,
    ModelInfo,
    PermissionHandler,
    Tool,
    ToolInvocation,
    ToolResult,
)
from copilot.session import Attachment
from copilot.session_events import (
    AssistantMessageData,
    AssistantReasoningData,
    AssistantUsageCopilotUsage,
    AssistantUsageData,
    SessionErrorData,
    SessionEvent,
    SessionIdleData,
    SessionMode,
    ToolExecutionCompleteData,
    ToolExecutionStartData,
)

from reality_check.intelligence.events import EventLog, fresh_input
from reality_check.intelligence.schemas import (
    AgentEvent,
    AgentEventKind,
    AgentRequest,
    AgentResult,
    McpServer,
    Steering,
)
from reality_check.intelligence.submission import (
    MAX_INVALID_SUBMISSIONS,
    SUBMIT_TOOL,
    resubmit_prompt,
    submission_problem,
)
from reality_check.schemas import ALL_EFFORTS, RealityCheckError

# How long an aborted turn may take to go idle before the run stops waiting for it.
DRAIN_SECONDS = 30
NANO = 1e9


class CopilotRun:
    """One Copilot session driven in a background task from construction, until it goes idle for good."""

    def __init__(self, client: CopilotClient, request: AgentRequest) -> None:
        self._client = client
        self._request = request
        self._log = EventLog()
        self._idle = asyncio.Event()
        self._running: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self._session: CopilotSession | None = None
        self._session_id: str | None = request.resume
        self._last_text = ""
        self._last_api_call: str | None = None
        self._session_error: str | None = None
        self._cancelling = False
        self._tool_names: dict[str, str] = {}
        self._submitted: dict[str, Any] | None = None
        self._task = asyncio.create_task(self._drive())

    @property
    def session_id(self) -> str | None:
        return self._session_id

    async def running(self) -> None:
        """Return once the first prompt is sent, or once the run ended trying."""
        await self._running

    def events(self) -> AsyncIterator[AgentEvent]:
        return self._log.replay()

    async def steer(self, message: str) -> None:
        if self._session is None or self._task.done():
            raise RealityCheckError(
                code="agent-run-finished",
                message="The agent run has ended, so the steering message was not delivered.",
                remedy=f"Start a new run with resume={self._session_id!r} and the message as its prompt.",
            )
        try:
            await self._session.send(message, mode="immediate")
        except Exception as error:
            raise RealityCheckError(
                code="agent-steer-failed",
                message=f"The steering message was not delivered: {type(error).__name__}: {error}",
                remedy="Send it again, or cancel the run and resume its session with the message as the prompt.",
            ) from error

    async def cancel(self) -> None:
        if self._task.done():
            return
        self._cancelling = True
        if self._session is not None:
            with contextlib.suppress(Exception):
                await self._session.abort()
        _, pending = await asyncio.wait([self._task], timeout=DRAIN_SECONDS)
        if pending:
            self._idle.set()
        await asyncio.wait([self._task])

    async def result(self) -> AgentResult:
        return await asyncio.shield(self._task)

    async def _drive(self) -> AgentResult:
        timeout = self._request.timeout_seconds
        try:
            async with asyncio.timeout(timeout):
                result = await self._turns()
        except TimeoutError:
            await self._drain()
            result = AgentResult(
                text=self._last_text,
                error=f"The agent did not finish within {timeout} seconds; resume session {self._session_id} to go on.",
                session_id=self._session_id,
            )
        except Exception as error:  # an SDK or runtime failure is the caller's data, not a crash
            result = AgentResult(error=f"{type(error).__name__}: {error}", session_id=self._session_id)
        finally:
            if not self._running.done():
                self._running.set_result(None)
            with contextlib.suppress(Exception):
                await self._client.stop()
        self._emit("terminal", result.error or result.text, result.model_dump(mode="json"))
        return result

    async def _turns(self) -> AgentResult:
        options = self._session_options()
        if self._request.resume is not None:
            session = await self._client.resume_session(self._request.resume, **options)
        else:
            session = await self._client.create_session(**options)
        self._session = session
        self._session_id = session.session_id
        self._last_text = ""
        schema = self._request.output_schema
        prompt = self._request.initial_message
        # The runtime echoes an attachment back in an event it cannot parse without a display name.
        attachments: list[Attachment] = [
            {"type": "file", "path": str(path), "displayName": path.name} for path in self._request.images
        ]
        invalid = 0
        while True:
            if self._cancelling:
                return self._cancelled()
            await self._turn(session, prompt, attachments)
            attachments = []
            if self._cancelling:
                return self._cancelled()
            if self._session_error is not None:
                return AgentResult(text=self._last_text, error=self._session_error, session_id=self._session_id)
            if schema is None:
                return AgentResult(text=self._last_text, session_id=self._session_id)
            problem = submission_problem(self._submitted, schema)
            if problem is None:
                return AgentResult(output=self._submitted, text=self._last_text, session_id=self._session_id)
            if invalid >= MAX_INVALID_SUBMISSIONS:
                return AgentResult(
                    text=self._last_text,
                    error=f"No valid submission after {invalid} retries: {problem}",
                    session_id=self._session_id,
                )
            invalid += 1
            self._submitted = None
            prompt = resubmit_prompt(problem)

    async def _turn(self, session: CopilotSession, prompt: str, attachments: list[Attachment]) -> None:
        """Send one prompt and wait until the session goes idle; a resubmission keeps the earlier turn's text."""
        self._idle.clear()
        self._last_api_call = None
        self._session_error = None
        await session.send(prompt, attachments=attachments or None)
        if not self._running.done():
            self._running.set_result(None)
        await self._idle.wait()

    async def _drain(self) -> None:
        """Abort the turn in flight and wait for it to settle, so the session on disk is whole when resumed."""
        if self._session is None:
            return
        self._idle.clear()
        with contextlib.suppress(Exception):
            await self._session.abort()
            await asyncio.wait_for(self._idle.wait(), DRAIN_SECONDS)

    def _cancelled(self) -> AgentResult:
        return AgentResult(text=self._last_text, cancelled=True, session_id=self._session_id)

    def _session_options(self) -> dict[str, Any]:
        request = self._request
        options: dict[str, Any] = {
            "model": request.model,
            "on_permission_request": PermissionHandler.approve_all,
            "skip_custom_instructions": True,
            "enable_session_telemetry": False,
            "on_event": self._on_event,
        }
        if request.reasoning_effort is not None:
            options["reasoning_effort"] = request.reasoning_effort
        if request.session_directory is not None:
            # The session's whole state is kept there, and resumed only from there.
            options["config_directory"] = str(request.session_directory)
        if request.workspace is not None:
            options["working_directory"] = str(request.workspace.path)
        if request.mcp_servers:
            options["mcp_servers"] = {name: mcp_server_config(server) for name, server in request.mcp_servers.items()}
        if request.skill_directories:
            options["skill_directories"] = [str(directory) for directory in request.skill_directories]
        if request.output_schema is not None:
            options["tools"] = [
                Tool(
                    name=SUBMIT_TOOL,
                    description="Submit your final answer. Call it exactly once, when you are done.",
                    parameters=request.output_schema,
                    handler=self._capture,
                    skip_permission=True,
                    is_terminal=True,
                )
            ]
        return options

    def _capture(self, invocation: ToolInvocation) -> ToolResult:
        self._submitted = invocation.arguments
        return ToolResult(text_result_for_llm="Submission received.")

    def _note_message(self, data: AssistantMessageData) -> None:
        """Keep the latest model response whole: one split at reasoning boundaries comes as chunks of one API call."""
        chunk = bool(data.chunk_index) and data.api_call_id is not None and data.api_call_id == self._last_api_call
        parts = [self._last_text, data.content] if chunk else [data.content]
        self._last_text = "\n\n".join(part for part in parts if part)
        self._last_api_call = data.api_call_id

    def _on_event(self, event: SessionEvent) -> None:
        root = not event.agent_id
        agent = {} if root else {"agent_id": event.agent_id}
        match event.data:
            case AssistantMessageData() as data:
                if root:
                    self._note_message(data)
                if data.content:
                    self._emit("message", data.content, agent, event)
            case AssistantReasoningData() as data if data.content.strip():
                self._emit("reasoning", data.content, {"reasoning_id": data.reasoning_id, **agent}, event)
            case ToolExecutionStartData() as data:
                self._tool_names[data.tool_call_id] = data.tool_name
                arguments = "" if data.arguments is None else json.dumps(data.arguments, default=str)
                self._emit(
                    "tool_call",
                    f"{data.tool_name} {arguments}".strip(),
                    {
                        "tool_call_id": data.tool_call_id,
                        "tool_name": data.tool_name,
                        "arguments": data.arguments,
                        **agent,
                    },
                    event,
                )
            case ToolExecutionCompleteData() as data:
                outcome: dict[str, Any] = {
                    "tool_call_id": data.tool_call_id,
                    "tool_name": self._tool_names.get(data.tool_call_id, ""),
                    "success": data.success,
                    **agent,
                }
                content = ""
                if data.result is not None:
                    content = outcome["result"] = data.result.content
                    detailed = data.result.detailed_content
                    if detailed is not None and detailed != content:
                        outcome["detailed_result"] = detailed
                if data.error is not None:
                    outcome["error"] = data.error.message
                    content = content or data.error.message
                self._emit("tool_result", content, outcome, event)
            case AssistantUsageData() as data:
                usage = {
                    "model": data.model,
                    "input_tokens": data.input_tokens,
                    "fresh_input_tokens": fresh_input(
                        data.input_tokens, data.cache_read_tokens, data.cache_write_tokens
                    ),
                    "output_tokens": data.output_tokens,
                    "cache_read_tokens": data.cache_read_tokens,
                    "cache_write_tokens": data.cache_write_tokens,
                    "reasoning_tokens": data.reasoning_tokens,
                    "cost": data.cost,
                    "copilot_usage": data.copilot_usage.to_dict() if data.copilot_usage is not None else None,
                    "billing": _billing(data.copilot_usage),
                }
                self._emit("usage", "", {**usage, **agent}, event)
            case SessionIdleData() as data if root and data.mode != SessionMode.AUTOPILOT:
                self._idle.set()
            case SessionErrorData() as data if root:
                self._session_error = f"{data.error_type}: {data.message}"
                self._idle.set()

    def _emit(self, kind: AgentEventKind, text: str, data: dict[str, Any], source: SessionEvent | None = None) -> None:
        event = AgentEvent(kind=kind, text=text, data=data)
        if source is not None:
            event.time = source.timestamp.astimezone(UTC)
        self._log.emit(event)


class CopilotIntelligence:
    """Runs agents through a Copilot CLI runtime on this machine, signed in as the GitHub CLI's user."""

    def __init__(self) -> None:
        self.implementation = f"copilot-sdk {version('github-copilot-sdk')}"
        self.steering: Steering = "mid-turn"
        self._token: str | None = None

    def preflight(self) -> None:
        self._github_token()

    async def start(self, request: AgentRequest) -> CopilotRun:
        token = await asyncio.to_thread(self._github_token)
        working_directory = str(request.workspace.path) if request.workspace is not None else None
        client = CopilotClient(working_directory=working_directory, github_token=token)
        try:
            await client.start()
            # From the run's own client, so the account's models are known without starting another runtime.
            problem = copilot_model_problem(await client.list_models(), request)
        except Exception as error:
            with contextlib.suppress(Exception):
                await client.stop()
            raise RealityCheckError(
                code="copilot-start-failed",
                message=f"The Copilot runtime did not start: {type(error).__name__}: {error}",
                remedy="Check that `gh auth status` shows an account with Copilot access, then start again.",
            ) from error
        if problem is not None:
            with contextlib.suppress(Exception):
                await client.stop()
            raise problem
        run = CopilotRun(client, request)
        await run.running()
        return run

    def _github_token(self) -> str:
        if self._token is not None:
            return self._token
        if shutil.which("gh") is None:
            raise RealityCheckError(
                code="gh-not-installed",
                message="The copilot agent provider signs in through the GitHub CLI, which is not installed.",
                remedy="Install gh from https://cli.github.com/ and sign in with `gh auth login`.",
            )
        minted = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True)
        if minted.returncode != 0:
            raise RealityCheckError(
                code="gh-not-signed-in",
                message=f"The GitHub CLI is not signed in: {minted.stderr.strip()}",
                remedy="Run `gh auth login` with an account that has Copilot access.",
            )
        self._token = minted.stdout.strip()
        return self._token


def copilot_model_problem(models: list[ModelInfo], request: AgentRequest) -> RealityCheckError | None:
    """Why this Copilot account cannot run the request's model as asked, or None when it can.

    The runtime runs another model in place of one it does not know, without saying so.
    """
    model = next((candidate for candidate in models if candidate.id == request.model), None)
    if model is None:
        return RealityCheckError(
            code="model-not-available",
            message=f"{request.model} is not one of the models this Copilot account has: "
            f"{', '.join(candidate.id for candidate in models) or 'none'}.",
            remedy="Pick one listed by `reality-check list-intelligence-models` that this Copilot account has.",
        )
    # The runtime lists "none" for some models and then refuses it.
    efforts = [effort for effort in ALL_EFFORTS if effort in (model.supported_reasoning_efforts or [])]
    if request.reasoning_effort is not None and request.reasoning_effort not in efforts:
        takes = f"takes one of: {', '.join(efforts)}" if efforts else "takes none"
        return RealityCheckError(
            code="bad-reasoning-effort",
            message=f"{request.model} on Copilot does not take the reasoning effort {request.reasoning_effort!r}; "
            f"it {takes}.",
            remedy="Pass one it takes, or leave the reasoning effort out for its default.",
        )
    if request.images and not model.capabilities.supports.vision:
        return RealityCheckError(
            code="model-without-vision",
            message=f"{request.model} on Copilot cannot be shown images.",
            remedy="Pick a model that can, from `reality-check list-intelligence-models`, or leave the images out.",
        )
    return None


def _billing(usage: AssistantUsageCopilotUsage | None) -> dict[str, float]:
    """What Copilot bills for the call, in AIU."""
    return {} if usage is None else {"AIU": usage.total_nano_aiu / NANO}


def mcp_server_config(server: McpServer) -> MCPServerConfig:
    """The SDK's wire form of a local MCP server, with every tool it offers enabled."""
    config: MCPStdioServerConfig = {"type": "stdio", "command": server.command, "args": server.args, "tools": ["*"]}
    if server.env is not None:
        config["env"] = server.env
    if server.cwd is not None:
        config["working_directory"] = str(server.cwd)
    return config
