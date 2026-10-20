"""Drives the Claude adapter with the SDK's client faked, so neither Claude Code nor an Anthropic account is needed."""

import asyncio
import base64
from collections.abc import AsyncIterable, AsyncIterator, Callable
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("claude_agent_sdk")

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ContentBlock,
    Message,
    ModelUsage,
    ResultMessage,
    SessionKey,
    SystemMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from reality_check.intelligence import claude as adapter
from reality_check.intelligence.claude import ClaudeIntelligence, FolderSessionStore, signed_in, skills_plugin
from reality_check.intelligence.schemas import AgentEvent, AgentRequest, HostWorkspace, McpServer
from reality_check.schemas import RealityCheckError

SESSION = "fake-session"
MODEL = "claude-sonnet-5-5"


def model_usage(cost: float) -> ModelUsage:
    return {
        "inputTokens": 10,
        "outputTokens": 2,
        "cacheReadInputTokens": 3,
        "cacheCreationInputTokens": 4,
        "webSearchRequests": 0,
        "costUSD": cost,
        "contextWindow": 200000,
        "maxOutputTokens": 64000,
    }


TELEMETRY_OFF = {
    "DISABLE_TELEMETRY": "1",
    "DISABLE_ERROR_REPORTING": "1",
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
}


def init() -> SystemMessage:
    return SystemMessage(subtype="init", data={"session_id": SESSION})


def echo(sent: dict[str, Any]) -> UserMessage:
    """The prompt as Claude Code replays it, without its images."""
    content = sent["message"]["content"]
    text = content if isinstance(content, str) else content[0]["text"]
    return UserMessage(content=text, uuid=sent["uuid"])


def assistant(*blocks: ContentBlock, parent: str | None = None) -> AssistantMessage:
    return AssistantMessage(content=list(blocks), model=MODEL, parent_tool_use_id=parent, session_id=SESSION)


def result(
    text: str | None = "done",
    is_error: bool = False,
    structured_output: Any = None,
    errors: list[str] | None = None,
    subtype: str = "success",
    total_cost_usd: float = 0.01,
) -> ResultMessage:
    return ResultMessage(
        subtype=subtype,
        duration_ms=1,
        duration_api_ms=1,
        is_error=is_error,
        num_turns=1,
        session_id=SESSION,
        total_cost_usd=total_cost_usd,
        usage={"input_tokens": 10, "output_tokens": 2, "cache_read_input_tokens": 3, "cache_creation_input_tokens": 4},
        result=text,
        structured_output=structured_output,
        model_usage={MODEL: model_usage(0.01)},
        errors=errors,
    )


class FakeClient:
    """Answers each sent message with the next script, whose messages the adapter reads on a later iteration."""

    def __init__(self, world: "FakeWorld", options: ClaudeAgentOptions) -> None:
        self._world = world
        self.options = options
        self._queue: asyncio.Queue[Message | None] = asyncio.Queue()

    def push(self, *messages: Message | None) -> None:
        for message in messages:
            self._queue.put_nowait(message)

    async def connect(self) -> None:
        self._world.calls.append("connect")
        if self._world.failure is not None:
            raise self._world.failure

    async def query(self, prompt: AsyncIterable[dict[str, Any]]) -> None:
        async for sent in prompt:
            self._world.sent.append(sent)
            self._world.scripts.pop(0)(self, sent)

    async def receive_messages(self) -> AsyncIterator[Message]:
        while (message := await self._queue.get()) is not None:
            yield message

    async def interrupt(self) -> None:
        self._world.interrupted += 1

    async def disconnect(self) -> None:
        self._world.disconnected += 1

    async def get_server_info(self) -> dict[str, Any] | None:
        return {"account": self._world.account}

    async def __aenter__(self) -> "FakeClient":
        await self.connect()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.disconnect()


Script = Callable[[FakeClient, dict[str, Any]], None]


def answers(text: str) -> Script:
    return lambda client, sent: client.push(init(), echo(sent), assistant(TextBlock(text)), result(text))


def submits(output: dict[str, Any] | None) -> Script:
    return lambda client, sent: client.push(echo(sent), result("{}", structured_output=output))


def keeps_working(client: FakeClient, sent: dict[str, Any]) -> None:
    client.push(init(), echo(sent), assistant(TextBlock("Working.")))


def ends(client: FakeClient, sent: dict[str, Any]) -> None:
    client.push(init(), echo(sent), None)


