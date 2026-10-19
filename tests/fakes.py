"""An agent faked by a script, so neither an agent provider nor a network is needed to run a check."""

import asyncio
from collections.abc import AsyncIterator, Callable, Coroutine
import sys
from typing import Any

from reality_check.intelligence.schemas import AgentEvent, AgentEventKind, AgentRequest, AgentResult, Steering
from reality_check.schemas import RealityCheckError

SESSION = "fake-session"


class FakeRun:
    """An agent run whose work is a script, which a cancel interrupts the way a drained session ends."""

    def __init__(self, request: AgentRequest, script: "Script", stopped_text: str) -> None:
        self.request = request
        self.session_id: str | None = SESSION
        self._stopped_text = stopped_text
        self.steered: list[str] = []
        self.steer_arrived = asyncio.Event()
        self._events: list[AgentEvent] = []
        self._appended = asyncio.Event()
        self._cancelled = asyncio.Event()
        self._task = asyncio.create_task(self._drive(script))

    def emit(self, kind: AgentEventKind, text: str = "", data: dict[str, Any] | None = None) -> None:
        self._events.append(AgentEvent(kind=kind, text=text, data=data or {}))
        self._appended.set()
        self._appended = asyncio.Event()

    async def events(self) -> AsyncIterator[AgentEvent]:
        index = 0
        while True:
            appended = self._appended
            while index < len(self._events):
                index += 1
                yield self._events[index - 1]
                if self._events[index - 1].kind == "terminal":
                    return
            await appended.wait()

    async def steer(self, message: str) -> None:
        self.steered.append(message)
        self.steer_arrived.set()

    async def cancel(self) -> None:
        self._cancelled.set()
        await asyncio.wait([self._task])

    async def result(self) -> AgentResult:
        return await asyncio.shield(self._task)

    async def _drive(self, script: "Script") -> AgentResult:
        work = asyncio.create_task(script(self))
        cancelled = asyncio.create_task(self._cancelled.wait())
        await asyncio.wait([work, cancelled], return_when=asyncio.FIRST_COMPLETED)
        cancelled.cancel()
        if work.done():
            result = work.result()
        else:
            work.cancel()
            result = AgentResult(text=self._stopped_text, cancelled=True, session_id=SESSION)
        self.emit("terminal", result.text)
        return result


Script = Callable[[FakeRun], Coroutine[Any, Any, AgentResult]]


class FakeIntelligence:
    def __init__(self, script: Script, stopped_text: str = "Stopped early.") -> None:
        self.implementation = "fake"
        self._stopped_text = stopped_text
        self.steering: Steering = "mid-turn"
        self.runs: list[FakeRun] = []
        self._script = script

    def preflight(self) -> None:
        pass

    async def start(self, request: AgentRequest) -> FakeRun:
        run = FakeRun(request, self._script, self._stopped_text)
        self.runs.append(run)
        return run


class Unavailable(FakeIntelligence):
    """Refuses the model the way the run's own client does when the account does not have it."""

    async def start(self, request: AgentRequest) -> FakeRun:
        raise RealityCheckError("model-not-available", f"{request.model} is not available.", "Pick another.")


class NotConfigured(FakeIntelligence):
    def preflight(self) -> None:
        raise RealityCheckError("gh-not-signed-in", "The GitHub CLI is not signed in.", "Run `gh auth login`.")


def finishes(text: str = "# Report\n\nGo: pass") -> Script:
    async def script(run: FakeRun) -> AgentResult:
        run.emit("message", "Opening the page.")
        run.emit("reasoning", "The page is the target.", {"reasoning_id": "r1"})
        run.emit(
            "tool_call",
            "bash curl http://localhost",
            {"tool_call_id": "call-1", "tool_name": "bash", "arguments": {"command": "curl http://localhost"}},
        )
        run.emit("usage")
        run.emit("tool_result", "x" * 2000, {"tool_call_id": "call-1", "success": True, "result": "x" * 2000})
        return AgentResult(text=text, session_id=SESSION)

    return script


async def waits_for_steering(run: FakeRun) -> AgentResult:
    run.emit("message", "Waiting.")
    await run.steer_arrived.wait()
    return AgentResult(text=f"Did: {run.steered[0]}", session_id=SESSION)


async def prints_and_waits_for_steering(run: FakeRun) -> AgentResult:
    print("printed by the agent", flush=True)
    print("warned by the agent", file=sys.stderr, flush=True)
    return await waits_for_steering(run)


async def works_forever(run: FakeRun) -> AgentResult:
    run.emit("message", "Working.")
    await asyncio.Event().wait()
    raise AssertionError("unreachable")


async def fails(run: FakeRun) -> AgentResult:
    return AgentResult(error="SessionError: model unavailable", session_id=SESSION)


def intelligence(name: str) -> FakeIntelligence:
    """The fake a detached check runs with, by the name a test gives."""
    match name:
        case "unavailable":
            return Unavailable(finishes())
        case "not-configured":
            return NotConfigured(finishes())
        case "finishes":
            return FakeIntelligence(finishes())
        case "prints":
            return FakeIntelligence(prints_and_waits_for_steering)
        case "works-forever":
            return FakeIntelligence(works_forever)
    return FakeIntelligence(waits_for_steering)
