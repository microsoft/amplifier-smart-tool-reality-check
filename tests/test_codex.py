"""Drives the Codex adapter with the SDK's client faked, so neither a Codex sign-in nor a network is needed."""

import asyncio
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

pytest.importorskip("openai_codex")

from openai_codex import ApprovalMode, CodexConfig, InvalidRequestError, LocalImageInput, Sandbox, TextInput
from openai_codex.generated.notification_registry import NOTIFICATION_MODELS
from openai_codex.models import Notification, UnknownNotification
from openai_codex.types import GetAccountResponse, ReasoningEffort

from reality_check.intelligence import codex as adapter
from reality_check.intelligence.codex import CodexIntelligence, to_strict
from reality_check.intelligence.schemas import AgentEvent, AgentRequest, HostWorkspace, McpServer
from reality_check.schemas import RealityCheckError

THREAD = "fake-thread"


def notification(method: str, params: dict[str, Any]) -> Notification:
    """The notification as the SDK hands it over: a typed payload when it parses, else the raw params."""
    model = NOTIFICATION_MODELS.get(method)
    if model is None:
        return Notification(method=method, payload=UnknownNotification(params=params))
    return Notification(method=method, payload=model.model_validate(params))


def started(item: dict[str, Any]) -> Notification:
    return notification("item/started", {"item": item, "threadId": THREAD, "turnId": "t", "startedAtMs": 1_000})


def completed(item: dict[str, Any]) -> Notification:
    return notification("item/completed", {"item": item, "threadId": THREAD, "turnId": "t", "completedAtMs": 2_000})


def message(text: str) -> Notification:
    return completed({"id": "msg_1", "type": "agentMessage", "phase": "final_answer", "text": text})


def command(exit_code: int | None = None, output: str = "") -> dict[str, Any]:
    item: dict[str, Any] = {
        "id": "exec-1",
        "type": "commandExecution",
        "command": "/bin/bash -lc 'echo hi'",
        "commandActions": [{"command": "echo hi", "type": "unknown"}],
        "cwd": "/work",
        "status": "inProgress",
    }
    if exit_code is not None:
        item |= {"status": "completed" if exit_code == 0 else "failed", "exitCode": exit_code}
        item["aggregatedOutput"] = output
    return item


def usage(last_input: int, last_output: int, total: int) -> Notification:
    def counts(input_tokens: int, output_tokens: int, total_tokens: int) -> dict[str, int]:
        return {
            "inputTokens": input_tokens,
            "outputTokens": output_tokens,
            "cachedInputTokens": 3,
            "cacheWriteInputTokens": 0,
            "reasoningOutputTokens": 1,
            "totalTokens": total_tokens,
        }

    return notification(
        "thread/tokenUsage/updated",
        {
            "threadId": THREAD,
            "turnId": "t",
            "tokenUsage": {
                "last": counts(last_input, last_output, last_input + last_output),
                "total": counts(0, 0, total),
            },
        },
    )


def turn_completed(status: str = "completed", error: str | None = None) -> Notification:
    turn: dict[str, Any] = {"id": "t", "items": [], "status": status}
    if error is not None:
        turn["error"] = {"message": error}
    return notification("turn/completed", {"threadId": THREAD, "turn": turn})


class FakeTurn:
    """One turn whose notifications are queued by a script, by a steer, or by an interrupt."""

    def __init__(self, world: "FakeWorld") -> None:
        self._world = world
        self._queue: asyncio.Queue[Notification] = asyncio.Queue()
        self.ended = False
        self.after_steer: list[Notification] = []
        # The turn ends just as a steer goes out, so the steer is refused the way the runtime refuses it.
        self.ends_on_steer = False

    def emit(self, *notifications: Notification) -> None:
        for each in notifications:
            self._queue.put_nowait(each)

    async def stream(self) -> AsyncIterator[Notification]:
        while True:
            each = await self._queue.get()
            yield each
            if each.method == "turn/completed":
                self.ended = True
                return

    async def steer(self, input: str) -> None:
        self._world.steers.append(input)
        if self.ended:
            raise InvalidRequestError(-32600, "no active turn to steer")
        self.emit(*self.after_steer)
        if self.ends_on_steer:
            raise InvalidRequestError(-32600, "no active turn to steer")

    async def interrupt(self) -> None:
        self._world.interrupts += 1
        self.emit(turn_completed("interrupted"))