class FakeWorld:
    """Stands in for ClaudeSDKClient and records what the adapter asked of it."""

    def __init__(self, *scripts: Script) -> None:
        self.scripts = list(scripts)
        self.options: list[ClaudeAgentOptions] = []
        self.sent: list[dict[str, Any]] = []
        self.calls: list[str] = []
        self.interrupted = 0
        self.disconnected = 0
        self.failure: Exception | None = None
        self.account: dict[str, Any] = {"apiKeySource": "ANTHROPIC_API_KEY", "tokenSource": "none"}

    def client(self, options: ClaudeAgentOptions) -> FakeClient:
        self.options.append(options)
        return FakeClient(self, options)


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Callable[..., FakeWorld]:
    monkeypatch.setattr(adapter, "state_directory", lambda agent_provider: tmp_path / "state" / agent_provider)

    def install(*scripts: Script) -> FakeWorld:
        fake = FakeWorld(*scripts)
        monkeypatch.setattr(adapter, "ClaudeSDKClient", fake.client)
        return fake

    return install


def request(workspace: Path | None = None, **fields: Any) -> AgentRequest:
    return AgentRequest(
        prompt="Do the work.",
        model=MODEL,
        workspace=HostWorkspace(path=workspace) if workspace is not None else None,
        timeout_seconds=60,
        **fields,
    )


async def collect(run: adapter.ClaudeRun) -> list[AgentEvent]:
    return [each async for each in run.events()]


async def until_message(run: adapter.ClaudeRun, text: str) -> None:
    async for each in run.events():
        if each.kind == "message" and each.text == text:
            return


SCHEMA = {
    "type": "object",
    "properties": {"score": {"type": "integer", "minimum": 0, "maximum": 100}},
    "required": ["score"],
    "additionalProperties": False,
}


async def test_a_run_gets_the_workspace_and_its_options_with_telemetry_and_settings_off(
    world: Callable[..., FakeWorld], tmp_path: Path
) -> None:
    fake = world(answers("done"))

    run = await ClaudeIntelligence().start(
        request(tmp_path, reasoning_effort="max", session_directory=tmp_path / "session")
    )
    result_ = await run.result()

    assert (result_.text, result_.error, result_.session_id) == ("done", None, SESSION)
    [options] = fake.options
    assert options.cwd == tmp_path.resolve()
    assert options.model == MODEL
    assert options.tools is None
    assert options.permission_mode == "bypassPermissions"
    assert options.effort == "max"
    assert options.thinking == {"type": "adaptive", "display": "summarized"}
    assert options.extra_args == {"replay-user-messages": None}
    assert options.max_buffer_size == 64 * 1024 * 1024
    assert options.setting_sources == []
    assert options.env == TELEMETRY_OFF
    assert options.include_partial_messages is False
    assert options.output_format is None
    assert options.plugins == []
    assert options.skills is None
    assert isinstance(options.session_store, FolderSessionStore)
    assert options.session_store.directory == tmp_path / "session"
    assert options.session_store_flush == "eager"
    assert fake.calls == ["connect"]
    assert fake.interrupted == 0
    assert fake.disconnected == 1


async def test_without_a_workspace_or_effort_a_run_works_in_the_scratch_directory_and_sends_no_effort(
    world: Callable[..., FakeWorld], tmp_path: Path
) -> None:
    fake = world(answers("done"))

    await (
        await ClaudeIntelligence().start(request(resume=SESSION).model_copy(update={"reasoning_effort": None}))
    ).result()

    [options] = fake.options
    assert options.cwd == tmp_path / "state" / "claude"
    assert options.cwd.is_dir()
    assert options.effort is None
    assert options.resume == SESSION
    assert options.session_store is None


async def test_skill_directories_become_one_local_plugin_reused_while_the_skills_are_the_same(
    world: Callable[..., FakeWorld], tmp_path: Path
) -> None:
    first, second = tmp_path / "skills", tmp_path / "0123abcd"
    (first / "alpha").mkdir(parents=True)
    (first / "alpha" / "SKILL.md").write_text("alpha", encoding="utf-8")
    (first / "alpha" / "notes.md").write_text("more", encoding="utf-8")
    (first / "loose.md").write_text("not a skill", encoding="utf-8")
    (second / "beta").mkdir(parents=True)
    (second / "beta" / "SKILL.md").write_text("beta", encoding="utf-8")
    fake = world(answers("done"))

    await (await ClaudeIntelligence().start(request(skill_directories=[first, second]))).result()

    [options] = fake.options
    [plugin] = options.plugins
    root = Path(plugin["path"])
    assert plugin["type"] == "local"
    assert root.name == "reality-check"
    assert root.parents[1] == tmp_path / "state" / "claude" / "plugins"
    assert options.skills == "all"
    assert (root / "skills" / "alpha" / "SKILL.md").read_text(encoding="utf-8") == "alpha"
    assert (root / "skills" / "alpha" / "notes.md").read_text(encoding="utf-8") == "more"
    assert (root / "skills" / "beta" / "SKILL.md").read_text(encoding="utf-8") == "beta"
    assert sorted(path.name for path in (root / "skills").iterdir()) == ["alpha", "beta"]

    assert skills_plugin([first, second]) == root
    assert [path.name for path in root.parents[1].iterdir()] == [root.parent.name]
    (second / "beta" / "SKILL.md").write_text("beta, changed", encoding="utf-8")
    changed = skills_plugin([first, second])
    assert changed != root
    assert (changed / "skills" / "beta" / "SKILL.md").read_text(encoding="utf-8") == "beta, changed"


