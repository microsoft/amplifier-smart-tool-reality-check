"""Claude Agent SDK implementation of the intelligence interface."""

import asyncio
import base64
from collections import deque
from collections.abc import AsyncIterator, Callable
from concurrent.futures import ThreadPoolExecutor
import contextlib
from datetime import UTC, datetime
import hashlib
from importlib.metadata import version
import json
import logging
import os
from pathlib import Path
import secrets
import shutil
import signal
import sys
from typing import Any
import uuid

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    Message,
    ProcessError,
    ResultError,
    ResultMessage,
    SessionKey,
    SessionListSubkeysKey,
    SessionStore,
    SessionStoreEntry,
    SessionStoreListEntry,
    SessionSummaryEntry,
    SystemMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
    fold_session_summary,
)

from reality_check.intelligence.events import EventLog
from reality_check.intelligence.interface import agent_environment, state_directory
from reality_check.intelligence.schemas import (
    IMAGE_MEDIA_TYPES,
    AgentEvent,
    AgentEventKind,
    AgentRequest,
    AgentResult,
    Steering,
)
from reality_check.intelligence.submission import MAX_INVALID_SUBMISSIONS, resubmit_prompt, submission_problem
from reality_check.schemas import RealityCheckError

AUTHENTICATION_DOCUMENTATION = "https://code.claude.com/docs/en/agent-sdk/quickstart"
# Claude Code otherwise reports usage, errors, and other nonessential traffic to Anthropic.
TELEMETRY_OFF = {
    "DISABLE_TELEMETRY": "1",
    "DISABLE_ERROR_REPORTING": "1",
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
}
# The plugin Reality Check's skills are loaded as, so the agent sees them as `reality-check:<name>`.
PLUGIN_NAME = "reality-check"
# How long a stopping run waits for Claude Code to abort its tools before ending the process anyway.
INTERRUPT_SECONDS = 5
# An image the agent reads back comes as one base64 JSON line, well past the SDK's 1 MB default for a line.
MAX_MESSAGE_BYTES = 64 * 1024 * 1024
PLUGIN_HASH_LENGTH = 16
# How much of the end of Claude Code's stderr a run keeps to explain why the process failed.
STDERR_LINES = 40
# The SDK raises as soon as Claude Code exits, while its own task may still be reading the last of its stderr; a
# failed run waits for stderr to stay quiet for a moment, a few moments at most, so it reports the process's last words.
STDERR_QUIET_SECONDS = 0.1
STDERR_QUIET_ATTEMPTS = 5
# Where Anthropic counts a call's input. Its output tokens are final only on a result, so a call's own are not summed.
INPUT_KEYS = ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
# The SDK logs the failure of a Claude Code process that exited with placeholder text for its stderr, and with no
# logging configured that line lands in a detached check's process.log; a run reports that failure itself, better.
SDK_READER_LOGGER = "claude_agent_sdk._internal.query"
SDK_FAILURE_PREFIX = "Fatal error in message reader: "
SDK_STDERR_PLACEHOLDER = "Error output: Check stderr output for details"


