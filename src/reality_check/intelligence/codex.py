"""OpenAI Codex SDK implementation of the intelligence interface."""

import asyncio
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
import contextlib
from datetime import UTC, datetime
from importlib.metadata import version
import json
from pathlib import Path
import shutil
from typing import Any

from openai_codex import (
    ApprovalMode,
    AsyncCodex,
    AsyncThread,
    AsyncTurnHandle,
    CodexConfig,
    InputItem,
    InvalidRequestError,
    LocalImageInput,
    RunInput,
    Sandbox,
    TextInput,
)
from openai_codex.models import Notification, UnknownNotification
from openai_codex.types import (
    GetAccountResponse,
    ReasoningEffort,
    ReasoningSummary,
    TurnCompletedNotification,
    TurnStatus,
)

from reality_check.intelligence.events import EventLog, fresh_input, shorten
from reality_check.intelligence.interface import state_directory
from reality_check.intelligence.schemas import AgentEvent, AgentEventKind, AgentRequest, AgentResult, Steering
from reality_check.intelligence.submission import MAX_INVALID_SUBMISSIONS, resubmit_prompt, submission_problem
from reality_check.schemas import RealityCheckError

SIGN_IN_DOCUMENTATION = "https://developers.openai.com/codex/auth"
TELEMETRY_OFF = ("analytics.enabled=false", 'otel.metrics_exporter="none"', "feedback.enabled=false")
# How long a stopping run waits for Codex to end its turn, and then for the turn's last notifications.
DRAIN_SECONDS = 30
# Without it the runtime leaves reasoning summaries out, and they are what the activity shows of reasoning.
SUMMARY = ReasoningSummary.model_validate("detailed")
SKILLS_DIRECTORY = Path(".agents") / "skills"
# The items that are a call to a tool, rather than words, reasoning, or the turn's own bookkeeping.
TOOL_ITEMS = frozenset(
    {
        "commandExecution",
        "fileChange",
        "imageView",
        "webSearch",
        "mcpToolCall",
        "dynamicToolCall",
        "collabAgentToolCall",
        "imageGeneration",
    }
)
# The items whose tool is named by the call rather than by the item.
NAMED_BY_TOOL = frozenset({"mcpToolCall", "dynamicToolCall", "collabAgentToolCall"})
# What a call's item carries beside what the agent called it with.
CALL_RESULT_FIELDS = frozenset(
    {
        "id",
        "type",
        "status",
        "aggregatedOutput",
        "exitCode",
        "durationMs",
        "processId",
        "source",
        "result",
        "results",
        "error",
        "contentItems",
        "success",
        "agentsStates",
    }
)
FAILED_STATUSES = ("failed", "declined")
# Keywords whose values are schemas, by how they hold them; walking only these leaves instance data such as
# `default` and `enum` untouched.
SUBSCHEMA_KEYWORDS = {"items", "additionalProperties", "not", "if", "then", "else", "contains"}
SUBSCHEMA_LIST_KEYWORDS = {"anyOf", "oneOf", "allOf", "prefixItems"}
SUBSCHEMA_MAP_KEYWORDS = {"properties", "patternProperties", "$defs", "definitions"}