async def test_the_prompt_is_one_streamed_message_with_its_images_as_base64_blocks(
    world: Callable[..., FakeWorld], tmp_path: Path
) -> None:
    image = tmp_path / "shot.PNG"
    image.write_bytes(b"\x89PNG fake")
    fake = world(answers("Red."))

    await (await ClaudeIntelligence().start(request(images=[image]))).result()

    [sent] = fake.sent
    assert sent["type"] == "user"
    assert sent["parent_tool_use_id"] is None
    assert isinstance(sent["uuid"], str)
    assert sent["message"] == {
        "role": "user",
        "content": [
            {"type": "text", "text": "Do the work."},
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": base64.b64encode(b"\x89PNG fake").decode("ascii"),
                },
            },
        ],
    }


async def test_claude_messages_become_agent_events_ending_in_one_terminal(world: Callable[..., FakeWorld]) -> None:
    def script(client: FakeClient, sent: dict[str, Any]) -> None:
        client.push(
            init(),
            echo(sent),
            assistant(
                ThinkingBlock(thinking="Think.", signature="s"),
                ThinkingBlock(thinking="", signature="s"),
                TextBlock(""),
                TextBlock("Looking."),
                ToolUseBlock(id="call-1", name="Bash", input={"command": "echo hi"}),
            ),
            UserMessage(
                content=[ToolResultBlock(tool_use_id="call-1", content=[{"type": "text", "text": "x" * 2000}])]
            ),
            assistant(ToolUseBlock(id="call-2", name="Read", input={"file_path": "a.md"}), parent="task-1"),
            UserMessage(
                content=[ToolResultBlock(tool_use_id="call-2", content="no such file", is_error=True)],
                parent_tool_use_id="task-1",
            ),
            assistant(TextBlock("Done.")),
            result("Done."),
        )

    world(script)

    run = await ClaudeIntelligence().start(request())
    events = await collect(run)

    assert [each.kind for each in events] == [
        "reasoning",
        "message",
        "tool_call",
        "tool_result",
        "tool_call",
        "tool_result",
        "message",
        "usage",
        "terminal",
    ]
    reasoning, said, call, outcome, sub_call, sub_outcome, _, usage, terminal = events
    assert (reasoning.text, reasoning.data) == ("Think.", {})
    assert said.text == "Looking."
    assert call.text == 'Bash {"command": "echo hi"}'
    assert call.data == {"tool_call_id": "call-1", "tool_name": "Bash", "arguments": {"command": "echo hi"}}
    assert outcome.data == {"tool_call_id": "call-1", "tool_name": "Bash", "success": True, "result": "x" * 2000}
    assert len(outcome.text) < 2000
    assert sub_call.data["agent_id"] == "task-1"
    assert sub_outcome.data == {
        "tool_call_id": "call-2",
        "tool_name": "Read",
        "success": False,
        "result": "no such file",
        "agent_id": "task-1",
    }
    assert sub_outcome.text == "no such file"
    assert usage.data == {
        "model": MODEL,
        "input_tokens": 10,
        "fresh_input_tokens": 10,
        "output_tokens": 2,
        "cache_read_tokens": 3,
        "cache_write_tokens": 4,
        "cost": {"USD": 0.01},
        "billing": {"USD": 0.01},
        "model_usage": {MODEL: model_usage(0.01)},
    }
    assert (terminal.text, terminal.data["text"], terminal.data["session_id"]) == ("Done.", "Done.", SESSION)
    assert run.session_id == SESSION
    assert await collect(run) == events


async def test_usage_names_the_model_claude_code_reports_when_the_request_s_is_not_among_them(
    world: Callable[..., FakeWorld],
) -> None:
    def script(client: FakeClient, sent: dict[str, Any]) -> None:
        answer = result()
        answer.model_usage = {"claude-opus-5-5": model_usage(0.02)}
        client.push(echo(sent), answer)

    world(script)

    events = await collect(await ClaudeIntelligence().start(request()))

    assert events[0].data["model"] == "claude-opus-5-5"


