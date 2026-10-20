"""Drives the Copilot adapter with the SDK's client faked, so neither gh nor a Copilot subscription is needed."""

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

pytest.importorskip("copilot")

from copilot import ModelCapabilities, ModelInfo, ModelLimits, ModelSupports, PermissionHandler, Tool, ToolInvocation
from copilot.session_events import (
    AssistantMessageData,
    AssistantReasoningData,
    AssistantUsageCopilotUsage,
    AssistantUsageData,
    SessionEvent,
    SessionEventData,
    SessionEventType,
    SessionIdleData,
    ToolExecutionCompleteData,
    ToolExecutionCompleteError,
    ToolExecutionCompleteResult,
    ToolExecutionStartData,
)

from reality_check.intelligence import copilot as adapter
from reality_check.intelligence.copilot import CopilotIntelligence
from reality_check.intelligence.schemas import AgentEvent, AgentRequest, HostWorkspace, McpServer
from reality_check.schemas import RealityCheckError

SESSION = "fake-session"


def model_info(model_id: str, efforts: list[str] | None, vision: bool = True) -> ModelInfo:
    supports = ModelSupports(vision=vision, reasoning_effort=efforts is not None)
    return ModelInfo(
        id=model_id,
        name=model_id,
        capabilities=ModelCapabilities(supports=supports, limits=ModelLimits()),
        supported_reasoning_efforts=efforts,
    )


MODELS = [
    model_info("gpt-6.1-sol", ["none", "low", "medium", "high", "xhigh", "max"]),
    model_info("auto", None, vision=False),
]


def event(event_type: SessionEventType, data: SessionEventData) -> SessionEvent:
    return SessionEvent(data=data, id=uuid4(), timestamp=datetime.now(UTC), type=event_type)


def message(text: str, api_call_id: str | None = None, chunk_index: int | None = None) -> SessionEvent:
    data = AssistantMessageData(content=text, message_id=str(uuid4()), api_call_id=api_call_id, chunk_index=chunk_index)
    return event(SessionEventType.ASSISTANT_MESSAGE, data)


def idle() -> SessionEvent:
    return event(SessionEventType.SESSION_IDLE, SessionIdleData())


class FakeSession:
    """Answers each send with the next script, whose events reach the adapter on a later loop iteration."""

    def __init__(self, world: "FakeWorld", options: dict[str, Any], session_id: str) -> None:
        self.session_id = session_id
        self._world = world
        self.options = options
        self._on_event: Callable[[SessionEvent], None] = options["on_event"]

    def emit(self, *events: SessionEvent) -> None:
        for each in events:
            asyncio.get_running_loop().call_soon(self._on_event, each)

    async def send(self, prompt: str, attachments: list[Any] | None = None, mode: str | None = None) -> str:
        self._world.sends.append((prompt, mode))
        self._world.attachments.append(attachments)
        self._world.scripts.pop(0)(self)
        return "message-id"

    async def abort(self) -> None:
        self._world.aborted += 1
        self.emit(event(SessionEventType.SESSION_IDLE, SessionIdleData(aborted=True)))


Script = Callable[[FakeSession], None]


def answers(text: str) -> Script:
    return lambda session: session.emit(message(text), idle())


def submits(arguments: dict[str, Any] | None, text: str = "") -> Script:
    """Calls the submit tool when given arguments, then ends the turn, the way a terminal tool does."""

    def script(session: FakeSession) -> None:
        if arguments is not None:
            tool: Tool = session.options["tools"][0]
            assert tool.handler is not None
            tool.handler(ToolInvocation(tool_name=tool.name, arguments=arguments))
        session.emit(*([message(text)] if text else []), idle())

    return script


def keeps_working(session: FakeSession) -> None:
    session.emit(message("Working."))


