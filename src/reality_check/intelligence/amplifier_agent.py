"""Amplifier Agent implementation of the intelligence interface."""

import asyncio
import base64
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
import contextlib
from datetime import UTC
from importlib.metadata import version
import json
from typing import Any

from amplifier_agent import (
    BUILTIN_TOOLS,
    Agent,
    AgentError,
    AgentOptions,
    ContentPart,
    Event,
    ImagePart,
    OutputDelta,
    ReasoningFinal,
    Session,
    TextPart,
    Tool,
    ToolCallEvent,
    ToolContext,
    ToolFailed,
    ToolResultEvent,
    Turn,
    TurnInput,
    TurnResult,
    Usage,
    UsageEvent,
    create_agent,
    list_providers,
)

from reality_check.intelligence.events import EventLog, fresh_input, shorten
from reality_check.intelligence.interface import state_directory
from reality_check.intelligence.schemas import (
    IMAGE_MEDIA_TYPES,
    AgentEvent,
    AgentEventKind,
    AgentRequest,
    AgentResult,
    Steering,
)
from reality_check.intelligence.submission import (
    MAX_INVALID_SUBMISSIONS,
    SUBMIT_TOOL,
    resubmit_prompt,
    submission_problem,
)
from reality_check.schemas import DEFAULT_INTELLIGENCE_MODELS, RealityCheckError