class ClaudeRun:
    """One agent in its own Claude Code process, driven in a background task from construction until it answers."""

    def __init__(self, client: ClaudeSDKClient, request: AgentRequest, stderr: deque[str]) -> None:
        self._client = client
        self._request = request
        self._stderr = stderr
        self._log = EventLog()
        self._running: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self._stopping = asyncio.Event()
        self._session_id: str | None = request.resume
        self._last_text = ""
        self._answered = False
        # User messages sent and not yet echoed back by Claude Code. A result ends the run only when there are none,
        # since a steering message that arrives late in a turn starts another one.
        self._unechoed: set[str] = set()
        # Claude Code reports the cost of its whole process on each result, and each result's tokens alone.
        self._cost_reported = 0.0
        # The usage of each API call since the last result, by message id. Claude Code repeats a call's usage on the
        # assistant message of each of its content blocks, and reports usage itself only on a result.
        self._calls: dict[str, dict[str, Any]] = {}
        self._tool_names: dict[str, str] = {}
        self._messages = aiter(client.receive_messages())
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
        if self._answered or self._task.done():
            raise RealityCheckError(
                code="agent-run-finished",
                message="The agent run has ended, so the steering message was not delivered.",
                remedy=f"Start a new run with resume={self._session_id!r} and the message as its prompt.",
            )
        try:
            await self._send(message, [])
        except Exception as error:
            raise RealityCheckError(
                code="agent-steer-failed",
                message=f"The steering message was not delivered: {type(error).__name__}: {error}",
                remedy="Send it again, or cancel the run and resume its session with the message as the prompt.",
            ) from error

    async def cancel(self) -> None:
        if self._task.done():
            return
        self._stopping.set()
        await asyncio.wait([self._task])

    async def result(self) -> AgentResult:
        return await asyncio.shield(self._task)

    async def _drive(self) -> AgentResult:
        timeout = self._request.timeout_seconds
        stopping = asyncio.create_task(self._stopping.wait())
        turns: asyncio.Task[AgentResult] | None = None
        try:
            async with asyncio.timeout(timeout):
                turns = asyncio.create_task(self._turns())
                await asyncio.wait([turns, stopping], return_when=asyncio.FIRST_COMPLETED)
            result = turns.result() if turns.done() else self._cancelled()
        except TimeoutError:
            result = AgentResult(
                text=self._last_text,
                error=f"The agent did not finish within {timeout} seconds; resume session {self._session_id} to go on.",
                session_id=self._session_id,
            )
        except Exception as error:  # an SDK or runtime failure is the caller's data, not a crash
            result = AgentResult(
                text=self._last_text,
                error=await failure_text(error=error, stderr=self._stderr),
                session_id=self._session_id,
            )
        finally:
            stopping.cancel()
            if turns is not None and not turns.done():
                turns.cancel()
                await asyncio.wait([turns])
            if not self._running.done():
                self._running.set_result(None)
            await self._close(interrupt=not self._answered)
        self._note_unreported_usage()
        self._emit("terminal", result.error or result.text, result.model_dump(mode="json"))
        return result

    async def _turns(self) -> AgentResult:
        schema = self._request.output_schema
        await self._send(self._request.initial_message, self._request.images)
        if not self._running.done():
            self._running.set_result(None)
        invalid = 0
        while True:
            answer = await self._answer()
            if answer.is_error:
                self._answered = True
                return AgentResult(text=self._last_text, error=describe(answer), session_id=self._session_id)
            text = answer.result or ""
            if schema is None:
                self._answered = True
                return AgentResult(text=text, session_id=self._session_id)
            output = answer.structured_output if isinstance(answer.structured_output, dict) else None
            problem = submission_problem(output, schema)
            if problem is None:
                self._answered = True
                return AgentResult(output=output, text=text, session_id=self._session_id)
            if invalid >= MAX_INVALID_SUBMISSIONS:
                self._answered = True
                return AgentResult(
                    text=text,
                    error=f"No valid submission after {invalid} retries: {problem}",
                    session_id=self._session_id,
                )
            invalid += 1
            await self._send(resubmit_prompt(problem), [])

    async def _answer(self) -> ResultMessage:
        """Read messages until a result that answers every message sent so far."""
        while True:
            message = await anext(self._messages, None)
            if message is None:
                raise RuntimeError("Claude Code ended the conversation without a result.")
            self._note(message)
            if isinstance(message, ResultMessage) and not self._unechoed:
                return message

    async def _send(self, text: str, images: list[Path]) -> None:
        # Claude Code echoes a user message under the uuid it was sent with, which is how the run sees it taken.
        identifier = str(uuid.uuid4())
        content: str | list[dict[str, Any]] = text
        if images:
            content = [{"type": "text", "text": text}, *(image_block(path) for path in images)]
        self._unechoed.add(identifier)
        message = {
            "type": "user",
            "uuid": identifier,
            "message": {"role": "user", "content": content},
            "parent_tool_use_id": None,
        }
        try:
            await self._client.query(_one(message))
        except Exception:
            self._unechoed.discard(identifier)
            raise

    async def _close(self, interrupt: bool) -> None:
        """End the Claude Code process; an unfinished run first has it abort its tools, so none outlive it."""
        if interrupt:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self._client.interrupt(), INTERRUPT_SECONDS)
        with contextlib.suppress(Exception):
            await self._client.disconnect()

    def _cancelled(self) -> AgentResult:
        return AgentResult(text=self._last_text, cancelled=True, session_id=self._session_id)

    def _note(self, message: Message) -> None:
        match message:
            case SystemMessage() as system:
                session_id = system.data.get("session_id")
                if isinstance(session_id, str):
                    self._session_id = session_id
            case AssistantMessage() as assistant:
                if assistant.session_id is not None:
                    self._session_id = assistant.session_id
                if assistant.message_id is not None and assistant.usage is not None:
                    self._calls[assistant.message_id] = assistant.usage
                self._note_assistant(assistant)
            case UserMessage() as user:
                if user.uuid is not None:
                    self._unechoed.discard(user.uuid)
                self._note_user(user)
            case ResultMessage() as answer:
                self._session_id = answer.session_id
                self._note_usage(answer)

    def _note_assistant(self, message: AssistantMessage) -> None:
        agent = _agent(message.parent_tool_use_id)
        texts: list[str] = []
        for block in message.content:
            match block:
                case TextBlock(text=text) if text.strip():
                    texts.append(text)
                    self._emit("message", text, agent)
                case ThinkingBlock(thinking=thinking) if thinking.strip():
                    self._emit("reasoning", thinking, agent)
                case ToolUseBlock(id=call_id, name=name, input=arguments):
                    self._tool_names[call_id] = name
                    self._emit(
                        "tool_call",
                        f"{name} {json.dumps(arguments, default=str)}".strip(),
                        {"tool_call_id": call_id, "tool_name": name, "arguments": arguments, **agent},
                    )
        if texts and message.parent_tool_use_id is None:
            self._last_text = "\n\n".join(texts)

    def _note_user(self, message: UserMessage) -> None:
        if isinstance(message.content, str):
            return
        agent = _agent(message.parent_tool_use_id)
        for block in message.content:
            if isinstance(block, ToolResultBlock):
                content = tool_result_text(block.content)
                self._emit(
                    "tool_result",
                    content,
                    {
                        "tool_call_id": block.tool_use_id,
                        "tool_name": self._tool_names.get(block.tool_use_id, ""),
                        "success": not block.is_error,
                        "result": content,
                        **agent,
                    },
                )

    def _note_usage(self, message: ResultMessage) -> None:
        usage = message.usage or {}
        if self._calls and not any(usage.get(key) for key in (*INPUT_KEYS, "output_tokens")):
            usage = self._summed_calls()
        calls = max(1, len(self._calls))
        self._calls.clear()
        model_usage = message.model_usage or {}
        model = self._request.model
        cost: dict[str, float] | None = None
        if message.total_cost_usd is not None:
            cost = {"USD": message.total_cost_usd - self._cost_reported}
            self._cost_reported = message.total_cost_usd
        if model_usage and model not in model_usage:
            model = next(iter(model_usage))
        self._emit(
            "usage",
            "",
            {
                "model": model,
                "input_tokens": usage.get("input_tokens"),
                # Anthropic counts cache reads and writes apart from input_tokens.
                "fresh_input_tokens": usage.get("input_tokens"),
                "output_tokens": usage.get("output_tokens"),
                "cache_read_tokens": usage.get("cache_read_input_tokens"),
                "cache_write_tokens": usage.get("cache_creation_input_tokens"),
                "cost": cost,
                "billing": cost or {},
                "model_usage": dict(model_usage),
                "calls": calls,
            },
        )

    def _note_unreported_usage(self) -> None:
        """Count the calls no result reported, as a run that ended without one leaves them."""
        if not self._calls:
            return
        usage = self._summed_calls()
        self._emit(
            "usage",
            "",
            {
                "model": self._request.model,
                "input_tokens": usage["input_tokens"],
                "fresh_input_tokens": usage["input_tokens"],
                "output_tokens": None,
                "cache_read_tokens": usage["cache_read_input_tokens"],
                "cache_write_tokens": usage["cache_creation_input_tokens"],
                "cost": None,
                "billing": {},
                "calls": len(self._calls),
                "incomplete": True,
            },
        )
        self._calls.clear()

    def _summed_calls(self) -> dict[str, int]:
        """The input tokens of the calls since the last result, summed."""
        return {key: sum(call.get(key) or 0 for call in self._calls.values()) for key in INPUT_KEYS}

    def _emit(self, kind: AgentEventKind, text: str, data: dict[str, Any]) -> None:
        self._log.emit(AgentEvent(kind=kind, text=text, data=data))