class FakeWorld:
    """Stands in for CopilotClient and records what the adapter asked of it."""

    def __init__(self, *scripts: Script) -> None:
        self.scripts = list(scripts)
        self.options: list[dict[str, Any]] = []
        self.sends: list[tuple[str, str | None]] = []
        self.attachments: list[list[Any] | None] = []
        self.calls: list[str] = []
        self.resumed: list[str] = []
        self.aborted = 0
        self.stopped = 0
        self.failure: Exception | None = None

    def client(self, working_directory: str | None, github_token: str) -> Any:
        world = self

        class Client:
            async def start(self) -> None:
                world.calls.append("start")

            async def stop(self) -> None:
                world.stopped += 1

            async def list_models(self) -> list[ModelInfo]:
                world.calls.append("list_models")
                return MODELS

            async def create_session(self, **options: Any) -> FakeSession:
                world.calls.append("create_session")
                if world.failure is not None:
                    raise world.failure
                world.options.append(options)
                return FakeSession(world, options, SESSION)

            async def resume_session(self, session_id: str, **options: Any) -> FakeSession:
                world.calls.append("resume_session")
                world.resumed.append(session_id)
                world.options.append(options)
                return FakeSession(world, options, session_id)

        return Client()


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> Callable[..., FakeWorld]:
    def install(*scripts: Script) -> FakeWorld:
        fake = FakeWorld(*scripts)
        monkeypatch.setattr(adapter, "CopilotClient", fake.client)
        monkeypatch.setattr(CopilotIntelligence, "_github_token", lambda self: "token")
        return fake

    return install


def request(workspace: Path | None = None, **fields: Any) -> AgentRequest:
    return AgentRequest(
        prompt="Do the work.",
        model="gpt-6.1-sol",
        workspace=HostWorkspace(path=workspace) if workspace is not None else None,
        timeout_seconds=60,
        **fields,
    )


async def collect(run: adapter.CopilotRun) -> list[AgentEvent]:
    return [each async for each in run.events()]


async def test_a_session_gets_the_workspace_mcp_servers_and_skills_and_keeps_the_built_in_tools(
    world: Callable[..., FakeWorld], tmp_path: Path
) -> None:
    fake = world(answers("done"))
    server = McpServer(command="dtu", args=["mcp"], env={"A": "1"}, cwd=tmp_path)

    run = await CopilotIntelligence().start(
        request(tmp_path, reasoning_effort="max", mcp_servers={"dtu": server}, skill_directories=[tmp_path / "skills"])
    )
    known_once_started = run.session_id
    result = await run.result()

    assert known_once_started == SESSION

    assert result.text == "done"
    assert result.session_id == SESSION
    options = fake.options[0]
    assert "available_tools" not in options
    assert "tools" not in options
    assert options["model"] == "gpt-6.1-sol"
    assert options["reasoning_effort"] == "max"
    assert options["working_directory"] == str(tmp_path)
    assert options["on_permission_request"] is PermissionHandler.approve_all
    assert options["skip_custom_instructions"] is True
    assert options["enable_session_telemetry"] is False
    assert options["skill_directories"] == [str(tmp_path / "skills")]
    assert options["mcp_servers"] == {
        "dtu": {
            "type": "stdio",
            "command": "dtu",
            "args": ["mcp"],
            "env": {"A": "1"},
            "working_directory": str(tmp_path),
            "tools": ["*"],
        }
    }
    assert fake.stopped == 1


async def test_sdk_events_become_agent_events_ending_in_one_terminal(world: Callable[..., FakeWorld]) -> None:
    def script(session: FakeSession) -> None:
        session.emit(
            event(
                SessionEventType.TOOL_EXECUTION_START,
                ToolExecutionStartData(tool_call_id="1", tool_name="bash", arguments={"command": "echo hello"}),
            ),
            event(
                SessionEventType.TOOL_EXECUTION_COMPLETE,
                ToolExecutionCompleteData(
                    success=True, tool_call_id="1", result=ToolExecutionCompleteResult(content="x" * 2000)
                ),
            ),
            event(
                SessionEventType.ASSISTANT_USAGE,
                AssistantUsageData(
                    model="gpt-6.1-sol",
                    input_tokens=10,
                    output_tokens=2,
                    cache_read_tokens=6,
                    cache_write_tokens=1,
                    cost=1.0,
                    copilot_usage=AssistantUsageCopilotUsage(total_nano_aiu=1500.0),
                ),
            ),
            message("done"),
            idle(),
        )

    world(script)

    run = await CopilotIntelligence().start(request())
    events = await collect(run)

    assert [each.kind for each in events] == ["tool_call", "tool_result", "usage", "message", "terminal"]
    call, outcome, usage, said, terminal = events
    assert call.text == 'bash {"command": "echo hello"}'
    assert call.data["tool_name"] == "bash"
    assert call.data["arguments"] == {"command": "echo hello"}
    assert outcome.data == {"tool_call_id": "1", "tool_name": "bash", "success": True, "result": "x" * 2000}
    assert len(outcome.text) < 2000
    assert usage.data["input_tokens"] == 10
    assert usage.data["cost"] == 1.0
    assert usage.data["copilot_usage"] == {"totalNanoAiu": 1500.0}
    assert usage.data["fresh_input_tokens"] == 3
    assert usage.data["billing"] == {"AIU": 1.5e-6}
    assert said.text == "done"
    assert terminal.data["session_id"] == SESSION
    assert all(each.time.tzinfo is not None for each in events)
    assert await collect(run) == events