Script = Callable[[FakeTurn], None]


def answers(text: str) -> Script:
    return lambda turn: turn.emit(message(text), turn_completed())


def keeps_working(turn: FakeTurn) -> None:
    turn.emit(started(command()))


class FakeThread:
    def __init__(self, world: "FakeWorld", thread_id: str) -> None:
        self.id = thread_id
        self._world = world

    async def turn(self, input: Any, **options: Any) -> FakeTurn:
        self._world.turns.append((input, options))
        turn = FakeTurn(self._world)
        self._world.scripts.pop(0)(turn)
        return turn

    async def read(self) -> SimpleNamespace:
        return SimpleNamespace(thread=SimpleNamespace(path=self._world.rollout))


class FakeWorld:
    """Stands in for AsyncCodex and records what the adapter asked of it."""

    def __init__(self, *scripts: Script) -> None:
        self.scripts = list(scripts)
        self.configs: list[CodexConfig | None] = []
        self.thread_options: list[dict[str, Any]] = []
        self.resumed: list[str] = []
        self.turns: list[tuple[Any, dict[str, Any]]] = []
        self.steers: list[str] = []
        self.interrupts = 0
        self.closed = 0
        self.rollout: str | None = None
        self.start_failure: Exception | None = None
        self.thread_failure: Exception | None = None
        self.account: GetAccountResponse | Exception = GetAccountResponse(requires_openai_auth=False)

    def codex(self, config: CodexConfig | None = None) -> Any:
        world = self
        world.configs.append(config)

        class Codex:
            async def __aenter__(self) -> "Codex":
                if world.start_failure is not None:
                    raise world.start_failure
                return self

            async def __aexit__(self, *_: object) -> None:
                world.closed += 1

            async def account(self) -> GetAccountResponse:
                if isinstance(world.account, Exception):
                    raise world.account
                return world.account

            async def thread_start(self, **options: Any) -> FakeThread:
                if world.thread_failure is not None:
                    raise world.thread_failure
                world.thread_options.append(options)
                return FakeThread(world, THREAD)

            async def thread_resume(self, thread_id: str, **options: Any) -> FakeThread:
                world.resumed.append(thread_id)
                world.thread_options.append(options)
                return FakeThread(world, thread_id)

        return Codex()


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> Callable[..., FakeWorld]:
    def install(*scripts: Script) -> FakeWorld:
        fake = FakeWorld(*scripts)
        monkeypatch.setattr(adapter, "AsyncCodex", fake.codex)
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


async def collect(run: adapter.CodexRun) -> list[AgentEvent]:
    return [each async for each in run.events()]


async def test_a_thread_gets_the_workspace_trusted_telemetry_off_and_no_agents_md(
    world: Callable[..., FakeWorld], tmp_path: Path
) -> None:
    fake = world(answers("done"))

    run = await CodexIntelligence().start(request(tmp_path, reasoning_effort="max"))
    result = await run.result()

    assert (result.text, result.session_id, result.error) == ("done", THREAD, None)
    [config] = fake.configs
    assert config is not None
    assert config.config_overrides == (
        "analytics.enabled=false",
        'otel.metrics_exporter="none"',
        "feedback.enabled=false",
    )
    cwd = str(tmp_path.resolve())
    assert fake.thread_options == [
        {
            "cwd": cwd,
            "model": "gpt-6.1-sol",
            "sandbox": Sandbox.full_access,
            "approval_mode": ApprovalMode.deny_all,
            "config": {
                "model_reasoning_summary": "detailed",
                "project_doc_max_bytes": 0,
                "projects": {cwd: {"trust_level": "trusted"}},
            },
        }
    ]
    [(content, options)] = fake.turns
    assert content == [TextInput("Do the work.")]
    assert options["effort"] == ReasoningEffort.max
    assert options["summary"].root.value == "detailed"
    assert "output_schema" not in options
    assert fake.closed == 1