class FolderSessionStore(SessionStore):
    """A copy of every transcript of a session in one directory, from which the session can also be resumed."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    async def append(self, key: SessionKey, entries: list[SessionStoreEntry]) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as transcript:
            transcript.writelines(json.dumps(entry) + "\n" for entry in entries)

    async def load(self, key: SessionKey) -> list[SessionStoreEntry] | None:
        path = self._path(key)
        if not path.is_file():
            return None
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]

    async def list_sessions(self, project_key: str) -> list[SessionStoreListEntry]:
        return [
            {"session_id": path.stem, "mtime": path.stat().st_mtime_ns // 1_000_000}
            for path in sorted(self.directory.glob("*.jsonl"))
        ]

    async def list_session_summaries(self, project_key: str) -> list[SessionSummaryEntry]:
        summaries: list[SessionSummaryEntry] = []
        for session in await self.list_sessions(project_key):
            key: SessionKey = {"project_key": project_key, "session_id": session["session_id"]}
            summary = fold_session_summary(None, key, await self.load(key) or [])
            summary["mtime"] = session["mtime"]
            summaries.append(summary)
        return summaries

    async def delete(self, key: SessionKey) -> None:
        self._path(key).unlink(missing_ok=True)
        if not key.get("subpath"):
            shutil.rmtree(self.directory / key["session_id"], ignore_errors=True)

    async def list_subkeys(self, key: SessionListSubkeysKey) -> list[str]:
        folder = self.directory / key["session_id"]
        return sorted(path.relative_to(folder).with_suffix("").as_posix() for path in folder.rglob("*.jsonl"))

    def _path(self, key: SessionKey) -> Path:
        # The directory belongs to one run's session, so the project key Claude Code scopes sessions by is left out.
        subpath = key.get("subpath")
        if subpath:
            return self.directory / key["session_id"] / f"{subpath}.jsonl"
        return self.directory / f"{key['session_id']}.jsonl"


class ClaudeIntelligence:
    """Runs agents through the Claude Code runtime the SDK bundles, with the credentials Claude Code resolves."""

    def __init__(self) -> None:
        self.implementation = f"claude-agent-sdk {version('claude-agent-sdk')}"
        self.steering: Steering = "queued"
        self._signed_in = False

    def preflight(self) -> None:
        if self._signed_in:
            return
        try:
            # Its own thread and event loop, since a caller may already be running one.
            with ThreadPoolExecutor(max_workers=1) as pool:
                account = pool.submit(lambda: asyncio.run(_account())).result()
        except Exception as error:  # whatever stops the runtime from starting, the remedy is the same
            raise _unavailable(error) from error
        if not signed_in(account):
            raise RealityCheckError(
                code="claude-not-signed-in",
                message="The Claude Agent SDK has no credentials.",
                remedy="Set ANTHROPIC_API_KEY to a Claude Console API key, or set CLAUDE_CODE_USE_BEDROCK, "
                "CLAUDE_CODE_USE_ANTHROPIC_AWS, CLAUDE_CODE_USE_VERTEX, or CLAUDE_CODE_USE_FOUNDRY to 1 with that cloud's credentials, as "
                f"{AUTHENTICATION_DOCUMENTATION} describes.",
            )
        self._signed_in = True

    async def start(self, request: AgentRequest) -> ClaudeRun:
        if request.mcp_servers:
            raise RealityCheckError(
                code="mcp-not-supported",
                message="The claude agent provider does not take MCP servers.",
                remedy='Use the copilot agent provider (agent_provider="copilot", --agent-provider copilot), or '
                "leave the MCP servers out.",
            )
        # The same filter added again is not added twice.
        logging.getLogger(SDK_READER_LOGGER).addFilter(without_placeholder_failure)
        stderr: deque[str] = deque(maxlen=STDERR_LINES)
        client = ClaudeSDKClient(options=claude_options(request=request, stderr_line=kept(tail=stderr)))
        try:
            await client.connect()
        except Exception as error:
            with contextlib.suppress(Exception):
                await client.disconnect()
            raise _unavailable(error) from error
        run = ClaudeRun(client=client, request=request, stderr=stderr)
        await run.running()
        return run


def claude_options(request: AgentRequest, stderr_line: Callable[[str], None]) -> ClaudeAgentOptions:
    """The options one run's Claude Code process starts with, each line of its stderr going to `stderr_line`."""
    if request.workspace is not None:
        cwd = request.workspace.path.resolve()
    else:
        cwd = scratch_directory()
        cwd.mkdir(parents=True, exist_ok=True)
    options = ClaudeAgentOptions(
        cwd=cwd,
        model=request.model,
        permission_mode="bypassPermissions",
        effort=request.reasoning_effort,
        # Newer models leave their reasoning out unless asked; its summary is what the activity shows of it.
        thinking={"type": "adaptive", "display": "summarized"},
        resume=request.resume,
        extra_args={"replay-user-messages": None},
        max_buffer_size=MAX_MESSAGE_BYTES,
        # Keeps the caller's CLAUDE.md, settings, and plugins out of the run.
        setting_sources=[],
        env=dict(TELEMETRY_OFF),
        # Without a callback the SDK leaves stderr unread and reports a failed process with no word of why.
        stderr=stderr_line,
    )
    options.env.update(agent_environment(request))
    if request.session_directory is not None:
        options.session_store = FolderSessionStore(request.session_directory)
        options.session_store_flush = "eager"
    if request.output_schema is not None:
        options.output_format = {"type": "json_schema", "schema": request.output_schema}
    if request.skill_directories:
        options.plugins = [{"type": "local", "path": str(skills_plugin(request.skill_directories))}]
        options.skills = "all"
    return options