async def test_steering_while_the_agent_works_is_a_streamed_message_answered_in_the_same_result(
    world: Callable[..., FakeWorld],
) -> None:
    fake = world(keeps_working, lambda client, sent: client.push(echo(sent), result("DONE1\n\nSTEERED2")))

    run = await ClaudeIntelligence().start(request())
    await until_message(run, "Working.")
    await run.steer("Also say STEERED2.")
    result_ = await run.result()

    assert result_.text == "DONE1\n\nSTEERED2"
    assert [sent["message"]["content"] for sent in fake.sent] == ["Do the work.", "Also say STEERED2."]
    assert fake.sent[0]["uuid"] != fake.sent[1]["uuid"]


async def test_a_result_before_a_late_steer_is_echoed_does_not_end_the_run(world: Callable[..., FakeWorld]) -> None:
    def late(client: FakeClient, sent: dict[str, Any]) -> None:
        client.push(
            result("DONE1"),
            init(),
            echo(sent),
            assistant(TextBlock("STEERED2")),
            result("STEERED2", total_cost_usd=0.03),
        )

    world(keeps_working, late)

    run = await ClaudeIntelligence().start(request())
    await until_message(run, "Working.")
    await run.steer("Also say STEERED2.")
    result_ = await run.result()
    events = await collect(run)

    assert result_.text == "STEERED2"
    costs = [each.data["cost"]["USD"] for each in events if each.kind == "usage"]
    assert costs == pytest.approx([0.01, 0.02])


async def test_steering_after_the_run_ended_names_the_session_to_resume(world: Callable[..., FakeWorld]) -> None:
    world(answers("done"))

    run = await ClaudeIntelligence().start(request())
    await run.result()

    with pytest.raises(RealityCheckError) as failure:
        await run.steer("More.")

    assert failure.value.code == "agent-run-finished"
    assert SESSION in failure.value.remedy


async def test_cancel_interrupts_and_disconnects_so_the_session_can_be_resumed(
    world: Callable[..., FakeWorld],
) -> None:
    fake = world(keeps_working)

    run = await ClaudeIntelligence().start(request())
    await until_message(run, "Working.")
    await run.cancel()
    result_ = await run.result()

    assert result_.cancelled
    assert result_.error is None
    assert (result_.text, result_.session_id) == ("Working.", SESSION)
    assert (fake.interrupted, fake.disconnected) == (1, 1)
    assert (await collect(run))[-1].kind == "terminal"
    await run.cancel()
    assert fake.disconnected == 1


async def test_a_run_past_its_timeout_is_interrupted_and_names_the_session(world: Callable[..., FakeWorld]) -> None:
    fake = world(keeps_working)

    run = await ClaudeIntelligence().start(request().model_copy(update={"timeout_seconds": 0.05}))
    result_ = await run.result()

    assert result_.error is not None
    assert "0.05 seconds" in result_.error
    assert SESSION in result_.error
    assert (fake.interrupted, fake.disconnected) == (1, 1)


async def test_a_conversation_that_ends_without_a_result_is_the_result_s_error(
    world: Callable[..., FakeWorld],
) -> None:
    fake = world(ends)

    run = await ClaudeIntelligence().start(request())
    result_ = await run.result()

    assert result_.error == "RuntimeError: Claude Code ended the conversation without a result."
    assert result_.session_id == SESSION
    assert fake.disconnected == 1
    assert [each.kind for each in await collect(run)] == ["terminal"]


@pytest.mark.parametrize(
    ("answer", "error"),
    [
        (result("ignored", is_error=True, errors=["first", "second"]), "first; second"),
        (
            result("There's an issue with the selected model.", is_error=True),
            "There's an issue with the selected model.",
        ),
        (result(None, is_error=True, subtype="error_max_turns"), "The run ended error_max_turns."),
    ],
)
async def test_an_error_result_is_the_result_s_error(
    world: Callable[..., FakeWorld], answer: ResultMessage, error: str
) -> None:
    world(lambda client, sent: client.push(echo(sent), answer))

    run = await ClaudeIntelligence().start(request())
    result_ = await run.result()

    assert result_.error == error
    assert (await collect(run))[-1].text == error
    with pytest.raises(RealityCheckError):
        await run.steer("More.")