class CodexRun:
    """One agent in its own Codex runtime, driven in a background task from construction until its last turn ends."""

    def __init__(self, request: AgentRequest) -> None:
        self._request = request
        self._log = EventLog()
        self._session_id: str | None = request.resume
        self._thread: AsyncThread | None = None
        self._turn: AsyncTurnHandle | None = None
        # Steering that arrived as a turn ended, which goes on in a turn of its own.
        self._pending: list[str] = []
        self._text = ""
        self._total_tokens: int | None = None
        self._answered = False
        self._halting = False
        self._began = asyncio.Event()
        self._stopping = asyncio.Event()
        self.unavailable: RealityCheckError | None = None
        self._task = asyncio.create_task(self._drive())

    @property
    def session_id(self) -> str | None:
        return self._session_id

    async def running(self) -> None:
        """Return once the first turn is sent, or once the run ended trying."""
        await self._began.wait()

    def events(self) -> AsyncIterator[AgentEvent]:
        return self._log.replay()

    async def steer(self, message: str) -> None:
        if self._answered or self._task.done() or self._turn is None:
            raise self._ended()
        try:
            await self._turn.steer(message)
        except InvalidRequestError:
            # The turn ended as the message went out; unless the run did too, it goes on in a turn of its own.
            if self._answered or self._task.done():
                raise self._ended() from None
            self._pending.append(message)
        except Exception as error:
            raise RealityCheckError(
                code="agent-steer-failed",
                message=f"The steering message was not delivered: {type(error).__name__}: {error}",
                remedy="Send it again, or cancel the run and resume its session with the message as the prompt.",
            ) from error

    async def cancel(self) -> None:
        self._stopping.set()
        await asyncio.wait([self._task])

    async def result(self) -> AgentResult:
        return await asyncio.shield(self._task)

    async def _drive(self) -> AgentResult:
        result: AgentResult | None = None
        try:
            # Opened and closed in this one task, since closing the runtime ends what its turns started.
            async with AsyncCodex(CodexConfig(config_overrides=TELEMETRY_OFF)) as codex:
                result = await self._run(codex)
        except Exception as error:
            if result is None:
                self.unavailable = RealityCheckError(
                    code="codex-unavailable",
                    message=f"The Codex runtime did not start: {type(error).__name__}: {error}",
                    remedy="Check that ~/.codex/config.toml is valid, and reinstall reality-check with the [codex] "
                    "extra, which brings the runtime.",
                )
                result = AgentResult(error=str(self.unavailable), session_id=self._session_id)
        finally:
            self._began.set()
        self._emit("terminal", result.error or result.text, result.model_dump(mode="json"))
        return result

    async def _run(self, codex: AsyncCodex) -> AgentResult:
        timeout = self._request.timeout_seconds
        stopping = asyncio.create_task(self._stopping.wait())
        reading: asyncio.Task[AgentResult] | None = None
        try:
            async with asyncio.timeout(timeout):
                await self._open(codex)
                self._began.set()
                reading = asyncio.create_task(self._turns())
                await asyncio.wait([reading, stopping], return_when=asyncio.FIRST_COMPLETED)
            if self._stopping.is_set():
                await self._halt(reading)
                return AgentResult(text=self._text, cancelled=True, session_id=self._session_id)
            return reading.result()
        except TimeoutError:
            await self._halt(reading)
            return AgentResult(
                text=self._text,
                error=f"The agent did not finish within {timeout} seconds; resume session {self._session_id} to go on.",
                session_id=self._session_id,
            )
        except Exception as error:  # an SDK or runtime failure is the caller's data, not a crash
            return AgentResult(text=self._text, error=f"{type(error).__name__}: {error}", session_id=self._session_id)
        finally:
            stopping.cancel()
            if reading is not None and not reading.done():
                reading.cancel()

    async def _open(self, codex: AsyncCodex) -> None:
        request = self._request
        cwd = workspace(request)
        await asyncio.to_thread(copy_skills, request.skill_directories, cwd)
        options: dict[str, Any] = {
            "cwd": str(cwd),
            "model": request.model,
            # Not sandboxed, since checking software means running it and the tools it needs; the prompt bounds the
            # agent. Nothing asks for approval, as no one is there to give it.
            "sandbox": Sandbox.full_access,
            "approval_mode": ApprovalMode.deny_all,
            "config": {
                "model_reasoning_summary": "detailed",
                # The workspace's AGENTS.md is written for whoever develops there, not for an agent checking it.
                "project_doc_max_bytes": 0,
                # Otherwise a writable thread in an untrusted project records it as trusted in ~/.codex/config.toml.
                "projects": {str(cwd): {"trust_level": "trusted"}},
            },
        }
        if request.resume is not None:
            self._thread = await codex.thread_resume(request.resume, **options)
        else:
            self._thread = await codex.thread_start(**options)
        self._session_id = self._thread.id
        content: list[InputItem] = [TextInput(request.initial_message)]
        content.extend(LocalImageInput(str(path)) for path in request.images)
        await self._begin(content)

    async def _begin(self, content: RunInput) -> None:
        if self._thread is None:
            raise RuntimeError("A turn began before its thread.")
        request = self._request
        options: dict[str, Any] = {"summary": SUMMARY}
        if request.reasoning_effort is not None:
            options["effort"] = ReasoningEffort(request.reasoning_effort)
        if request.output_schema is not None:
            options["output_schema"] = to_strict(request.output_schema)
        self._turn = await self._thread.turn(content, **options)

    async def _turns(self) -> AgentResult:
        schema = self._request.output_schema
        invalid = 0
        while True:
            completed = await self._read_turn()
            await self._keep_session()
            turn = completed.turn
            if turn.status == TurnStatus.completed and self._pending and not self._halting:
                await self._begin(self._pending.pop(0))
                continue
            if turn.status == TurnStatus.interrupted or self._halting:
                return self._finish(AgentResult(text=self._text, cancelled=True, session_id=self._session_id))
            if turn.status != TurnStatus.completed:
                reason = turn.error.message if turn.error is not None else f"The turn ended {turn.status.value}."
                return self._finish(AgentResult(text=self._text, error=reason, session_id=self._session_id))
            if schema is None:
                return self._finish(AgentResult(text=self._text, session_id=self._session_id))
            output, problem = parse_answer(self._text, schema)
            if problem is None:
                return self._finish(AgentResult(output=output, text=self._text, session_id=self._session_id))
            if invalid >= MAX_INVALID_SUBMISSIONS:
                return self._finish(
                    AgentResult(
                        text=self._text,
                        error=f"No valid submission after {invalid} retries: {problem}",
                        session_id=self._session_id,
                    )
                )
            invalid += 1
            await self._begin(resubmit_prompt(problem))

    async def _read_turn(self) -> TurnCompletedNotification:
        if self._turn is None:
            raise RuntimeError("Codex was read from before a turn began.")
        completed: TurnCompletedNotification | None = None
        async for notification in self._turn.stream():
            if isinstance(notification.payload, TurnCompletedNotification):
                completed = notification.payload
            self._note(notification)
        if completed is None:
            raise RuntimeError("Codex ended the turn without saying how.")
        return completed

    def _finish(self, result: AgentResult) -> AgentResult:
        self._answered = True
        return result

    async def _halt(self, reading: asyncio.Task[AgentResult] | None) -> None:
        """Interrupt the turn in flight and let it settle, so the session is whole when resumed."""
        self._halting = True
        if self._turn is not None and not self._answered:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self._turn.interrupt(), DRAIN_SECONDS)
        if reading is not None:
            await asyncio.wait([reading], timeout=DRAIN_SECONDS)

    async def _keep_session(self) -> None:
        """Copy the thread's rollout to the session directory, where it can be read without the runtime."""
        directory = self._request.session_directory
        if directory is None or self._thread is None:
            return
        rollout = (await self._thread.read()).thread.path
        if rollout is None:
            return
        directory.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(shutil.copyfile, rollout, directory / f"{self._thread.id}.jsonl")

    def _note(self, notification: Notification) -> None:
        method = notification.method
        data = as_data(notification)
        if method == "thread/tokenUsage/updated":
            self._note_usage(data)
            return
        item = data.get("item")
        if not isinstance(item, dict):
            return
        kind = item.get("type")
        time = _time(data)
        if method == "item/started" and kind in TOOL_ITEMS:
            name, arguments = _name(item), _input(item)
            self._emit(
                "tool_call",
                f"{name} {shorten(json.dumps(arguments, default=str))}".strip(),
                {"tool_call_id": item.get("id"), "tool_name": name, "arguments": arguments, **_agent(item)},
                time,
            )
        elif method != "item/completed":
            return
        elif kind == "agentMessage":
            text = str(item.get("text") or "")
            if text:
                self._text = text
                self._emit("message", text, {}, time)
        elif kind == "reasoning":
            summary = "\n\n".join(part for part in item.get("summary") or [] if isinstance(part, str)).strip()
            if summary:
                self._emit("reasoning", summary, {"reasoning_id": item.get("id")}, time)
        elif kind in TOOL_ITEMS:
            output = _output(item)
            failed = _failed(item)
            outcome: dict[str, Any] = {
                "tool_call_id": item.get("id"),
                "tool_name": _name(item),
                "success": not failed,
                "result": output,
                **_agent(item),
            }
            if failed:
                outcome["error"] = _failure(item, output)
            self._emit("tool_result", shorten(output or outcome.get("error", "")), outcome, time)

    def _note_usage(self, data: dict[str, Any]) -> None:
        usage = data.get("tokenUsage")
        if not isinstance(usage, dict):
            return
        total = usage.get("total") or {}
        last = usage.get("last") or {}
        # Codex repeats the count for one model call, and only the session's total moves when a new call is counted.
        if total.get("totalTokens") == self._total_tokens:
            return
        self._total_tokens = total.get("totalTokens")
        self._emit(
            "usage",
            "",
            {
                "model": self._request.model,
                "input_tokens": last.get("inputTokens"),
                "fresh_input_tokens": fresh_input(
                    last.get("inputTokens"), last.get("cachedInputTokens"), last.get("cacheWriteInputTokens")
                ),
                "output_tokens": last.get("outputTokens"),
                "cache_read_tokens": last.get("cachedInputTokens"),
                "cache_write_tokens": last.get("cacheWriteInputTokens"),
                "reasoning_tokens": last.get("reasoningOutputTokens"),
            },
        )

    def _ended(self) -> RealityCheckError:
        return RealityCheckError(
            code="agent-run-finished",
            message="The agent run has ended, so the steering message was not delivered.",
            remedy=f"Start a new run with resume={self._session_id!r} and the message as its prompt.",
        )

    def _emit(self, kind: AgentEventKind, text: str, data: dict[str, Any], time: datetime | None = None) -> None:
        event = AgentEvent(kind=kind, text=text, data=data)
        if time is not None:
            event.time = time
        self._log.emit(event)