async def test_the_result_text_is_the_final_message_of_the_turn_whole(world: Callable[..., FakeWorld]) -> None:
    def script(session: FakeSession) -> None:
        from_subagent = message("A subagent's answer.")
        from_subagent.agent_id = "explore"
        session.emit(
            message("Let me look.", api_call_id="call-1"),
            from_subagent,
            message("# Report", api_call_id="call-2", chunk_index=0),
            message("Go: pass", api_call_id="call-2", chunk_index=1),
            idle(),
        )

    fake = world(script)

    result = await (await CopilotIntelligence().start(request())).result()

    assert result.text == "# Report\n\nGo: pass"
    assert result.error is None
    assert fake.sends == [("Do the work.", None)]


async def test_cancel_aborts_and_drains_so_the_session_can_be_resumed(world: Callable[..., FakeWorld]) -> None:
    fake = world(keeps_working)

    run = await CopilotIntelligence().start(request())
    await run.cancel()
    result = await run.result()

    assert result.cancelled
    assert result.error is None
    assert result.session_id == SESSION
    assert fake.aborted == 1
    assert fake.stopped == 1
    assert (await collect(run))[-1].kind == "terminal"


async def test_a_run_past_its_timeout_is_aborted_and_names_the_session(world: Callable[..., FakeWorld]) -> None:
    fake = world(keeps_working)

    run = await CopilotIntelligence().start(request().model_copy(update={"timeout_seconds": 0.05}))
    result = await run.result()

    assert result.error is not None
    assert "0.05 seconds" in result.error
    assert SESSION in result.error
    assert fake.aborted == 1


async def test_an_sdk_failure_is_the_result_s_error_and_the_client_still_stops(
    world: Callable[..., FakeWorld],
) -> None:
    fake = world()
    fake.failure = RuntimeError("model not available")

    run = await CopilotIntelligence().start(request())
    result = await run.result()

    assert result.error == "RuntimeError: model not available"
    assert fake.stopped == 1
    assert [each.kind for each in await collect(run)] == ["terminal"]


SCHEMA = {
    "type": "object",
    "properties": {"score": {"type": "integer", "minimum": 0, "maximum": 100}},
    "required": ["score"],
    "additionalProperties": False,
}


async def test_an_output_schema_adds_a_terminal_submit_tool_beside_the_built_in_ones(
    world: Callable[..., FakeWorld],
) -> None:
    fake = world(submits({"score": 80}, text="Graded."))

    result = await (await CopilotIntelligence().start(request(output_schema=SCHEMA))).result()

    assert result.output == {"score": 80}
    assert result.text == "Graded."
    assert result.error is None
    options = fake.options[0]
    assert "available_tools" not in options
    [tool] = options["tools"]
    assert (tool.name, tool.parameters, tool.is_terminal, tool.skip_permission) == ("submit", SCHEMA, True, True)


async def test_an_invalid_submission_is_sent_back_and_the_corrected_one_is_the_output(
    world: Callable[..., FakeWorld],
) -> None:
    fake = world(submits({"score": 120}, text="Graded."), submits({"score": 90}))

    result = await (await CopilotIntelligence().start(request(output_schema=SCHEMA))).result()

    assert result.output == {"score": 90}
    assert result.text == "Graded."
    assert len(fake.sends) == 2
    assert "does not match the schema" in fake.sends[1][0]


async def test_no_valid_submission_after_the_retries_is_the_result_s_error(world: Callable[..., FakeWorld]) -> None:
    fake = world(submits(None), submits(None), submits(None))

    result = await (await CopilotIntelligence().start(request(output_schema=SCHEMA))).result()

    assert result.output is None
    assert result.error == "No valid submission after 2 retries: no answer was submitted"
    assert len(fake.sends) == 3


