"""Drives the Amplifier Agent adapter with the SDK faked, so neither a provider key nor a network is needed."""

import asyncio
import base64
from collections.abc import AsyncIterator, Callable, Coroutine
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

import pytest

pytest.importorskip("amplifier_agent")

from amplifier_agent import (
    BUILTIN_TOOLS,
    AgentError,
    AgentOptions,
    ApprovalRequest,
    ApprovalRequestEvent,
    Event,
    ImagePart,
    OutputDelta,
    Progress,
    ProviderRecord,
    ReasoningFinal,
    SessionRecord,
    TextPart,
    Tool,
    ToolCall,
    ToolCallEvent,
    ToolContext,
    ToolFailed,
    ToolResolution,
    ToolResultEvent,
    TurnInput,
    TurnResult,
    Usage,
    UsageEntry,
    UsageEvent,
)

from reality_check.intelligence import amplifier_agent as adapter
from reality_check.intelligence.amplifier_agent import AmplifierAgentIntelligence, parse_model
from reality_check.intelligence.schemas import AgentEvent, AgentRequest, HostWorkspace, McpServer
from reality_check.schemas import RealityCheckError

SESSION = "fake-session"
MODEL = "openai/gpt-6.1-sol"
SCHEMA = {
    "type": "object",
    "properties": {"score": {"type": "integer", "minimum": 0, "maximum": 100}},
    "required": ["score"],
    "additionalProperties": False,
}


def agent_error(code: str = "provider_failed") -> AgentError:
    return AgentError(code=code, category="provider", message="The provider refused.", remedy="Check the key.")


class FakeTurn:
    """One turn whose events a script pushes, ending at the first TurnResult."""

    def __init__(self, world: "FakeWorld", options: AgentOptions, number: int) -> None:
        self.world = world
        self.options = options
        self.number = number
        self.cancelled = asyncio.Event()
        self.ended = False
        self._queue: asyncio.Queue[Any] = asyncio.Queue()
        self._sequence = 0

    def push(self, *payloads: Any) -> None:
        for payload in payloads:
            self._queue.put_nowait(payload)

    def finish(
        self,
        state: Literal["success", "failure", "rejected", "cancelled"] = "success",
        text: str = "",
        error: AgentError | None = None,
    ) -> None:
        content = [TextPart(text=text)] if text else None
        self.push(TurnResult(state=state, content=content, error=error, usage=self.world.usage))

    async def submit(self, arguments: dict[str, Any]) -> None:
        """Call the submit tool the way the runtime does, reporting its resolution as events."""
        tool = self.options.tools[-1] if self.options.tools else None
        assert isinstance(tool, Tool)
        call_id = f"submit-{self.number}-{self._sequence}"
        self.push(ToolCallEvent(call=ToolCall(call_id=call_id, name=tool.name, source="caller", arguments=arguments)))
        try:
            reply = await tool.handler(arguments, ToolContext(call_id=call_id))
        except ToolFailed as failure:
            error = AgentError(code="tool_failed", category="tool", message=str(failure), remedy="")
            self.push(ToolResultEvent(resolution=ToolResolution(call_id=call_id, outcome="failed", error=error)))
            return
        assert isinstance(reply, str)
        self.push(ToolResultEvent(resolution=ToolResolution(call_id=call_id, outcome="completed", content=reply)))

    async def events(self) -> AsyncIterator[Event]:
        while True:
            payload = await self._queue.get()
            self._sequence += 1
            self.ended = isinstance(payload, TurnResult)
            yield Event("turn-events/1", SESSION, f"turn-{self.number}", self._sequence, "event", payload)
            if self.ended:
                return

    async def cancel(self) -> None:
        self.world.cancels += 1
        self.cancelled.set()


Script = Callable[[FakeTurn], Coroutine[Any, Any, None]]