class CodexIntelligence:
    """Runs agents through a Codex runtime on this machine, with the user's Codex sign-in and configuration."""

    def __init__(self) -> None:
        self.implementation = f"openai-codex {version('openai-codex')}"
        self.steering: Steering = "mid-turn"

    def preflight(self) -> None:
        try:
            # In a thread of its own, since a caller in an event loop cannot run another in its own thread.
            with ThreadPoolExecutor(max_workers=1) as executor:
                account = executor.submit(_account).result()
        except Exception as error:  # whatever stops the runtime from starting, the remedy is the same
            raise RealityCheckError(
                code="codex-unavailable",
                message=f"The Codex runtime did not start: {type(error).__name__}: {error}",
                remedy="Check that ~/.codex/config.toml is valid, and reinstall reality-check with the [codex] extra, "
                "which brings the runtime.",
            ) from None
        if account.account is None and account.requires_openai_auth:
            raise RealityCheckError(
                code="codex-not-signed-in",
                message="Codex is not signed in.",
                remedy="Install the Codex CLI and run `codex login`, with ChatGPT or an API key as "
                f"{SIGN_IN_DOCUMENTATION} describes.",
            )

    async def start(self, request: AgentRequest) -> CodexRun:
        if request.mcp_servers:
            raise RealityCheckError(
                code="mcp-not-supported",
                message="The codex agent provider does not take MCP servers.",
                remedy="Use the copilot agent provider for a run with MCP servers, or leave them out.",
            )
        run = CodexRun(request)
        await run.running()
        if run.unavailable is not None:
            raise run.unavailable
        return run