async def test_without_a_workspace_the_agent_works_in_the_state_directory_and_no_effort_sends_none(
    world: Callable[..., FakeWorld], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(adapter, "state_directory", lambda provider: tmp_path / provider)
    fake = world(answers("done"))

    await (await CodexIntelligence().start(request(reasoning_effort=None))).result()

    assert fake.thread_options[0]["cwd"] == str((tmp_path / "codex").resolve())
    assert "effort" not in fake.turns[0][1]


async def test_skills_are_copied_into_the_project_skills_without_removing_others(
    world: Callable[..., FakeWorld], tmp_path: Path
) -> None:
    world(answers("done"))
    skills = tmp_path / "skills"
    (skills / "reaching").mkdir(parents=True)
    (skills / "reaching" / "SKILL.md").write_text("new", encoding="utf-8")
    (skills / "notes").mkdir()
    work = tmp_path / "work"
    kept = work / ".agents" / "skills"
    (kept / "other").mkdir(parents=True)
    (kept / "other" / "SKILL.md").write_text("other", encoding="utf-8")
    (kept / "reaching").mkdir()
    (kept / "reaching" / "SKILL.md").write_text("old", encoding="utf-8")

    await (await CodexIntelligence().start(request(work, skill_directories=[skills, tmp_path / "missing"]))).result()

    assert (kept / "reaching" / "SKILL.md").read_text(encoding="utf-8") == "new"
    assert (kept / "other" / "SKILL.md").read_text(encoding="utf-8") == "other"
    assert not (kept / "notes").exists()


async def test_images_are_local_image_inputs_on_the_first_turn(world: Callable[..., FakeWorld], tmp_path: Path) -> None:
    image = tmp_path / "shot.png"
    fake = world(answers("done"))

    await (await CodexIntelligence().start(request(images=[image]))).result()

    assert fake.turns[0][0] == [TextInput("Do the work."), LocalImageInput(str(image))]


async def test_notifications_become_agent_events_ending_in_one_terminal(world: Callable[..., FakeWorld]) -> None:
    failing = command() | {"id": "exec-2", "commandActions": [{"command": "false", "type": "unknown"}]}

    def script(turn: FakeTurn) -> None:
        turn.emit(
            completed({"id": "rs_0", "type": "reasoning", "summary": [], "content": []}),
            completed({"id": "rs_1", "type": "reasoning", "summary": ["Plan.", "Run it."], "content": []}),
            started(command()),
            usage(10, 2, 12),
            usage(10, 2, 12),
            completed(command(0, "x" * 2000)),
            started(failing),
            completed(failing | {"status": "failed", "exitCode": 1, "aggregatedOutput": "starting\nno such file\n"}),
            completed({"id": "msg_0", "type": "agentMessage", "text": ""}),
            usage(20, 4, 36),
            message("done"),
            turn_completed(),
        )

    world(script)

    run = await CodexIntelligence().start(request())
    events = await collect(run)

    assert [each.kind for each in events] == [
        "reasoning",
        "tool_call",
        "usage",
        "tool_result",
        "tool_call",
        "tool_result",
        "usage",
        "message",
        "terminal",
    ]
    reasoning, call, first_usage, outcome, _, failure, second_usage, said, terminal = events
    assert reasoning.text == "Plan.\n\nRun it."
    assert call.text == 'commandExecution {"command": "echo hi", "cwd": "/work"}'
    assert call.data == {
        "tool_call_id": "exec-1",
        "tool_name": "commandExecution",
        "arguments": {"command": "echo hi", "cwd": "/work"},
    }
    assert call.time.timestamp() == 1.0
    assert outcome.data == {
        "tool_call_id": "exec-1",
        "tool_name": "commandExecution",
        "success": True,
        "result": "x" * 2000,
    }
    assert len(outcome.text) < 2000
    assert (failure.data["success"], failure.data["error"]) == (False, "no such file")
    assert first_usage.data == {
        "model": "gpt-6.1-sol",
        "input_tokens": 10,
        "fresh_input_tokens": 7,
        "output_tokens": 2,
        "cache_read_tokens": 3,
        "cache_write_tokens": 0,
        "reasoning_tokens": 1,
    }
    assert second_usage.data["input_tokens"] == 20
    assert said.text == "done"
    assert terminal.text == "done"
    assert terminal.data["session_id"] == THREAD
    assert await collect(run) == events


async def test_a_collab_agent_call_names_the_agent_it_speaks_to(world: Callable[..., FakeWorld]) -> None:
    item = {
        "id": "call-1",
        "type": "collabAgentToolCall",
        "tool": "spawnAgent",
        "prompt": "Look around.",
        "receiverThreadIds": ["child-1"],
        "senderThreadId": THREAD,
        "agentsStates": {},
        "status": "inProgress",
    }
    world(lambda turn: turn.emit(started(item), completed(item | {"status": "completed"}), turn_completed()))

    call, outcome, _ = await collect(await CodexIntelligence().start(request()))

    assert (call.data["tool_name"], call.data["agent_id"]) == ("spawnAgent", "child-1")
    assert call.data["arguments"]["prompt"] == "Look around."
    assert (outcome.data["agent_id"], outcome.data["success"]) == ("child-1", True)


async def test_a_steer_lands_in_the_turn_in_flight(world: Callable[..., FakeWorld]) -> None:
    def script(turn: FakeTurn) -> None:
        keeps_working(turn)
        turn.after_steer = [message("done KIWI"), turn_completed()]

    fake = world(script)

    run = await CodexIntelligence().start(request())
    await run.steer("End with KIWI.")
    result = await run.result()

    assert fake.steers == ["End with KIWI."]
    assert len(fake.turns) == 1
    assert result.text == "done KIWI"


async def test_a_steer_that_meets_the_end_of_a_turn_goes_on_in_a_turn_of_its_own(
    world: Callable[..., FakeWorld],
) -> None:
    def script(turn: FakeTurn) -> None:
        keeps_working(turn)
        turn.after_steer = [message("first"), turn_completed()]
        turn.ends_on_steer = True

    fake = world(script, answers("second"))

    run = await CodexIntelligence().start(request())
    await run.steer("One more thing.")
    result = await run.result()

    assert [content for content, _ in fake.turns] == [[TextInput("Do the work.")], "One more thing."]
    assert result.text == "second"


async def test_a_steer_after_the_run_ended_names_the_session_to_resume(world: Callable[..., FakeWorld]) -> None:
    world(answers("done"))

    run = await CodexIntelligence().start(request())
    await run.result()
    with pytest.raises(RealityCheckError) as failure:
        await run.steer("Too late.")

    assert failure.value.code == "agent-run-finished"
    assert THREAD in failure.value.remedy


async def test_cancel_interrupts_the_turn_and_keeps_the_session(world: Callable[..., FakeWorld]) -> None:
    fake = world(keeps_working)

    run = await CodexIntelligence().start(request())
    await run.cancel()
    result = await run.result()

    assert result.cancelled
    assert result.error is None
    assert result.session_id == THREAD
    assert fake.interrupts == 1
    assert fake.closed == 1
    assert (await collect(run))[-1].kind == "terminal"


async def test_a_run_past_its_timeout_is_interrupted_and_names_the_session(world: Callable[..., FakeWorld]) -> None:
    fake = world(keeps_working)

    run = await CodexIntelligence().start(request().model_copy(update={"timeout_seconds": 0.05}))
    result = await run.result()

    assert result.error is not None
    assert "0.05 seconds" in result.error
    assert THREAD in result.error
    assert result.session_id == THREAD
    assert fake.interrupts == 1


async def test_a_failed_turn_is_the_result_s_error(world: Callable[..., FakeWorld]) -> None:
    world(lambda turn: turn.emit(turn_completed("failed", "Unsupported value: 'none'")))

    result = await (await CodexIntelligence().start(request())).result()

    assert result.error == "Unsupported value: 'none'"
    assert not result.cancelled


async def test_a_thread_that_does_not_start_is_the_result_s_error_and_the_runtime_still_closes(
    world: Callable[..., FakeWorld],
) -> None:
    fake = world()
    fake.thread_failure = RuntimeError("no rollout found")

    run = await CodexIntelligence().start(request())
    result = await run.result()

    assert result.error == "RuntimeError: no rollout found"
    assert fake.closed == 1
    assert [each.kind for each in await collect(run)] == ["terminal"]


async def test_a_runtime_that_does_not_start_fails_the_start(world: Callable[..., FakeWorld]) -> None:
    fake = world()
    fake.start_failure = FileNotFoundError("codex")

    with pytest.raises(RealityCheckError) as failure:
        await CodexIntelligence().start(request())

    assert failure.value.code == "codex-unavailable"


async def test_mcp_servers_are_refused_before_a_runtime_starts(world: Callable[..., FakeWorld]) -> None:
    fake = world()

    with pytest.raises(RealityCheckError) as failure:
        await CodexIntelligence().start(request(mcp_servers={"dtu": McpServer(command="dtu")}))

    assert failure.value.code == "mcp-not-supported"
    assert failure.value.message == "The codex agent provider does not take MCP servers."
    assert fake.configs == []


async def test_a_resumed_run_resumes_the_thread_and_copies_its_rollout(
    world: Callable[..., FakeWorld], tmp_path: Path
) -> None:
    fake = world(answers("again"))
    rollout = tmp_path / "rollout.jsonl"
    rollout.write_text('{"type": "session_meta"}\n', encoding="utf-8")
    fake.rollout = str(rollout)

    result = await (
        await CodexIntelligence().start(request(resume="earlier", session_directory=tmp_path / "session"))
    ).result()

    assert fake.resumed == ["earlier"]
    assert result.session_id == "earlier"
    assert (tmp_path / "session" / "earlier.jsonl").read_text(encoding="utf-8") == '{"type": "session_meta"}\n'


SCHEMA = {
    "type": "object",
    "properties": {
        "score": {"type": "integer", "minimum": 0, "maximum": 100},
        "note": {"type": "string"},
    },
    "required": ["score"],
    "additionalProperties": False,
}


async def test_an_output_schema_is_enforced_strictly_and_its_added_nulls_dropped(
    world: Callable[..., FakeWorld],
) -> None:
    fake = world(answers('{"score": 80, "note": null}'))

    result = await (await CodexIntelligence().start(request(output_schema=SCHEMA))).result()

    assert result.output == {"score": 80}
    assert result.error is None
    strict = fake.turns[0][1]["output_schema"]
    assert strict == to_strict(SCHEMA)
    assert strict["required"] == ["score", "note"]
    assert strict["properties"]["note"] == {"anyOf": [{"type": "string"}, {"type": "null"}]}


async def test_an_invalid_answer_is_sent_back_and_the_corrected_one_is_the_output(
    world: Callable[..., FakeWorld],
) -> None:
    fake = world(answers('{"score": 120, "note": null}'), answers('{"score": 90, "note": "ok"}'))

    result = await (await CodexIntelligence().start(request(output_schema=SCHEMA))).result()

    assert result.output == {"score": 90, "note": "ok"}
    assert len(fake.turns) == 2
    assert "does not match the schema" in fake.turns[1][0]
    assert fake.turns[1][1]["output_schema"] == to_strict(SCHEMA)


async def test_no_valid_answer_after_the_retries_is_the_result_s_error(world: Callable[..., FakeWorld]) -> None:
    fake = world(answers("not json"), answers("not json"), answers("[1]"))

    result = await (await CodexIntelligence().start(request(output_schema=SCHEMA))).result()

    assert result.output is None
    assert result.error == "No valid submission after 2 retries: the final message is not a JSON object"
    assert len(fake.turns) == 3


@pytest.mark.parametrize(
    ("account", "code"),
    [
        (RuntimeError("bad config"), "codex-unavailable"),
        (GetAccountResponse(requires_openai_auth=True), "codex-not-signed-in"),
    ],
)
async def test_preflight_names_a_runtime_that_does_not_start_and_a_missing_sign_in(
    world: Callable[..., FakeWorld], account: GetAccountResponse | Exception, code: str
) -> None:
    fake = world()
    fake.account = account

    with pytest.raises(RealityCheckError) as failure:
        CodexIntelligence().preflight()

    assert failure.value.code == code
    assert fake.configs[0] is not None
    assert "analytics.enabled=false" in fake.configs[0].config_overrides


def test_preflight_passes_when_signed_in(world: Callable[..., FakeWorld]) -> None:
    world()

    CodexIntelligence().preflight()

    assert CodexIntelligence().steering == "mid-turn"
    assert CodexIntelligence().implementation.startswith("openai-codex ")