class FakeWorld:
    """Stands in for the SDK and records what the adapter asked of it."""

    def __init__(self, *scripts: Script) -> None:
        self.scripts = list(scripts)
        self.options: list[AgentOptions] = []
        self.inputs: list[TurnInput] = []
        self.turns: list[FakeTurn] = []
        self.calls: list[str] = []
        self.cancels = 0
        self.failure: Exception | None = None
        self.turn_failure: Exception | None = None
        self.usage: Usage | None = None
        self.providers: list[ProviderRecord] = []
        self._tasks: set[asyncio.Task[None]] = set()

    async def create_agent(self, options: AgentOptions) -> Any:
        self.calls.append("create_agent")
        self.options.append(options)
        if self.failure is not None:
            raise self.failure
        world = self

        class Session:
            info = SessionRecord(session_id=SESSION, persistence="durable", provider="openai", model="gpt-6.1-sol")

            async def start_turn(self, turn_input: TurnInput) -> FakeTurn:
                world.calls.append("start_turn")
                if world.turns and not world.turns[-1].ended:
                    raise AgentError(code="busy", category="state", message="A turn is active.", remedy="")
                if world.turn_failure is not None and world.turns:
                    raise world.turn_failure
                world.inputs.append(turn_input)
                turn = FakeTurn(world, options, len(world.turns))
                world.turns.append(turn)
                task = asyncio.create_task(world.scripts.pop(0)(turn))
                world._tasks.add(task)
                return turn

            async def close(self) -> None:
                world.calls.append("session.close")

        class Agent:
            async def create_session(self) -> Session:
                world.calls.append("create_session")
                return Session()

            async def resume_session(self, session_id: str) -> Session:
                world.calls.append(f"resume_session {session_id}")
                session = Session()
                session.info = SessionRecord(session_id, "durable", "openai", "gpt-6.1-sol")
                return session

            async def close(self) -> None:
                world.calls.append("agent.close")

        return Agent()

    async def list_providers(self) -> list[ProviderRecord]:
        return self.providers


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Callable[..., FakeWorld]:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

    def install(*scripts: Script) -> FakeWorld:
        fake = FakeWorld(*scripts)
        monkeypatch.setattr(adapter, "create_agent", fake.create_agent)
        monkeypatch.setattr(adapter, "list_providers", fake.list_providers)
        return fake

    return install


def answers(*deltas: str) -> Script:
    async def script(turn: FakeTurn) -> None:
        turn.push(*(OutputDelta(content=[TextPart(text=delta)]) for delta in deltas))
        turn.finish(text="".join(deltas))

    return script


async def keeps_working(turn: FakeTurn) -> None:
    turn.push(OutputDelta(content=[TextPart(text="Working.")]))
    await turn.cancelled.wait()
    error = AgentError(code="turn_cancelled", category="cancelled", message="The caller cancelled the turn.", remedy="")
    turn.finish("cancelled", "Working.", error)


async def finishes_anyway(turn: FakeTurn) -> None:
    await turn.cancelled.wait()
    turn.finish(text="Already done.")


def submits(*attempts: dict[str, Any], text: str = "") -> Script:
    async def script(turn: FakeTurn) -> None:
        for arguments in attempts:
            await turn.submit(arguments)
        turn.finish(text=text)

    return script


def request(workspace: Path | None = None, **fields: Any) -> AgentRequest:
    return AgentRequest(
        initial_message="Do the work.",
        model=MODEL,
        workspace=HostWorkspace(path=workspace) if workspace is not None else None,
        timeout_seconds=60,
        **fields,
    )


async def collect(run: adapter.AmplifierAgentRun) -> list[AgentEvent]:
    return [each async for each in run.events()]


def texts(turn_input: TurnInput) -> list[str]:
    return [part.text for part in turn_input.content if isinstance(part, TextPart)]


async def test_the_agent_gets_the_split_model_workspace_sessions_and_skills_and_keeps_the_built_in_tools(
    world: Callable[..., FakeWorld], tmp_path: Path
) -> None:
    fake = world(answers("done"))

    run = await AmplifierAgentIntelligence().start(
        request(
            tmp_path,
            reasoning_effort="max",
            skill_directories=[tmp_path / "skills", tmp_path / "more"],
            session_directory=tmp_path / "session",
        )
    )
    known_once_started = run.session_id
    result = await run.result()

    assert known_once_started == SESSION
    assert (result.text, result.error, result.session_id) == ("done", None, SESSION)
    [options] = fake.options
    assert (options.provider, options.model, options.reasoning_effort) == ("openai", "gpt-6.1-sol", "max")
    assert options.working_directory == tmp_path
    assert options.sessions_directory == tmp_path / "session"
    assert options.skills == [str(tmp_path / "skills"), str(tmp_path / "more")]
    assert options.approvals == "allow"
    assert options.tools is None
    assert texts(fake.inputs[0]) == ["Do the work."]
    assert fake.calls[-2:] == ["session.close", "agent.close"]