async def test_an_output_schema_is_the_output_format_and_the_structured_output_the_output(
    world: Callable[..., FakeWorld],
) -> None:
    fake = world(submits({"score": 80}))

    result_ = await (await ClaudeIntelligence().start(request(output_schema=SCHEMA))).result()

    assert result_.output == {"score": 80}
    assert result_.error is None
    assert fake.options[0].output_format == {"type": "json_schema", "schema": SCHEMA}


async def test_an_invalid_structured_output_is_sent_back_and_the_corrected_one_is_the_output(
    world: Callable[..., FakeWorld],
) -> None:
    fake = world(submits({"score": 120}), submits({"score": 90}))

    result_ = await (await ClaudeIntelligence().start(request(output_schema=SCHEMA))).result()

    assert result_.output == {"score": 90}
    assert len(fake.sent) == 2
    assert "does not match the schema" in fake.sent[1]["message"]["content"]


async def test_no_valid_structured_output_after_the_retries_is_the_result_s_error(
    world: Callable[..., FakeWorld],
) -> None:
    fake = world(submits(None), submits(None), submits(None))

    result_ = await (await ClaudeIntelligence().start(request(output_schema=SCHEMA))).result()

    assert result_.output is None
    assert result_.error == "No valid submission after 2 retries: no answer was submitted"
    assert len(fake.sent) == 3


async def test_mcp_servers_are_refused_before_claude_code_starts(world: Callable[..., FakeWorld]) -> None:
    fake = world()

    with pytest.raises(RealityCheckError) as failure:
        await ClaudeIntelligence().start(request(mcp_servers={"dtu": McpServer(command="dtu")}))

    assert failure.value.code == "mcp-not-supported"
    assert failure.value.message == "The claude agent provider does not take MCP servers."
    assert fake.options == []


async def test_claude_code_that_does_not_start_is_claude_unavailable(world: Callable[..., FakeWorld]) -> None:
    fake = world()
    fake.failure = RuntimeError("no runtime")

    with pytest.raises(RealityCheckError) as failure:
        await ClaudeIntelligence().start(request())

    assert failure.value.code == "claude-unavailable"
    assert "no runtime" in failure.value.message
    assert fake.disconnected == 1


async def test_preflight_reads_the_account_with_telemetry_off_and_inside_a_running_loop(
    world: Callable[..., FakeWorld],
) -> None:
    fake = world()
    intelligence = ClaudeIntelligence()

    intelligence.preflight()
    intelligence.preflight()

    [options] = fake.options
    assert options.env == TELEMETRY_OFF
    assert options.setting_sources == []
    assert fake.calls == ["connect"]
    assert fake.disconnected == 1


@pytest.mark.parametrize(
    ("account", "failure", "code"),
    [
        ({"apiProvider": "firstParty", "tokenSource": "none"}, None, "claude-not-signed-in"),
        ({}, RuntimeError("bad settings"), "claude-unavailable"),
    ],
)
def test_preflight_names_what_to_configure(
    world: Callable[..., FakeWorld], account: dict[str, Any], failure: Exception | None, code: str
) -> None:
    fake = world()
    fake.account = account
    fake.failure = failure

    with pytest.raises(RealityCheckError) as raised:
        ClaudeIntelligence().preflight()

    assert raised.value.code == code


@pytest.mark.parametrize(
    ("account", "expected"),
    [
        ({"apiKeySource": "ANTHROPIC_API_KEY", "tokenSource": "none", "apiProvider": "firstParty"}, True),
        ({"tokenSource": "claude.ai"}, True),
        ({"subscriptionType": "max"}, True),
        ({"apiProvider": "bedrock"}, True),
        ({"tokenSource": "none", "apiProvider": "firstParty"}, False),
        ({}, False),
    ],
)
def test_signed_in(account: dict[str, Any], expected: bool) -> None:
    assert signed_in(account) is expected


async def test_a_folder_session_store_keeps_transcripts_it_can_load_list_and_delete(tmp_path: Path) -> None:
    store = FolderSessionStore(tmp_path)
    main: SessionKey = {"project_key": "p", "session_id": SESSION}
    sub: SessionKey = {"project_key": "p", "session_id": SESSION, "subpath": "subagents/agent-1"}

    await store.append(main, [{"type": "user", "uuid": "u1"}])
    await store.append(main, [{"type": "assistant", "uuid": "a1"}])
    await store.append(sub, [{"type": "user", "uuid": "u2"}])

    assert await store.load(main) == [{"type": "user", "uuid": "u1"}, {"type": "assistant", "uuid": "a1"}]
    assert [entry["session_id"] for entry in await store.list_sessions("p")] == [SESSION]
    assert await store.list_subkeys(main) == ["subagents/agent-1"]
    await store.delete(main)
    assert await store.load(main) is None
    assert await store.load(sub) is None