def skills_plugin(skill_directories: list[Path]) -> Path:
    """A local plugin holding a copy of every skill in the directories, since Claude Code loads skills only from plugins.

    Named by the skills' content, so a written plugin never changes and runs at once can share it. Of two skills with
    one name, the one in the earlier directory is kept.
    """
    skills: dict[str, Path] = {}
    for directory in skill_directories:
        for found in sorted(directory.glob("*/SKILL.md")):
            skills.setdefault(found.parent.name, found.parent)
    digest = hashlib.sha256()
    for name, folder in sorted(skills.items()):
        digest.update(f"{name}\0".encode())
        for path in sorted(each for each in folder.rglob("*") if each.is_file()):
            digest.update(f"{path.relative_to(folder).as_posix()}\0".encode())
            digest.update(path.read_bytes())
    root = scratch_directory() / "plugins" / digest.hexdigest()[:PLUGIN_HASH_LENGTH]
    plugin = root / PLUGIN_NAME
    if plugin.is_dir():
        return plugin
    # Written aside and renamed, so a run never loads half a plugin.
    partial = root.with_name(f"{root.name}.{secrets.token_hex(3)}.tmp")
    for name, folder in skills.items():
        shutil.copytree(folder, partial / PLUGIN_NAME / "skills" / name)
    (partial / PLUGIN_NAME / "skills").mkdir(parents=True, exist_ok=True)
    try:
        partial.rename(root)
    except OSError:
        # Another run wrote the same plugin first.
        shutil.rmtree(partial, ignore_errors=True)
        if not plugin.is_dir():
            raise
    return plugin