# How long a cancelled turn may take to reach its terminal event before the run stops waiting for it.
DRAIN_SECONDS = 30
PROVIDERS_DOCUMENTATION = "https://github.com/microsoft/amplifier-agent/blob/v0.23.1/docs/providers.md"
# The runtime rejects arguments that break a tool's declared schema before the handler runs, and ends the turn.
# Declaring any object and validating in the handler turns a bad submission into a failure the model can retry.
PERMISSIVE_SCHEMA: dict[str, Any] = {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object"}
# Telling the model to call it exactly once makes it refuse to call it again after a failure.
SUBMIT_DESCRIPTION = """Submit your final answer when you are done.
The arguments must be one JSON object matching this JSON schema:
{schema}
If the tool reports a problem with the answer, fix the answer and call the tool again."""
# Their credentials can come from where list_providers does not look, so a missing status does not mean they fail.
UNDETECTED_CREDENTIALS = ("azure-openai", "github-copilot")


class AmplifierAgentRun:
    """One Amplifier Agent session driven in a background task from construction, one turn at a time."""

    def __init__(self, request: AgentRequest, provider: str, model: str, content: list[ContentPart]) -> None:
        self._request = request
        self._provider = provider
        self._model = model
        self._content = content
        self._log = EventLog()
        self._running: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self._session_id: str | None = request.resume
        self._turn: Turn | None = None
        self._reader: asyncio.Task[TurnResult] | None = None
        self._last_text = ""
        self._buffer: list[str] = []
        self._steering: list[str] = []
        self._finished = False
        self._cancelling = False
        self._tool_names: dict[str, str] = {}
        self._submitted: dict[str, Any] | None = None
        self._task = asyncio.create_task(self._drive())

    @property
    def session_id(self) -> str | None:
        return self._session_id

    async def running(self) -> None:
        """Return once the first turn has started; raise RealityCheckError when the run ended before that."""
        await self._running

    def events(self) -> AsyncIterator[AgentEvent]:
        return self._log.replay()

    async def steer(self, message: str) -> None:
        if self._finished or self._cancelling or self._task.done():
            raise RealityCheckError(
                code="agent-run-finished",
                message="The agent run has ended, so the steering message was not delivered.",
                remedy=f"Start a new run with resume={self._session_id!r} and the message as its prompt.",
            )
        self._steering.append(message)
        # The message is already queued for the next turn, which starts however this cancel goes.
        if self._turn is not None:
            with contextlib.suppress(Exception):
                await self._turn.cancel()

    async def cancel(self) -> None:
        if self._task.done():
            return
        self._cancelling = True
        if self._turn is not None:
            with contextlib.suppress(Exception):
                await self._turn.cancel()
        _, pending = await asyncio.wait([self._task], timeout=DRAIN_SECONDS)
        if pending and self._reader is not None:
            self._reader.cancel()
        await asyncio.wait([self._task])

    async def result(self) -> AgentResult:
        return await asyncio.shield(self._task)

    async def _drive(self) -> AgentResult:
        timeout = self._request.timeout_seconds
        agent: Agent | None = None
        session: Session | None = None
        try:
            async with asyncio.timeout(timeout):
                agent = await create_agent(self._agent_options())
                if self._request.resume is not None:
                    session = await agent.resume_session(self._request.resume)
                else:
                    session = await agent.create_session()
                self._session_id = session.info.session_id
                result = await self._turns(session)
        except TimeoutError:
            self._finished = True
            await self._drain()
            result = AgentResult(
                text=self._last_text,
                error=f"The agent did not finish within {timeout} seconds; resume session {self._session_id} to go on.",
                session_id=self._session_id,
            )
        except AgentError as error:
            self._finished = True
            result = AgentResult(text=self._last_text, error=describe(error), session_id=self._session_id)
        except Exception as error:  # an SDK or runtime failure is the caller's data, not a crash
            self._finished = True
            result = AgentResult(
                text=self._last_text, error=f"{type(error).__name__}: {error}", session_id=self._session_id
            )
        finally:
            if session is not None:
                with contextlib.suppress(Exception):
                    await session.close()
            if agent is not None:
                with contextlib.suppress(Exception):
                    await agent.close()
        if not self._running.done():
            self._running.set_exception(
                RealityCheckError(
                    code="amplifier-agent-start-failed",
                    message=f"The amplifier-agent agent provider did not start the run: {result.error}",
                    remedy="Fix what the message names, then start again.",
                )
            )
        self._flush()
        self._emit("terminal", result.error or result.text, result.model_dump(mode="json"))
        return result

    async def _turns(self, session: Session) -> AgentResult:
        schema = self._request.output_schema
        content: list[ContentPart] = self._content
        invalid = 0
        while True:
            if self._cancelling:
                return self._end(self._cancelled())
            result = await self._take_turn(session, content)
            if self._cancelling:
                return self._end(self._cancelled())
            if self._steering:
                # A steered turn was cancelled, or ended just as the message came; either way the message goes next.
                content = [TextPart(text="\n\n".join(self._steering))]
                self._steering.clear()
                continue
            if result.state != "success":
                error = describe(result.error) if result.error is not None else f"The turn ended {result.state}."
                return self._end(AgentResult(text=self._last_text, error=error, session_id=self._session_id))
            if schema is None:
                return self._end(AgentResult(text=self._last_text, session_id=self._session_id))
            problem = submission_problem(self._submitted, schema)
            if problem is None:
                return self._end(AgentResult(output=self._submitted, text=self._last_text, session_id=self._session_id))
            if invalid >= MAX_INVALID_SUBMISSIONS:
                return self._end(
                    AgentResult(
                        text=self._last_text,
                        error=f"No valid submission after {invalid} retries: {problem}",
                        session_id=self._session_id,
                    )
                )
            invalid += 1
            self._submitted = None
            content = [TextPart(text=resubmit_prompt(problem))]

    async def _take_turn(self, session: Session, content: list[ContentPart]) -> TurnResult:
        """Start one turn and wait for its terminal event; a turn with no text keeps the earlier turn's."""
        turn = await session.start_turn(TurnInput(content=content))
        self._turn = turn
        # The reader outlives a timeout of this wait, so the turn can still be drained to its terminal event.
        reader = self._reader = asyncio.create_task(self._read(turn))
        if not self._running.done():
            self._running.set_result(None)
        if self._cancelling or self._steering:
            with contextlib.suppress(Exception):
                await turn.cancel()
        await asyncio.wait([reader])
        if reader.cancelled():
            return TurnResult(state="cancelled")
        result = reader.result()
        text = "".join(part.text for part in result.content or [])
        if text:
            self._last_text = text
        return result

    async def _drain(self) -> None:
        """Cancel the turn in flight and read it to its end, so the session on disk is whole when resumed."""
        if self._turn is None or self._reader is None:
            return
        with contextlib.suppress(Exception):
            await self._turn.cancel()
        _, pending = await asyncio.wait([self._reader], timeout=DRAIN_SECONDS)
        if pending:
            self._reader.cancel()

    def _end(self, result: AgentResult) -> AgentResult:
        self._finished = True
        return result

    def _cancelled(self) -> AgentResult:
        return AgentResult(text=self._last_text, cancelled=True, session_id=self._session_id)

    def _agent_options(self) -> AgentOptions:
        request = self._request
        if request.workspace is not None:
            working_directory = request.workspace.path
        else:
            # A plain completion still gets a directory to work in; never the caller's.
            working_directory = state_directory("amplifier-agent") / "scratch"
            working_directory.mkdir(parents=True, exist_ok=True)
        tools: list[Tool | str] | None = None
        if request.output_schema is not None:
            submit = Tool(
                name=SUBMIT_TOOL,
                description=SUBMIT_DESCRIPTION.format(schema=json.dumps(request.output_schema, indent=2)),
                input_schema=PERMISSIVE_SCHEMA,
                handler=self._capture,
            )
            tools = [*BUILTIN_TOOLS, submit]
        options = AgentOptions(
            provider=self._provider,
            model=self._model,
            tools=tools,
            skills=[str(directory) for directory in request.skill_directories],
            approvals="allow",
            working_directory=working_directory,
            sessions_directory=request.session_directory or state_directory("amplifier-agent") / "sessions",
        )
        if request.reasoning_effort is not None:
            options.reasoning_effort = request.reasoning_effort
        return options

    async def _capture(self, arguments: dict[str, Any], context: ToolContext) -> str:
        """Fail a submission that breaks the schema, so the model can fix it within the turn."""
        schema = self._request.output_schema
        problem = None if schema is None else submission_problem(arguments, schema)
        if problem is not None:
            raise ToolFailed(problem)
        self._submitted = arguments
        return "Submission received."

    async def _read(self, turn: Turn) -> TurnResult:
        known: Usage | None = None
        async for event in turn.events():
            match event.payload:
                case UsageEvent(snapshot=snapshot) if _reported(snapshot):
                    known = snapshot
                case OutputDelta() as delta:
                    self._buffer.extend(part.text for part in delta.content)
                case ReasoningFinal() as reasoning if reasoning.text.strip():
                    self._flush()
                    self._emit("reasoning", reasoning.text, {}, event)
                case ToolCallEvent(call=call):
                    self._flush()
                    self._tool_names[call.call_id] = call.name
                    arguments = shorten(json.dumps(call.arguments, default=str))
                    self._emit(
                        "tool_call",
                        f"{call.name} {arguments}".strip(),
                        {
                            "tool_call_id": call.call_id,
                            "tool_name": call.name,
                            "arguments": call.arguments,
                            "source": call.source,
                        },
                        event,
                    )
                case ToolResultEvent(resolution=resolution):
                    self._flush()
                    outcome: dict[str, Any] = {
                        "tool_call_id": resolution.call_id,
                        "tool_name": self._tool_names.get(resolution.call_id, ""),
                        "success": resolution.outcome == "completed",
                        "result": resolution.content,
                    }
                    text = resolution.content or ""
                    if resolution.error is not None:
                        outcome["error"] = resolution.error.message
                        text = text or resolution.error.message
                    self._emit("tool_result", shorten(text), outcome, event)
                case TurnResult() as result:
                    self._flush()
                    # Snapshots are cumulative for the turn and empty while a call is in flight, so a turn cancelled
                    # mid-call ends with an empty one; the last that had numbers still counts what was used.
                    usage = result.usage if _reported(result.usage) else known
                    for entry in usage.entries if usage is not None else []:
                        if entry.tokens_in is None and entry.tokens_out is None and entry.cost is None:
                            continue
                        cost = (
                            None
                            if entry.cost is None
                            else {currency: float(amount) for currency, amount in entry.cost.items()}
                        )
                        data = {
                            "model": f"{entry.provider}/{entry.model}",
                            "input_tokens": entry.tokens_in,
                            # Amplifier counts cache reads, not cache writes, in its input tokens.
                            "fresh_input_tokens": fresh_input(entry.tokens_in, entry.cache_read_tokens),
                            "output_tokens": entry.tokens_out,
                            "cache_read_tokens": entry.cache_read_tokens,
                            "cache_write_tokens": entry.cache_write_tokens,
                            "cost": cost,
                            "billing": cost or {},
                        }
                        self._emit("usage", "", data, event)
                    return result
        raise RuntimeError("The turn's event stream ended without a terminal event.")

    def _flush(self) -> None:
        """Emit the reply text gathered from deltas as one message, so a reader sees whole messages."""
        text = "".join(self._buffer)
        self._buffer.clear()
        if text:
            self._emit("message", text, {})

    def _emit(self, kind: AgentEventKind, text: str, data: dict[str, Any], source: Event | None = None) -> None:
        event = AgentEvent(kind=kind, text=text, data=data)
        if source is not None and source.at is not None:
            event.time = source.at.astimezone(UTC)
        self._log.emit(event)


class AmplifierAgentIntelligence:
    """Runs agents in process through Amplifier Agent, against the provider named in the model."""

    def __init__(self, model: str = DEFAULT_INTELLIGENCE_MODELS["amplifier-agent"]) -> None:
        self.implementation = f"amplifier-agent {version('amplifier-agent')}"
        self.steering: Steering = "restart"
        self.model = model

    def preflight(self) -> None:
        provider, model = parse_model(self.model)
        # The protocol is synchronous and its callers may already run an event loop.
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(asyncio.run, _probe(provider, model)).result()

    async def start(self, request: AgentRequest) -> AmplifierAgentRun:
        provider, model = parse_model(request.model)
        if request.mcp_servers:
            raise RealityCheckError(
                code="mcp-not-supported",
                message="The amplifier-agent agent provider does not take MCP servers.",
                remedy="Use the copilot agent provider, or leave the MCP servers out.",
            )
        content: list[ContentPart] = [TextPart(text=request.prompt)]
        for path in request.images:
            data = base64.b64encode(await asyncio.to_thread(path.read_bytes)).decode("ascii")
            content.append(ImagePart(media_type=IMAGE_MEDIA_TYPES[path.suffix.lower()], data=data))
        run = AmplifierAgentRun(request, provider, model, content)
        await run.running()
        return run


def parse_model(model: str) -> tuple[str, str]:
    """Split `<provider>/<model>` on the first slash; the model id itself may hold more."""
    provider, _, name = model.partition("/")
    if not provider or not name:
        raise RealityCheckError(
            code="model-invalid",
            message="The amplifier-agent agent provider takes the model as <provider>/<model>, for instance "
            f"{DEFAULT_INTELLIGENCE_MODELS['amplifier-agent']}; got {model!r}.",
            remedy=f"Pass the model in that form; the providers are listed at {PROVIDERS_DOCUMENTATION}",
        )
    return provider, name


def describe(error: AgentError) -> str:
    """An Amplifier Agent failure in one line, with what it says to do about it."""
    return f"{error.code}: {error.message} {error.remedy}"


async def _probe(provider: str, model: str) -> None:
    record = next((each for each in await list_providers() if each.provider == provider), None)
    if record is not None and record.credentials == "missing" and provider not in UNDETECTED_CREDENTIALS:
        variables = " or ".join(record.credential_variables)
        raise RealityCheckError(
            code="amplifier-agent-unavailable",
            message=f"Amplifier Agent finds no credentials for the {provider} provider.",
            remedy=(f"Set {variables}, as " if variables else "Set up its credentials as ")
            + f"{PROVIDERS_DOCUMENTATION} describes, or pass a model of another provider as <provider>/<model>.",
        )
    try:
        agent = await create_agent(
            AgentOptions(
                provider=provider,
                model=model,
                tools=[],
                sessions_directory=state_directory("amplifier-agent") / "sessions",
            )
        )
    except AgentError as error:
        raise RealityCheckError(
            code="amplifier-agent-unavailable",
            message=f"Amplifier Agent cannot run {provider}/{model}: {describe(error)}",
            remedy=f"Set up the provider and its credentials as {PROVIDERS_DOCUMENTATION} describes, or pass another "
            "model as <provider>/<model>.",
        ) from None
    await agent.close()


def _reported(usage: Usage | None) -> bool:
    """Whether the usage holds any numbers, rather than only calls still in flight."""
    return usage is not None and any(
        entry.tokens_in is not None or entry.tokens_out is not None for entry in usage.entries
    )