def workspace(request: AgentRequest) -> Path:
    """Where the agent works: the request's workspace, else one fixed directory that is never the caller's."""
    if request.workspace is not None:
        return request.workspace.path.resolve()
    directory = state_directory("codex")
    directory.mkdir(parents=True, exist_ok=True)
    return directory.resolve()


def copy_skills(skill_directories: list[Path], cwd: Path) -> None:
    """Copy each skill into the project skills Codex finds under `cwd`.

    Codex takes no skill directories, only the ones it finds itself. Existing copies are overwritten and nothing is
    deleted, since checks running at the same time in the same workspace may be reading them.
    """
    for directory in skill_directories:
        if not directory.is_dir():
            continue
        for skill in sorted(directory.iterdir()):
            if (skill / "SKILL.md").is_file():
                shutil.copytree(skill, cwd / SKILLS_DIRECTORY / skill.name, dirs_exist_ok=True)


def as_data(notification: Notification) -> dict[str, Any]:
    """The notification's payload as Codex gave it, in JSON's types and names."""
    payload = notification.payload
    if isinstance(payload, UnknownNotification):
        return dict(payload.params)
    # Some of the SDK's defaults are plain strings where it declares enums; they serialize right, but warn.
    return payload.model_dump(mode="json", by_alias=True, exclude_none=True, warnings=False)