def kept(tail: deque[str]) -> Callable[[str], None]:
    """A stderr callback that keeps each line in `tail` and passes it on, timed, to this process's stderr."""

    def keep(line: str) -> None:
        tail.append(line)
        sys.stderr.write(f"{datetime.now(UTC).isoformat()} claude: {line}\n")

    return keep


def without_placeholder_failure(record: logging.LogRecord) -> bool:
    """Whether an SDK log record is other than its line for a failed Claude Code process, which a run reports itself."""
    message = record.getMessage()
    return not (message.startswith(SDK_FAILURE_PREFIX) and message.endswith(SDK_STDERR_PLACEHOLDER))


async def failure_text(error: Exception, stderr: deque[str]) -> str:
    """Why a run failed; for a Claude Code process that exited, how it did and the end of what it printed."""
    # The SDK's ProcessError carries placeholder text instead of the process's stderr; a ResultError says why itself.
    if not isinstance(error, ProcessError) or isinstance(error, ResultError):
        return f"{type(error).__name__}: {error}"
    exited = f"Claude Code exited with code {error.exit_code}"
    if error.exit_code is not None and error.exit_code < 0 and os.name == "posix":
        with contextlib.suppress(ValueError):
            exited += f" ({signal.Signals(-error.exit_code).name})"
    await quiet(stderr=stderr)
    lines = list(stderr)
    if not lines:
        return f"{type(error).__name__}: {exited} and printed nothing on stderr."
    return f"{type(error).__name__}: {exited}; the end of its stderr:\n" + "\n".join(lines)