async def test_without_effort_workspace_or_session_directory_the_state_directory_is_used(
    world: Callable[..., FakeWorld], tmp_path: Path
) -> None:
    fake = world(answers("done"))

    await (await AmplifierAgentIntelligence().start(request(reasoning_effort=None))).result()

    [options] = fake.options
    state = tmp_path / "state" / "reality-check" / "amplifier-agent"
    assert options.reasoning_effort is None
    assert options.working_directory == state / "scratch"
    assert (state / "scratch").is_dir()
    assert options.sessions_directory == state / "sessions"
    assert options.skills == []


async def test_an_output_schema_adds_a_permissive_submit_tool_describing_the_schema_beside_the_built_in_ones(
    world: Callable[..., FakeWorld],
) -> None:
    fake = world(submits({"score": 80}, text="Graded."))

    result = await (await AmplifierAgentIntelligence().start(request(output_schema=SCHEMA))).result()

    assert (result.output, result.text, result.error) == ({"score": 80}, "Graded.", None)
    tools = fake.options[0].tools
    assert tools is not None
    assert tools[:-1] == list(BUILTIN_TOOLS)
    submit = tools[-1]
    assert isinstance(submit, Tool)
    assert submit.name == "submit"
    assert submit.input_schema == {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object"}
    assert '"maximum": 100' in submit.description
    assert "call the tool again" in submit.description
    assert "exactly once" not in submit.description


@pytest.mark.parametrize("model", ["gpt-6.1-sol", "openai/", "/gpt-6.1-sol"])
async def test_a_model_without_a_provider_is_refused_before_an_agent(
    world: Callable[..., FakeWorld], model: str
) -> None:
    fake = world()

    with pytest.raises(RealityCheckError) as failure:
        await AmplifierAgentIntelligence().start(request().model_copy(update={"model": model}))

    assert failure.value.code == "model-invalid"
    assert "<provider>/<model>" in failure.value.message
    assert "v0.25.0/docs/providers.md" in failure.value.remedy
    assert fake.calls == []


def test_the_model_splits_on_the_first_slash_only() -> None:
    assert parse_model("chat-completions/org/model") == ("chat-completions", "org/model")


async def test_mcp_servers_are_refused(world: Callable[..., FakeWorld]) -> None:
    fake = world()

    with pytest.raises(RealityCheckError) as failure:
        await AmplifierAgentIntelligence().start(request(mcp_servers={"dtu": McpServer(command="dtu")}))

    assert failure.value.code == "mcp-not-supported"
    assert failure.value.message == "The amplifier-agent agent provider does not take MCP servers."
    assert fake.calls == []


async def test_images_are_inline_base64_parts_on_the_first_turn_only(
    world: Callable[..., FakeWorld], tmp_path: Path
) -> None:
    image = tmp_path / "shot.JPG"
    image.write_bytes(b"\xff\xd8 not really a jpeg")
    fake = world(submits(), submits({"score": 1}))

    await (await AmplifierAgentIntelligence().start(request(images=[image], output_schema=SCHEMA))).result()

    first, second = fake.inputs
    text, picture = first.content
    assert text == TextPart(text="Do the work.")
    assert picture == ImagePart(media_type="image/jpeg", data=base64.b64encode(image.read_bytes()).decode())
    assert all(isinstance(part, TextPart) for part in second.content)


async def test_deltas_become_whole_messages_around_reasoning_and_tools_and_usage_comes_from_the_terminal(
    world: Callable[..., FakeWorld],
) -> None:
    async def script(turn: FakeTurn) -> None:
        empty = Usage(entries=[UsageEntry(provider="openai", model="gpt-6.1-sol")])
        turn.push(
            UsageEvent(snapshot=empty),
            ReasoningFinal(text=""),
            OutputDelta(content=[TextPart(text="Let me ")]),
            OutputDelta(content=[TextPart(text="look.")]),
            ReasoningFinal(text="Think."),
            ToolCallEvent(call=ToolCall(call_id="1", name="bash", source="built-in", arguments={"command": "ls"})),
            ApprovalRequestEvent(request=ApprovalRequest(request_id="a", summary="bash")),
            Progress(data={"context": {"compacted": True}}),
            ToolResultEvent(resolution=ToolResolution(call_id="1", outcome="completed", content="x" * 2000)),
            UsageEvent(snapshot=empty),
            OutputDelta(content=[TextPart(text="Done")]),
            OutputDelta(content=[TextPart(text=".")]),
        )
        turn.finish(text="Let me look.Done.")

    fake = world(script)
    fake.usage = Usage(
        entries=[
            UsageEntry(
                provider="openai",
                model="gpt-6.1-sol",
                tokens_in=10,
                tokens_out=2,
                cache_read_tokens=4,
                cache_write_tokens=0,
                cost={"USD": Decimal("0.0125")},
            )
        ]
    )

    run = await AmplifierAgentIntelligence().start(request())
    events = await collect(run)

    kinds = [each.kind for each in events]
    assert kinds == ["message", "reasoning", "tool_call", "tool_result", "message", "usage", "terminal"]
    said, thought, call, outcome, done, usage, terminal = events
    assert (said.text, thought.text, done.text) == ("Let me look.", "Think.", "Done.")
    assert call.text == 'bash {"command": "ls"}'
    assert call.data == {"tool_call_id": "1", "tool_name": "bash", "arguments": {"command": "ls"}, "source": "built-in"}
    assert outcome.data == {"tool_call_id": "1", "tool_name": "bash", "success": True, "result": "x" * 2000}
    assert len(outcome.text) < 600
    assert usage.data == {
        "model": "openai/gpt-6.1-sol",
        "input_tokens": 10,
        "fresh_input_tokens": 6,
        "output_tokens": 2,
        "cache_read_tokens": 4,
        "cache_write_tokens": 0,
        "cost": {"USD": 0.0125},
        "billing": {"USD": 0.0125},
    }
    assert terminal.text == "Let me look.Done."
    assert terminal.data == (await run.result()).model_dump(mode="json")
    assert all(each.time.tzinfo is not None for each in events)
    assert await collect(run) == events


async def test_a_turn_ending_with_empty_usage_reports_the_last_snapshot_that_had_numbers(
    world: Callable[..., FakeWorld],
) -> None:
    def snapshot(tokens_in: int | None) -> Usage:
        return Usage(entries=[UsageEntry(provider="openai", model="gpt-6.1-sol", tokens_in=tokens_in, tokens_out=None)])

    async def script(turn: FakeTurn) -> None:
        turn.push(
            UsageEvent(snapshot=snapshot(None)), UsageEvent(snapshot=snapshot(7)), UsageEvent(snapshot=snapshot(None))
        )
        turn.finish(state="cancelled")

    fake = world(script)
    fake.usage = snapshot(None)

    run = await AmplifierAgentIntelligence().start(request())
    events = await collect(run)

    assert [each.data["input_tokens"] for each in events if each.kind == "usage"] == [7]


async def test_a_failed_tool_result_carries_its_error(world: Callable[..., FakeWorld]) -> None:
    async def script(turn: FakeTurn) -> None:
        error = AgentError(code="tool_failed", category="tool", message="no such file", remedy="")
        turn.push(
            ToolCallEvent(call=ToolCall(call_id="1", name="read_file", source="built-in", arguments={"path": "z"})),
            ToolResultEvent(resolution=ToolResolution(call_id="1", outcome="failed", error=error)),
        )
        turn.finish(text="Gone.")

    world(script)

    _, failure, *_ = await collect(await AmplifierAgentIntelligence().start(request()))

    assert failure.text == "no such file"
    assert failure.data == {
        "tool_call_id": "1",
        "tool_name": "read_file",
        "success": False,
        "result": None,
        "error": "no such file",
    }


async def test_steering_cancels_the_turn_and_sends_the_message_as_the_next_turn_of_the_same_session(
    world: Callable[..., FakeWorld],
) -> None:
    fake = world(keeps_working, answers("Went left."))

    run = await AmplifierAgentIntelligence().start(request())
    await run.steer("Go left.")
    result = await run.result()

    assert (result.text, result.error, result.cancelled) == ("Went left.", None, False)
    assert fake.cancels == 1
    assert [texts(each) for each in fake.inputs] == [["Do the work."], ["Go left."]]
    assert fake.calls.count("create_session") == 1
    assert [each.kind for each in await collect(run)] == ["message", "message", "terminal"]


async def test_a_steer_arriving_as_the_turn_ends_runs_as_the_next_turn(world: Callable[..., FakeWorld]) -> None:
    fake = world(finishes_anyway, answers("Also checked the docs."))

    run = await AmplifierAgentIntelligence().start(request())
    await run.steer("Check the docs too.")
    result = await run.result()

    assert result.text == "Also checked the docs."
    assert [texts(each) for each in fake.inputs] == [["Do the work."], ["Check the docs too."]]


async def test_steering_after_the_run_ended_is_refused(world: Callable[..., FakeWorld]) -> None:
    world(answers("done"))

    run = await AmplifierAgentIntelligence().start(request())
    await run.result()

    with pytest.raises(RealityCheckError) as failure:
        await run.steer("Too late.")

    assert failure.value.code == "agent-run-finished"
    assert SESSION in failure.value.remedy


async def test_cancel_cancels_the_turn_and_drains_it_so_the_session_can_be_resumed(
    world: Callable[..., FakeWorld],
) -> None:
    fake = world(keeps_working)

    run = await AmplifierAgentIntelligence().start(request())
    await run.cancel()
    result = await run.result()

    assert (result.cancelled, result.error, result.session_id, result.text) == (True, None, SESSION, "Working.")
    assert fake.cancels == 1
    assert fake.turns[0].ended
    assert fake.calls[-2:] == ["session.close", "agent.close"]
    assert (await collect(run))[-1].kind == "terminal"


async def test_a_run_past_its_timeout_is_cancelled_drained_and_names_the_session(
    world: Callable[..., FakeWorld],
) -> None:
    fake = world(keeps_working)

    run = await AmplifierAgentIntelligence().start(request().model_copy(update={"timeout_seconds": 0.05}))
    result = await run.result()

    assert result.error is not None
    assert "0.05 seconds" in result.error
    assert SESSION in result.error
    assert fake.cancels == 1
    assert fake.turns[0].ended


async def test_a_failed_turn_is_the_result_s_error(world: Callable[..., FakeWorld]) -> None:
    async def fails(turn: FakeTurn) -> None:
        turn.finish("failure", "Partial.", agent_error())

    world(fails)

    result = await (await AmplifierAgentIntelligence().start(request())).result()

    assert result.error == "provider_failed: The provider refused. Check the key."
    assert result.text == "Partial."


async def test_a_turn_ending_otherwise_without_an_error_names_its_state(world: Callable[..., FakeWorld]) -> None:
    async def rejected(turn: FakeTurn) -> None:
        turn.finish("rejected")

    world(rejected)

    result = await (await AmplifierAgentIntelligence().start(request())).result()

    assert result.error == "The turn ended rejected."


async def test_a_failure_after_the_start_is_the_result_s_error_and_everything_closes(
    world: Callable[..., FakeWorld],
) -> None:
    fake = world(submits())
    fake.turn_failure = RuntimeError("disk full")

    run = await AmplifierAgentIntelligence().start(request(output_schema=SCHEMA))
    result = await run.result()

    assert result.error == "RuntimeError: disk full"
    assert fake.calls[-2:] == ["session.close", "agent.close"]
    assert (await collect(run))[-1].kind == "terminal"


async def test_a_failure_before_the_first_turn_raises(world: Callable[..., FakeWorld]) -> None:
    fake = world()
    fake.failure = agent_error("session_in_use")

    with pytest.raises(RealityCheckError) as failure:
        await AmplifierAgentIntelligence().start(request())

    assert failure.value.code == "amplifier-agent-start-failed"
    assert "session_in_use: The provider refused." in failure.value.message


async def test_an_invalid_submission_fails_the_tool_and_the_corrected_one_in_the_same_turn_is_the_output(
    world: Callable[..., FakeWorld],
) -> None:
    fake = world(submits({"score": 120}, {"score": 90}, text="Graded."))

    run = await AmplifierAgentIntelligence().start(request(output_schema=SCHEMA))
    result = await run.result()

    assert result.output == {"score": 90}
    assert len(fake.inputs) == 1
    outcomes = [each for each in await collect(run) if each.kind == "tool_result"]
    assert [each.data["success"] for each in outcomes] == [False, True]
    assert "does not match the schema" in outcomes[0].data["error"]


async def test_a_turn_without_a_valid_submission_is_sent_back_and_keeps_the_earlier_text(
    world: Callable[..., FakeWorld],
) -> None:
    fake = world(submits(text="Graded."), submits({"score": 90}))

    result = await (await AmplifierAgentIntelligence().start(request(output_schema=SCHEMA))).result()

    assert (result.output, result.text) == ({"score": 90}, "Graded.")
    assert "no answer was submitted" in texts(fake.inputs[1])[0]


async def test_no_valid_submission_after_the_retries_is_the_result_s_error(world: Callable[..., FakeWorld]) -> None:
    fake = world(submits(), submits({"score": -1}), submits())

    result = await (await AmplifierAgentIntelligence().start(request(output_schema=SCHEMA))).result()

    assert result.output is None
    assert result.error == "No valid submission after 2 retries: no answer was submitted"
    assert len(fake.inputs) == 3


async def test_a_resumed_run_continues_the_named_session(world: Callable[..., FakeWorld], tmp_path: Path) -> None:
    fake = world(answers("You said hello."))

    run = await AmplifierAgentIntelligence().start(request(resume="earlier", session_directory=tmp_path / "copy"))
    result = await run.result()

    assert "resume_session earlier" in fake.calls
    assert "create_session" not in fake.calls
    assert result.session_id == "earlier"
    assert fake.options[0].sessions_directory == tmp_path / "copy"


def provider(name: str, credentials: Literal["found", "missing"], variables: list[str]) -> ProviderRecord:
    return ProviderRecord(name, name, True, credentials, variables)


def test_preflight_names_the_credential_variables_of_a_provider_without_credentials(
    world: Callable[..., FakeWorld],
) -> None:
    fake = world()
    fake.providers = [provider("openai", "missing", ["OPENAI_API_KEY"])]

    with pytest.raises(RealityCheckError) as failure:
        AmplifierAgentIntelligence(MODEL).preflight()

    assert failure.value.code == "amplifier-agent-unavailable"
    assert "OPENAI_API_KEY" in failure.value.remedy
    assert fake.calls == []


def test_preflight_describes_an_agent_that_cannot_be_made(world: Callable[..., FakeWorld]) -> None:
    fake = world()
    fake.providers = [provider("openai", "found", ["OPENAI_API_KEY"])]
    fake.failure = agent_error("selector_rejected")

    with pytest.raises(RealityCheckError) as failure:
        AmplifierAgentIntelligence(MODEL).preflight()

    assert failure.value.code == "amplifier-agent-unavailable"
    assert "selector_rejected: The provider refused. Check the key." in failure.value.message


def test_preflight_passes_with_credentials_or_where_they_cannot_be_detected(world: Callable[..., FakeWorld]) -> None:
    fake = world()
    fake.providers = [provider("openai", "found", ["OPENAI_API_KEY"]), provider("azure-openai", "missing", [])]

    AmplifierAgentIntelligence(MODEL).preflight()
    AmplifierAgentIntelligence("azure-openai/my-deployment").preflight()

    assert [(each.provider, each.model) for each in fake.options] == [
        ("openai", "gpt-6.1-sol"),
        ("azure-openai", "my-deployment"),
    ]
    assert fake.calls.count("agent.close") == 2


async def test_preflight_runs_inside_an_event_loop_and_refuses_a_model_without_a_provider(
    world: Callable[..., FakeWorld],
) -> None:
    world()

    with pytest.raises(RealityCheckError) as failure:
        AmplifierAgentIntelligence("gpt-6.1-sol").preflight()

    assert failure.value.code == "model-invalid"
    AmplifierAgentIntelligence(MODEL).preflight()