async def test_reasoning_becomes_one_reasoning_event_and_empty_reasoning_none(world: Callable[..., FakeWorld]) -> None:
    def script(session: FakeSession) -> None:
        session.emit(
            event(SessionEventType.ASSISTANT_REASONING, AssistantReasoningData(content="Think.", reasoning_id="r1")),
            event(SessionEventType.ASSISTANT_REASONING, AssistantReasoningData(content=" ", reasoning_id="r2")),
            message("done"),
            idle(),
        )

    world(script)

    events = await collect(await CopilotIntelligence().start(request()))

    assert [each.kind for each in events] == ["reasoning", "message", "terminal"]
    assert (events[0].text, events[0].data) == ("Think.", {"reasoning_id": "r1"})


async def test_a_long_tool_result_keeps_its_full_and_detailed_content_and_a_failure_its_error(
    world: Callable[..., FakeWorld],
) -> None:
    long = "y" * 3000

    def script(session: FakeSession) -> None:
        session.emit(
            event(
                SessionEventType.TOOL_EXECUTION_START,
                ToolExecutionStartData(tool_call_id="1", tool_name="view", arguments={"path": "z" * 1000}),
            ),
            event(
                SessionEventType.TOOL_EXECUTION_COMPLETE,
                ToolExecutionCompleteData(
                    success=True,
                    tool_call_id="1",
                    result=ToolExecutionCompleteResult(content=long, detailed_content=long + "!"),
                ),
            ),
            event(
                SessionEventType.TOOL_EXECUTION_COMPLETE,
                ToolExecutionCompleteData(
                    success=False, tool_call_id="2", error=ToolExecutionCompleteError(message="no such file")
                ),
            ),
            idle(),
        )

    world(script)

    call, result, failure, _ = await collect(await CopilotIntelligence().start(request()))

    assert len(call.text) < 600
    assert call.data["arguments"] == {"path": "z" * 1000}
    assert len(result.text) < 600
    assert (result.data["result"], result.data["detailed_result"]) == (long, long + "!")
    assert (failure.text, failure.data["error"], failure.data["success"]) == ("no such file", "no such file", False)


async def test_images_are_file_attachments_with_a_display_name_on_the_first_send_only(
    world: Callable[..., FakeWorld], tmp_path: Path
) -> None:
    image = tmp_path / "shot.png"
    fake = world(submits(None), submits({"score": 1}))

    await (await CopilotIntelligence().start(request(images=[image], output_schema=SCHEMA))).result()

    assert fake.attachments == [[{"type": "file", "path": str(image), "displayName": "shot.png"}], None]


async def test_the_session_directory_is_the_config_directory_on_create_and_resume_and_no_effort_sends_none(
    world: Callable[..., FakeWorld], tmp_path: Path
) -> None:
    fake = world(answers("one"), answers("two"))

    await (await CopilotIntelligence().start(request(session_directory=tmp_path / "session"))).result()
    await (
        await CopilotIntelligence().start(
            request(resume=SESSION, session_directory=tmp_path / "again").model_copy(
                update={"model": "auto", "reasoning_effort": None}
            )
        )
    ).result()

    created, resumed = fake.options
    assert created["config_directory"] == str(tmp_path / "session")
    assert created["reasoning_effort"] == "high"
    assert resumed["config_directory"] == str(tmp_path / "again")
    assert "reasoning_effort" not in resumed
    assert fake.resumed == [SESSION]


@pytest.mark.parametrize(
    ("fields", "code"),
    [
        ({"model": "gemini-4-argon"}, "model-not-available"),
        ({"reasoning_effort": "none"}, "bad-reasoning-effort"),
        ({"model": "auto", "reasoning_effort": "low"}, "bad-reasoning-effort"),
        ({"model": "auto", "reasoning_effort": None, "images": [Path("shot.png")]}, "model-without-vision"),
    ],
)
async def test_the_run_s_own_client_refuses_a_model_this_account_cannot_run_as_asked_before_a_session(
    world: Callable[..., FakeWorld], fields: dict[str, Any], code: str
) -> None:
    fake = world()
    asked = request().model_copy(update=fields)

    with pytest.raises(RealityCheckError) as failure:
        await CopilotIntelligence().start(asked)

    assert failure.value.code == code
    assert fake.calls == ["start", "list_models"]
    assert fake.stopped == 1