async def quiet(stderr: deque[str]) -> None:
    """Return once no line reaches `stderr` for `STDERR_QUIET_SECONDS`, or after `STDERR_QUIET_ATTEMPTS` such waits."""
    for _ in range(STDERR_QUIET_ATTEMPTS):
        lines = list(stderr)
        await asyncio.sleep(STDERR_QUIET_SECONDS)
        if list(stderr) == lines:
            return


def describe(result: ResultMessage) -> str:
    """Why a run that ended in error failed, in the runtime's own words where it gave any."""
    return "; ".join(result.errors or []) or result.result or f"The run ended {result.subtype}."


def tool_result_text(content: str | list[dict[str, Any]] | None) -> str:
    if isinstance(content, str):
        return content
    if content is None:
        return ""
    return "\n".join(part["text"] for part in content if isinstance(part.get("text"), str))


def image_block(path: Path) -> dict[str, Any]:
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    source = {"type": "base64", "media_type": IMAGE_MEDIA_TYPES[path.suffix.lower()], "data": data}
    return {"type": "image", "source": source}


def signed_in(account: dict[str, Any]) -> bool:
    """Whether the account Claude Code resolved at startup can make requests."""
    # A cloud provider authenticates with that cloud's credentials and reports no Anthropic key or token.
    if account.get("apiProvider", "firstParty") != "firstParty":
        return True
    # A Claude subscription signed in through Claude Code reports its plan, with neither a key nor a token source.
    if account.get("subscriptionType"):
        return True
    return bool(account.get("apiKeySource")) or account.get("tokenSource", "none") != "none"


def scratch_directory() -> Path:
    """Where a run without a workspace works, one directory so their sessions share one ~/.claude/projects entry."""
    return state_directory("claude")


def _agent(parent_tool_use_id: str | None) -> dict[str, Any]:
    return {} if parent_tool_use_id is None else {"agent_id": parent_tool_use_id}


def _unavailable(error: Exception) -> RealityCheckError:
    return RealityCheckError(
        code="claude-unavailable",
        message=f"The Claude Code runtime did not start: {type(error).__name__}: {error}",
        remedy="Check that ~/.claude/settings.json is valid, and reinstall reality-check with the [claude] extra, "
        "which brings the runtime.",
    )


async def _one(message: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
    yield message


async def _account() -> dict[str, Any]:
    directory = scratch_directory()
    directory.mkdir(parents=True, exist_ok=True)
    options = ClaudeAgentOptions(cwd=directory, tools=[], setting_sources=[], env=dict(TELEMETRY_OFF))
    async with ClaudeSDKClient(options=options) as client:
        info = await client.get_server_info()
    return (info or {}).get("account") or {}