def parse_answer(text: str, schema: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """The final message as output conforming to `schema`, or why it is not acceptable."""
    try:
        answer = json.loads(text)
    except json.JSONDecodeError as error:
        return None, f"the final message is not JSON ({error.msg})"
    if not isinstance(answer, dict):
        return None, "the final message is not a JSON object"
    answer = without_added_nulls(answer, schema, schema)
    problem = submission_problem(answer, schema)
    return (answer, None) if problem is None else (None, problem)


def to_strict(schema: dict[str, Any]) -> dict[str, Any]:
    """`schema` in the form the API enforces: every property required, no others allowed.

    A property that was optional becomes nullable instead, so the model can still leave it out by answering null;
    `without_added_nulls` maps those nulls back to absent keys.
    """
    strict: dict[str, Any] = {}
    for keyword, value in schema.items():
        if keyword in SUBSCHEMA_KEYWORDS and isinstance(value, dict):
            strict[keyword] = to_strict(value)
        elif keyword in SUBSCHEMA_LIST_KEYWORDS and isinstance(value, list):
            strict[keyword] = [to_strict(item) if isinstance(item, dict) else item for item in value]
        elif keyword in SUBSCHEMA_MAP_KEYWORDS and isinstance(value, dict):
            strict[keyword] = {
                name: to_strict(item) if isinstance(item, dict) else item for name, item in value.items()
            }
        else:
            strict[keyword] = value
    if strict.get("type") == "object" or "properties" in strict:
        properties: dict[str, Any] = strict.get("properties", {})
        required = set(strict.get("required", []))
        strict["properties"] = {
            name: item if name in required else _nullable(item) for name, item in properties.items()
        }
        strict["required"] = list(properties)
        strict["additionalProperties"] = False
    return strict


def without_added_nulls(value: Any, schema: dict[str, Any], root: dict[str, Any]) -> Any:
    """`value` without the nulls `to_strict` let the model give for properties `schema` leaves optional."""
    if "$ref" in schema:
        schema = _resolve(root, schema["$ref"])
    if isinstance(value, dict):
        properties: dict[str, Any] = schema.get("properties", {})
        required = set(schema.get("required", []))
        return {
            name: without_added_nulls(item, properties.get(name, {}), root)
            for name, item in value.items()
            if item is not None or name not in properties or name in required
        }
    if isinstance(value, list):
        items = schema.get("items", {})
        return [without_added_nulls(item, items if isinstance(items, dict) else {}, root) for item in value]
    return value


def _nullable(schema: Any) -> dict[str, Any]:
    if isinstance(schema, dict) and {"type": "null"} in schema.get("anyOf", []):
        return schema
    return {"anyOf": [schema, {"type": "null"}]}


def _resolve(root: dict[str, Any], reference: str) -> dict[str, Any]:
    node: Any = root
    for part in reference.removeprefix("#/").split("/"):
        node = node[part]
    return node


def _time(data: dict[str, Any]) -> datetime | None:
    milliseconds = data.get("completedAtMs", data.get("startedAtMs"))
    return datetime.fromtimestamp(milliseconds / 1000, UTC) if isinstance(milliseconds, int) else None


def _agent(item: dict[str, Any]) -> dict[str, str]:
    """The sub-agents a collab tool call speaks to, by their thread ids."""
    if item.get("type") != "collabAgentToolCall":
        return {}
    receivers = [receiver for receiver in item.get("receiverThreadIds") or [] if isinstance(receiver, str)]
    return {"agent_id": ", ".join(receivers)} if receivers else {}


def _name(item: dict[str, Any]) -> str:
    kind = str(item.get("type", ""))
    return str(item.get("tool") or kind) if kind in NAMED_BY_TOOL else kind


def _command(item: dict[str, Any]) -> str:
    """The command as the agent wrote it, without the shell Codex wraps it in."""
    actions = [
        action["command"]
        for action in item.get("commandActions") or []
        if isinstance(action, dict) and isinstance(action.get("command"), str)
    ]
    return " && ".join(actions) if actions else str(item.get("command", ""))


def _input(item: dict[str, Any]) -> dict[str, Any]:
    """What the agent called the tool with."""
    match item.get("type"):
        case "commandExecution":
            return {"command": _command(item), "cwd": item.get("cwd")}
        case "mcpToolCall" | "dynamicToolCall":
            arguments = item.get("arguments")
            return arguments if isinstance(arguments, dict) else {"arguments": arguments}
    return {key: value for key, value in item.items() if key not in CALL_RESULT_FIELDS}


def _output(item: dict[str, Any]) -> str:
    """What came back, as text with any images left out."""
    match item.get("type"):
        case "commandExecution":
            return str(item.get("aggregatedOutput") or "")
        case "mcpToolCall":
            error = item.get("error")
            if isinstance(error, dict):
                return str(error.get("message", ""))
            result = item.get("result")
            return _text(result.get("content") if isinstance(result, dict) else None)
        case "dynamicToolCall":
            return _text(item.get("contentItems"))
    return ""


def _failed(item: dict[str, Any]) -> bool:
    exit_code = item.get("exitCode")
    return (
        item.get("status") in FAILED_STATUSES
        or (isinstance(exit_code, int) and exit_code != 0)
        or isinstance(item.get("error"), dict)
        or item.get("success") is False
    )


def _failure(item: dict[str, Any], output: str) -> str:
    """Why the call failed, in the tool's own words where it gave any."""
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if lines:
        # A command prints its error last, after whatever it printed on the way.
        return lines[-1] if item.get("type") == "commandExecution" else lines[0]
    exit_code = item.get("exitCode")
    return f"Exited with code {exit_code}" if isinstance(exit_code, int) else f"The call ended {item.get('status')}."


def _text(content: Any) -> str:
    if not isinstance(content, list):
        return ""
    return "\n".join(part["text"] for part in content if isinstance(part, dict) and isinstance(part.get("text"), str))


def _account() -> GetAccountResponse:
    async def read() -> GetAccountResponse:
        async with AsyncCodex(CodexConfig(config_overrides=TELEMETRY_OFF)) as codex:
            return await codex.account()

    return asyncio.run(read())
