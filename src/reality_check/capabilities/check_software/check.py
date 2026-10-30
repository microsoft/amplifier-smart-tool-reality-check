"""Check software: an agent uses the software as a user does, gathers evidence, and writes a report."""

import asyncio
from collections.abc import AsyncIterator
import contextlib
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
from string import Template
import subprocess
import sys
import threading
from typing import IO, Any, Literal, Protocol

from filelock import Timeout
import platformdirs
from pydantic import BaseModel
import yaml

from reality_check.capabilities.check_software.constants import (
    ASK_FIRST,
    COMPUTER_USE_ENABLED,
    COMPUTER_USE_NOT_INSTALLED,
    COMPUTER_USE_OFF,
    COMPUTER_USE_UNSUPPORTED,
    EARLIER_EVIDENCE,
    EVIDENCE_DIRECTORY,
    KEEP_RUNNING,
    NAMED_FILES,
    NO_ACCESSIBILITY_TREE,
    PREVIOUS_CHECKS,
    TARGET_FROM_REQUEST,
    WRAP_UP,
)
from reality_check.capabilities.check_software.intelligence_models import require_allowed
from reality_check.capabilities.check_software.record import (
    EVENTS,
    EVIDENCE,
    PROCESS_LOG,
    SESSION,
    alive,
    check_state,
    load_record,
    process_started,
    read_events,
    write_record,
)
from reality_check.capabilities.check_software.registry import register_project
from reality_check.capabilities.computer_use.prepare import ComputerUse, NotInstalled, prepare_computer_use
from reality_check.capabilities.computer_use.target import Unavailable
from reality_check.core.skill import DISTRIBUTION, skill_directory
from reality_check.intelligence.interface import AgentRun, Intelligence, resolve_agent_provider, select_intelligence
from reality_check.intelligence.schemas import IMAGE_MEDIA_TYPES, AgentEvent, AgentRequest, AgentResult, HostWorkspace
from reality_check.schemas import (
    AGENT_PROVIDERS,
    DEFAULT_CHECKS_DIRECTORY,
    DEFAULT_INTELLIGENCE_MODELS,
    DEFAULT_INTELLIGENCE_REASONING_EFFORT,
    DEFAULT_ORIGIN,
    DEFAULT_TIMEOUT_SECONDS,
    AgentProvider,
    AskFirst,
    CheckEvent,
    CheckEventKind,
    CheckRecord,
    CheckResult,
    CheckStatus,
    CheckTimeoutError,
    CheckUsage,
    RealityCheckError,
    ReasoningEffort,
)

HERE = Path(__file__).parent
# The skills under the package's `skills/` directory that every check's agent gets.
CHECKING_SKILLS = ("reaching-software", "using-software", "using-computer-use", "gathering-evidence")
DTU_SKILL = "digital-twin-universe"
DTU_COMMAND = "digital-twin-universe"
# Skills made at run time, outside the project the agent works in.
SKILLS_CACHE_DIRECTORY = platformdirs.user_cache_path(DISTRIBUTION, appauthor=False) / "skills"
# How often the process running a check looks for steering messages and a cancel from other processes, and a
# detached check's handle for its events.
POLL_SECONDS = 1.0
# The agent's own timeout outlasts the check's, so the check is what stops it and the session drains whole.
AGENT_TIMEOUT_GRACE_SECONDS = 60
# The share of its time after which a check tells its agent to stop testing and write its report.
WRAP_UP_FRACTION = 0.85
WRAP_UP_ORIGIN = "reality-check"
SHORTENED_LENGTH = 500
MAX_NAMED_FILES = 20
# What starts a detached check, given its request on stdin. Tests swap it for a command that fakes the agent.
BACKGROUND_COMMAND = [sys.executable, "-m", "reality_check.capabilities.check_software.background"]
IMAGES = "images"
# The parts of the record the `started` event repeats, so the events alone say what was asked and how.
STARTED_FIELDS = {
    "request",
    "target",
    "resume",
    "previous_checks",
    "ask_first",
    "keep_running",
    "agent_provider",
    "model",
    "reasoning_effort",
    "origin",
    "images",
    "pid",
    "detached",
}


class CheckRun(Protocol):
    """A running check: its events, a way to talk to its agent, and how it ended."""

    check_id: str
    directory: Path

    def events(self) -> AsyncIterator[CheckEvent]:
        """Every event from the start, then live ones until the check ends with `finished` or `failed`."""
        ...

    async def steer(self, message: str) -> None:
        """Send a message to the agent while it works; a `steered` event shows when it is delivered."""
        ...

    async def cancel(self) -> None:
        """End the check and wait for it to stop; its session can still be resumed."""
        ...

    async def result(self) -> CheckResult:
        """Wait for the check to end; raises the RealityCheckError a `failed` event carries."""
        ...


class DetachedCheckRequest(BaseModel):
    """What `check_software` hands the process a detached check runs in; its paths are resolved."""

    request: str
    target: str | None
    resume: str | None
    previous_checks: list[Path] | None
    ask_first: AskFirst
    keep_running: bool
    checks_directory: Path
    agent_provider: AgentProvider | None
    model: str | None
    # Any string, so one that is not a reasoning effort fails in that process with the same error as in this one.
    reasoning_effort: str | None
    timeout_seconds: int | None
    images: list[Path] | None
    origin: str


class InProcessCheckRun:
    """A check whose agent this process runs."""

    def __init__(
        self,
        record: CheckRecord,
        directory: Path,
        intelligence: Intelligence,
        request: AgentRequest,
        timeout_seconds: int | None,
        next_command: str,
        computer_use: ComputerUse | NotInstalled | Unavailable,
    ) -> None:
        self.check_id = record.check_id
        self.directory = directory
        self._record = record
        self._intelligence = intelligence
        self._request = request
        self._timeout_seconds = timeout_seconds
        self._next = next_command
        self._computer_use = computer_use
        self._preparing: asyncio.Future[ComputerUse | NotInstalled | Unavailable] | None = None
        self._events: list[CheckEvent] = []
        # Replaced on every append, so a reader waits on the one current when it ran out of events.
        self._appended = asyncio.Event()
        self._agent: AgentRun | None = None
        self._agent_started = asyncio.Event()
        # Steering messages and who sent them, waiting for the agent to run.
        self._pending: list[tuple[str, str]] = []
        self._cancelling = False
        self._cancel_task: asyncio.Task[None] | None = None
        started = {
            "directory": str(directory),
            **record.model_dump(mode="json", include=STARTED_FIELDS),
            "timeout_seconds": timeout_seconds,
            "checks_directory": str(directory.parent),
            "implementation": intelligence.implementation,
            "agent_request": request.model_dump(mode="json", exclude={"output_schema"}),
        }
        self._emit("started", f"Check {self.check_id} started in {directory}.", started)
        self._task = asyncio.create_task(self._drive())

    def events(self) -> AsyncIterator[CheckEvent]:
        """Every event from the start, then live ones until the check ends with `finished` or `failed`."""
        return self._replay()

    async def steer(self, message: str) -> None:
        """Send a message to the agent while it works, as from whoever started the check."""
        if self._task.done():
            raise _not_running(self.check_id, self._record.status)
        if self._agent is None or self._pending:
            self._pending.append((message, self._record.origin))
            return
        await self._deliver(message, self._record.origin)

    async def cancel(self) -> None:
        """End the check and wait for it to stop; its session can still be resumed."""
        self._request_cancel()
        await asyncio.wait([self._task])

    async def result(self) -> CheckResult:
        """Wait for the check to end; raises the RealityCheckError a `failed` event carries."""
        return await asyncio.shield(self._task)

    async def running(self) -> None:
        """Return once the agent runs or the check has ended; raises the RealityCheckError of a check that failed."""
        started = asyncio.ensure_future(self._agent_started.wait())
        await asyncio.wait([started, self._task], return_when=asyncio.FIRST_COMPLETED)
        started.cancel()
        if self._task.done() and not self._task.cancelled():
            error = self._task.exception()
            if isinstance(error, RealityCheckError):
                raise error

    async def _replay(self) -> AsyncIterator[CheckEvent]:
        index = 0
        while True:
            appended = self._appended
            while index < len(self._events):
                event = self._events[index]
                index += 1
                yield event
                if event.kind in ("finished", "failed"):
                    return
            if self._task.done():
                return
            await appended.wait()

    async def _drive(self) -> CheckResult:
        try:
            result = await self._run()
        except RealityCheckError as error:
            if self._record.status == "running":
                self._end("failed", None)
            data: dict[str, Any] = {"code": error.code, "message": error.message, "remedy": error.remedy}
            if isinstance(error, CheckTimeoutError):
                data["result"] = error.result.model_dump(mode="json")
            self._emit("failed", str(error), data)
            raise
        finally:
            self._appended.set()
        where = (
            f"the report is in {self._report_path}"
            if self._report_path.is_file()
            else f"there is no report; resume it with `{self._next}`"
        )
        self._emit("finished", f"Check {result.status}; {where}.", result.model_dump(mode="json"))
        return result

    async def _run(self) -> CheckResult:
        deadline = None if self._timeout_seconds is None else asyncio.get_running_loop().time() + self._timeout_seconds
        watcher = asyncio.create_task(self._watch())
        wrap_up = asyncio.create_task(self._wrap_up(self._timeout_seconds)) if self._timeout_seconds else None
        forward: asyncio.Task[None] | None = None
        timed_out = False
        try:
            try:
                async with asyncio.timeout_at(deadline):
                    agent = await self._intelligence.start(self._request)
                    self._agent = agent
                    self._agent_started.set()
                    self._note_session()
                    forward = asyncio.create_task(self._forward(agent))
                    if self._cancelling:
                        self._request_cancel()
                    outcome = await agent.result()
            except TimeoutError:
                timed_out = True
                outcome = await self._stop_after_timeout()
            if forward is not None:
                await forward
            if self._cancel_task is not None:
                await self._cancel_task
        finally:
            watcher.cancel()
            if wrap_up is not None:
                wrap_up.cancel()
            await self._release_computer_use()
        if timed_out:
            report = self._report(outcome.text, "it timed out")
            so_far = (
                f"its report so far is in {self._report_path}" if self._report_path.is_file() else "it wrote no report"
            )
            result = self._finish("timed-out", outcome.session_id, report)
            raise CheckTimeoutError(
                message=f"Check {self.check_id} did not finish within {self._timeout_seconds} seconds; the agent was "
                f"stopped and {so_far}.",
                remedy=f"Go on where it stopped with `{self._next}`, or start it again with a larger timeout.",
                result=result,
            )
        if outcome.cancelled:
            return self._finish("cancelled", outcome.session_id, self._report(outcome.text, "it was cancelled"))
        if outcome.error is not None:
            self._end("failed", outcome.session_id)
            log = self.directory / PROCESS_LOG
            also = f" and {log} for what its process printed" if log.is_file() else ""
            raise RealityCheckError(
                code="agent-failed",
                message=f"The agent running check {self.check_id} failed: {outcome.error}",
                remedy=f"Read {self.directory / EVENTS} for what it did{also}; go on with `{self._next}` when its "
                "session was kept, or start the check again.",
            )
        return self._finish("done", outcome.session_id, self._report(outcome.text, "it ended"))

    async def _enable_installed_computer_use(self) -> None:
        """Make computer use ready once the agent has installed it during the check."""
        if not isinstance(self._computer_use, NotInstalled) or not self._computer_use.executable.is_file():
            return
        self._preparing = asyncio.ensure_future(
            asyncio.to_thread(prepare_computer_use, self.check_id, SKILLS_CACHE_DIRECTORY)
        )
        # Shielded, so a check ending meanwhile still gets what it made ready, and lets go of it.
        self._computer_use = await asyncio.shield(self._preparing)

    async def _release_computer_use(self) -> None:
        """Let go of computer use however the check ends; a failure to stop the daemon never fails the check."""
        if self._preparing is not None:
            with contextlib.suppress(Exception):
                self._computer_use = await self._preparing
        if isinstance(self._computer_use, ComputerUse):
            with contextlib.suppress(Exception):
                await asyncio.to_thread(self._computer_use.release)

    async def _wrap_up(self, timeout_seconds: int) -> None:
        """Tell the agent how little time is left, so it reports what it has before the check stops it."""
        await asyncio.sleep(timeout_seconds * WRAP_UP_FRACTION)
        message = WRAP_UP.substitute(left=_duration(timeout_seconds * (1 - WRAP_UP_FRACTION)))
        if self._agent is None or self._pending:
            self._pending.append((message, WRAP_UP_ORIGIN))
            return
        try:
            await self._deliver(message, WRAP_UP_ORIGIN)
        except RealityCheckError as error:
            self._emit("steered", message, {"error": str(error), "code": error.code, "origin": WRAP_UP_ORIGIN})

    async def _stop_after_timeout(self) -> AgentResult:
        agent = self._agent
        if agent is None:
            return AgentResult(error="The agent did not start in time.")
        await agent.cancel()
        return await agent.result()

    async def _forward(self, agent: AgentRun) -> None:
        async for event in agent.events():
            self._forward_one(event)

    def _forward_one(self, event: AgentEvent) -> None:
        match event.kind:
            case "message":
                self._emit("progress", event.text, event.data, event.time)
            case "reasoning":
                self._emit("reasoning", event.text, event.data, event.time)
            case "tool_call" | "tool_result":
                phase = "call" if event.kind == "tool_call" else "result"
                self._emit("tool", _shorten(event.text), {**event.data, "phase": phase}, event.time)
            case "usage":
                self._record = self._record.model_copy(update={"usage": _added(self._record.usage, event.data)})
                self._emit("usage", event.text, event.data, event.time)
            case "terminal":
                pass

    async def _watch(self) -> None:
        """Act on what other processes wrote to the check's directory, and deliver queued steering messages."""
        steer = self.directory / "steer"
        while True:
            self._note_session()
            if (self.directory / "cancel").exists():
                self._request_cancel()
            await self._enable_installed_computer_use()
            for path in sorted(steer.glob("*.json")):
                note = json.loads(path.read_text(encoding="utf-8"))
                self._pending.append((note["message"], note.get("origin", DEFAULT_ORIGIN)))
                path.unlink()
            while self._agent is not None and self._pending and not self._cancelling:
                message, origin = self._pending.pop(0)
                try:
                    await self._deliver(message, origin)
                except RealityCheckError as error:
                    self._emit("steered", message, {"error": str(error), "code": error.code, "origin": origin})
            await asyncio.sleep(POLL_SECONDS)

    async def _deliver(self, message: str, origin: str) -> None:
        if self._agent is None:
            raise _not_running(self.check_id, self._record.status)
        await self._agent.steer(message)
        self._emit("steered", message, {"steering": self._intelligence.steering, "origin": origin})

    def _request_cancel(self) -> None:
        self._cancelling = True
        if self._agent is not None and self._cancel_task is None:
            self._cancel_task = asyncio.create_task(self._agent.cancel())

    @property
    def _report_path(self) -> Path:
        return self.directory / "report.md"

    def _report(self, text: str, ending: str) -> str:
        """The agent's final message, kept in report.md so a later check can compare.

        Without one, report.md is not made, so an empty file never passes for a report.
        """
        if not text.strip():
            return f"No report: {ending} before the agent wrote one. Resume it with `{self._next}`."
        self._report_path.write_text(text, encoding="utf-8")
        return text

    def _note_session(self) -> None:
        """Keep the session in check.json as soon as it is known, so a killed process leaves a resumable check."""
        session_id = self._agent.session_id if self._agent is not None else None
        if session_id is not None and session_id != self._record.session_id:
            self._record = self._record.model_copy(update={"session_id": session_id})
            write_record(self.directory, self._record)

    def _result(self, status: CheckStatus, session_id: str | None, report: str) -> CheckResult:
        return CheckResult(
            check_id=self.check_id,
            status=status,
            session_id=session_id,
            agent_provider=self._record.agent_provider,
            report=report,
            directory=self.directory,
            next=self._next,
            timeout_seconds=self._timeout_seconds,
            elapsed_seconds=round(
                ((self._record.ended_at or datetime.now(UTC)) - self._record.started_at).total_seconds(), 3
            ),
            usage=self._record.usage,
        )

    def _finish(self, status: CheckStatus, session_id: str | None, report: str) -> CheckResult:
        self._end(status, session_id)
        return self._result(status, session_id, report)

    def _end(self, status: CheckStatus | Literal["failed"], session_id: str | None) -> None:
        self._record = self._record.model_copy(
            update={
                "status": status,
                "ended_at": datetime.now(UTC),
                "session_id": session_id or self._record.session_id,
            }
        )
        write_record(self.directory, self._record)

    def _emit(
        self, kind: CheckEventKind, text: str = "", data: dict[str, Any] | None = None, time: datetime | None = None
    ) -> None:
        event = CheckEvent(check_id=self.check_id, kind=kind, text=text, data=data or {})
        if time is not None:
            event.time = time
        with (self.directory / EVENTS).open("a", encoding="utf-8") as events:
            events.write(json.dumps(event.model_dump(mode="json")) + "\n")
        # Kept with every event, so a reader of check.json sees the check is still moving.
        self._record = self._record.model_copy(update={"last_event": event.time})
        write_record(self.directory, self._record)
        self._events.append(event)
        self._appended.set()
        self._appended = asyncio.Event()


class DetachedCheckRun:
    """A check running in a process of its own, followed through the files that process writes."""

    def __init__(self, check_id: str, directory: Path, origin: str, next_command: str) -> None:
        self.check_id = check_id
        self.directory = directory
        self._origin = origin
        self._next = next_command

    def events(self) -> AsyncIterator[CheckEvent]:
        """Every event from the start, then each as the check's process writes it, until the check ends."""
        return self._follow()

    async def steer(self, message: str) -> None:
        """Send a message to the agent while it works, as from whoever started the check."""
        directory = await asyncio.to_thread(_running_check, self.directory.parent, self.check_id)
        _write_steering(directory, message, self._origin)

    async def cancel(self) -> None:
        """End the check and wait for it to stop; its session can still be resumed."""
        # A check that has ended already needs no stopping.
        with contextlib.suppress(RealityCheckError):
            directory = await asyncio.to_thread(_running_check, self.directory.parent, self.check_id)
            (directory / "cancel").touch()
        async for _ in self._follow():
            pass

    async def result(self) -> CheckResult:
        """Wait for the check to end; raises the RealityCheckError a `failed` event carries, or `check-crashed`."""
        last: CheckEvent | None = None
        async for event in self._follow():
            last = event
        if last is not None and last.kind == "finished":
            return CheckResult.model_validate(last.data)
        if last is not None and last.kind == "failed":
            raise _failure(last.data)
        record = await asyncio.to_thread(load_record, self.directory.parent, self.check_id)
        raise _crashed(record, self.directory, self._next)

    async def _follow(self) -> AsyncIterator[CheckEvent]:
        path = self.directory / EVENTS
        offset = 0
        while True:
            # Looked at before reading, so every event of a check whose process is seen gone is read.
            record = await asyncio.to_thread(load_record, self.directory.parent, self.check_id)
            ended = _process_gone(record)
            events, offset = await asyncio.to_thread(read_events, path, offset)
            for event in events:
                yield event
                if event.kind in ("finished", "failed"):
                    return
            if ended:
                return
            await asyncio.sleep(POLL_SECONDS)


async def check_software(
    request: str,
    target: str | None = None,
    resume: str | None = None,
    previous_checks: list[Path] | None = None,
    ask_first: AskFirst = "when-off",
    keep_running: bool = False,
    checks_directory: Path = DEFAULT_CHECKS_DIRECTORY,
    agent_provider: AgentProvider | None = None,
    model: str | None = None,
    reasoning_effort: ReasoningEffort | None = None,
    timeout_seconds: int | None = DEFAULT_TIMEOUT_SECONDS,
    images: list[Path] | None = None,
    origin: str = DEFAULT_ORIGIN,
    detach: bool = False,
    intelligence: Intelligence | None = None,
) -> CheckRun:
    """Start a check and return its handle once it runs; the work goes on in the background, or in its own process."""
    # Checks run in the caller's working directory, and a detached check's process inherits it. The registry only
    # helps find checks later, so a check still runs when it cannot be written.
    with contextlib.suppress(RealityCheckError, OSError, Timeout):
        register_project(checks_directory, Path.cwd())
    if not detach:
        return await _start(
            request=request,
            target=target,
            resume=resume,
            previous_checks=previous_checks,
            ask_first=ask_first,
            keep_running=keep_running,
            checks_directory=checks_directory,
            agent_provider=agent_provider,
            model=model,
            reasoning_effort=reasoning_effort,
            timeout_seconds=timeout_seconds,
            images=images,
            origin=origin,
            intelligence=intelligence,
            detached=False,
        )
    if intelligence is not None:
        raise RealityCheckError(
            code="detach-with-intelligence",
            message="A detached check runs its agent in its own process, which the intelligence passed cannot reach.",
            remedy="Leave out detach to run the agent with that intelligence here, or leave out the intelligence.",
        )
    detached = DetachedCheckRequest(
        request=request,
        target=target,
        resume=resume,
        previous_checks=[path.resolve() for path in previous_checks] if previous_checks else None,
        ask_first=ask_first,
        keep_running=keep_running,
        checks_directory=checks_directory.resolve(),
        agent_provider=agent_provider,
        model=model,
        reasoning_effort=reasoning_effort,
        timeout_seconds=timeout_seconds,
        images=[path.resolve() for path in images] if images else None,
        origin=origin,
    )
    return await _detach(detached)


async def start_detached(request: DetachedCheckRequest, intelligence: Intelligence | None) -> InProcessCheckRun:
    """Start the check a detached request asks for in this process, which is that check's own."""
    return await _start(**request.model_dump(), intelligence=intelligence, detached=True)


async def _start(
    request: str,
    target: str | None,
    resume: str | None,
    previous_checks: list[Path] | None,
    ask_first: AskFirst,
    keep_running: bool,
    checks_directory: Path,
    agent_provider: AgentProvider | None,
    model: str | None,
    reasoning_effort: ReasoningEffort | None,
    timeout_seconds: int | None,
    images: list[Path] | None,
    origin: str,
    intelligence: Intelligence | None,
    detached: bool,
) -> InProcessCheckRun:
    root = checks_directory.resolve()
    resumed = load_record(root, resume) if resume is not None else None
    if resumed is not None and resumed.session_id is None:
        raise RealityCheckError(
            code="check-not-resumable",
            message=f"Check {resumed.check_id} has no agent session to resume; its status is {resumed.status}.",
            remedy="Resume a check that ended done, cancelled, or timed-out, or start a new check without resume.",
        )
    if resumed is not None and check_state(resumed) == "running":
        # Two processes driving one session would each send it turns the other does not know about.
        raise RealityCheckError(
            code="check-running",
            message=f"Check {resumed.check_id} is still running, in process {resumed.pid}.",
            remedy=f"Steer it with `reality-check steer-check --check-id {resumed.check_id} --message <text>`, cancel "
            f"it with `reality-check cancel-check --check-id {resumed.check_id}`, or wait for it to end.",
        )
    previous = _previous_checks(previous_checks or [])
    sources = _images(images or [])
    if resumed is not None and agent_provider is None:
        agent_provider = resumed.agent_provider
    if resumed is not None and agent_provider != resumed.agent_provider:
        raise RealityCheckError(
            code="resume-other-provider",
            message=f"Check {resumed.check_id} ran on {resumed.agent_provider}, and {agent_provider} was asked for.",
            remedy=f"Resume it on {resumed.agent_provider} by leaving the agent provider out, or start a new check "
            "without resume.",
        )
    injected = intelligence is not None
    if not injected:
        agent_provider = resolve_agent_provider(agent_provider)
    provider: AgentProvider = agent_provider or AGENT_PROVIDERS[0]
    intelligence, model = select_intelligence(intelligence, provider, model, DEFAULT_INTELLIGENCE_MODELS)
    if injected:
        # An injected implementation chooses its own models.
        effort = DEFAULT_INTELLIGENCE_REASONING_EFFORT if reasoning_effort is None else reasoning_effort
    else:
        effort = require_allowed(provider, model, reasoning_effort, sources)
    intelligence.preflight()

    check_id, directory = _new_check_directory(root)
    copied = _copy_images(directory, sources)
    session_directory: Path | None = directory / SESSION
    if resumed is not None:
        kept = root / resumed.check_id / SESSION
        if kept.is_dir():
            # Copied, so each check holds its whole session up to its end and the resumed one is never written to.
            await asyncio.to_thread(shutil.copytree, kept, directory / SESSION, ignore=shutil.ignore_patterns("*.lock"))
        else:
            # A check made before checks kept their session: it is where the agent provider keeps its sessions.
            session_directory = None
    pid = os.getpid()
    record = CheckRecord(
        check_id=check_id,
        request=request,
        target=target,
        resume=resume,
        previous_checks=previous or None,
        ask_first=ask_first,
        keep_running=keep_running,
        agent_provider=provider,
        model=model,
        reasoning_effort=effort,
        timeout_seconds=timeout_seconds,
        pid=pid,
        pid_started=process_started(pid),
        origin=origin,
        images=copied or None,
        detached=detached,
    )
    write_record(directory, record)
    # Decided again on every start, so a check resumed after its caller enabled computer use gets it.
    computer_use = await asyncio.to_thread(prepare_computer_use, check_id, SKILLS_CACHE_DIRECTORY)
    if resumed is not None:
        prompt = _resume_prompt(
            request, directory, root / resumed.check_id, previous, ask_first, keep_running, computer_use
        )
    else:
        prompt = _prompt(request, target, directory, previous, ask_first, keep_running, computer_use)
    agent_request = AgentRequest(
        initial_message=prompt,
        model=model,
        workspace=HostWorkspace(path=Path.cwd()),
        reasoning_effort=effort,
        timeout_seconds=None if timeout_seconds is None else timeout_seconds + AGENT_TIMEOUT_GRACE_SECONDS,
        resume=resumed.session_id if resumed is not None else None,
        skill_directories=[skill_directory() / "skills", _dtu_skill()],
        images=copied,
        session_directory=session_directory,
    )
    return InProcessCheckRun(
        record,
        directory,
        intelligence,
        agent_request,
        timeout_seconds,
        _next_command(check_id, checks_directory),
        computer_use,
    )


def steer_check(
    check_id: str, message: str, checks_directory: Path = DEFAULT_CHECKS_DIRECTORY, origin: str = DEFAULT_ORIGIN
) -> None:
    """Write a steering message for the process running the check to deliver."""
    _write_steering(_running_check(checks_directory.resolve(), check_id), message, origin)


def cancel_check(check_id: str, checks_directory: Path = DEFAULT_CHECKS_DIRECTORY) -> None:
    """Write the cancel the process running the check acts on."""
    directory = _running_check(checks_directory.resolve(), check_id)
    (directory / "cancel").touch()


def _write_steering(directory: Path, message: str, origin: str) -> None:
    steer = directory / "steer"
    steer.mkdir(exist_ok=True)
    name = f"{datetime.now(UTC).strftime('%Y%m%d-%H%M%S-%f')}-{secrets.token_hex(3)}"
    # Written aside and renamed, so the running check never reads half a message.
    partial = steer / f"{name}.tmp"
    partial.write_text(json.dumps({"message": message, "origin": origin}), encoding="utf-8")
    partial.replace(steer / f"{name}.json")


def _running_check(root: Path, check_id: str) -> Path:
    record = load_record(root, check_id)
    state = check_state(record)
    if state == "crashed":
        raise _crashed(record, root / check_id, _next_command(check_id, root))
    if state != "running":
        raise _not_running(check_id, record.status)
    return root / check_id


def _not_running(check_id: str, status: str) -> RealityCheckError:
    return RealityCheckError(
        code="check-not-running",
        message=f"Check {check_id} is not running; it ended {status}.",
        remedy=f"Start a new check with resume={check_id!r} (`--resume {check_id}`) and the message as its request.",
    )


def _crashed(record: CheckRecord, directory: Path, next_command: str) -> RealityCheckError:
    last = record.last_event.isoformat() if record.last_event is not None else "never"
    log = directory / PROCESS_LOG
    read = f"Read {log} for why, then go" if log.is_file() else "Go"
    return RealityCheckError(
        code="check-crashed",
        message=f"Check {record.check_id} is not running: process {record.pid} that ran it is gone; its last event "
        f"was at {last}.",
        remedy=f"{read} on with `{next_command}` and the message as its request.",
    )


def _process_gone(record: CheckRecord) -> bool:
    """Whether the process running the check is gone, so all it wrote is on disk."""
    if record.pid is None:
        return record.status != "running"
    return not alive(record.pid, record.pid_started)


def _failure(data: dict[str, Any]) -> RealityCheckError:
    """The RealityCheckError a `failed` event carries."""
    if data.get("code") == "check-timeout" and "result" in data:
        return CheckTimeoutError(data["message"], data["remedy"], CheckResult.model_validate(data["result"]))
    return RealityCheckError(data["code"], data["message"], data["remedy"])


async def _detach(request: DetachedCheckRequest) -> DetachedCheckRun:
    report = await asyncio.to_thread(_start_process, request)
    if "code" in report:
        raise RealityCheckError(report["code"], report["message"], report["remedy"])
    return DetachedCheckRun(
        report["check_id"],
        Path(report["directory"]),
        request.origin,
        _next_command(report["check_id"], request.checks_directory),
    )


def _start_process(request: DetachedCheckRequest) -> dict[str, Any]:
    """Start the process a detached check runs in, and return what it reports once its agent runs or cannot."""
    process = detached_process(BACKGROUND_COMMAND, subprocess.PIPE, subprocess.PIPE)
    # It only starts the check's own process and exits; waited on here so it leaves no zombie.
    threading.Thread(target=process.wait, daemon=True).start()
    assert process.stdin is not None
    assert process.stdout is not None
    with process.stdin:
        process.stdin.write(request.model_dump_json().encode("utf-8"))
    with process.stdout:
        line = process.stdout.readline()
    if not line:
        return {
            "code": "check-start-failed",
            "message": "The process that runs the check ended before its agent ran, without saying why.",
            "remedy": "Run the check without detach to see why.",
        }
    return json.loads(line)


def detached_process(
    command: list[str], stdin: int | IO[Any], stdout: int | IO[Any], environment: dict[str, str] | None = None
) -> subprocess.Popen[bytes]:
    """Start `command` apart from this process's console, session, and job, so ending them leaves it running."""
    if sys.platform != "win32":
        return _popen(command, stdin, stdout, environment, start_new_session=True)
    # A console of its own without a window, which the agent's processes share, so none of them opens one.
    flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    try:
        # Out of the caller's job as well, since a host may end everything in its job when it exits.
        return _popen(command, stdin, stdout, environment, creationflags=flags | subprocess.CREATE_BREAKAWAY_FROM_JOB)
    except PermissionError:
        # The job allows no breaking away. Hosts built on Node let the children of their children leave it anyway.
        return _popen(command, stdin, stdout, environment, creationflags=flags)


def _popen(
    command: list[str],
    stdin: int | IO[Any],
    stdout: int | IO[Any],
    environment: dict[str, str] | None,
    start_new_session: bool = False,
    creationflags: int = 0,
) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        command,
        stdin=stdin,
        stdout=stdout,
        stderr=subprocess.DEVNULL,
        env=environment,
        start_new_session=start_new_session,
        creationflags=creationflags,
    )


def _images(paths: list[Path]) -> list[Path]:
    resolved = [path.resolve() for path in paths]
    for path in resolved:
        if not path.is_file():
            raise RealityCheckError(
                code="image-not-found",
                message=f"The image {path} is not a file.",
                remedy="Name each image file relative to the working directory, or absolute.",
            )
        if path.suffix.lower() not in IMAGE_MEDIA_TYPES:
            raise RealityCheckError(
                code="image-not-supported",
                message=f"The image {path} is not one the agent can be shown.",
                remedy=f"Pass images of these types: {', '.join(IMAGE_MEDIA_TYPES)}.",
            )
    return resolved


def _copy_images(directory: Path, sources: list[Path]) -> list[Path]:
    """The images copied into the check, so it keeps what its agent was shown."""
    copied: list[Path] = []
    for source in sources:
        target = directory / IMAGES / source.name
        if target in copied:
            target = target.with_name(f"{source.stem}-{len(copied) + 1}{source.suffix}")
        target.parent.mkdir(exist_ok=True)
        shutil.copy2(source, target)
        copied.append(target)
    return copied


def _previous_checks(directories: list[Path]) -> list[Path]:
    resolved = [directory.resolve() for directory in directories]
    for directory in resolved:
        if not directory.is_dir():
            raise RealityCheckError(
                code="previous-check-not-found",
                message=f"The previous check {directory} is not a directory.",
                remedy="Name the directory of each earlier check, relative to the working directory or absolute.",
            )
    return resolved


def _new_check_directory(root: Path) -> tuple[str, Path]:
    """A check_id that sorts by time and is unique across processes, and its directory, made for it alone."""
    while True:
        check_id = f"{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(3)}"
        directory = root / check_id
        try:
            directory.mkdir(parents=True)
        except FileExistsError:
            continue
        (directory / "steer").mkdir()
        (directory / EVIDENCE).mkdir()
        return check_id, directory


def _next_command(check_id: str, checks_directory: Path) -> str:
    command = f'reality-check check-software --resume {check_id} --request "<your answer>"'
    if checks_directory.resolve() != DEFAULT_CHECKS_DIRECTORY.resolve():
        command += f" --checks-directory {_quoted(str(checks_directory.resolve()))}"
    return command


def _quoted(text: str) -> str:
    return f'"{text}"' if re.search(r"\s", text) else text


def _dtu_skill() -> Path:
    """A skills directory holding Digital Twin Universe's skill, which its package ships only as the tool's help."""
    from digital_twin_universe import lib as dtu

    frontmatter = yaml.safe_dump({"name": DTU_SKILL, "description": dtu.load_manifest().description}, width=1000)
    text = f"---\n{frontmatter}---\n\n{dtu.skill()}\n"
    # Named by its content, so a written skill never changes and checks running at once can share it.
    skills = SKILLS_CACHE_DIRECTORY / hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    path = skills / DTU_SKILL / "SKILL.md"
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        partial = path.with_name(f"SKILL.md.{secrets.token_hex(3)}.tmp")
        partial.write_text(text, encoding="utf-8")
        try:
            partial.replace(path)
        except PermissionError:
            # Windows refuses to replace a file another check has open; that file is this same skill.
            partial.unlink()
    return skills


def _dtu_command() -> str:
    """The Digital Twin Universe CLI from this environment, which need not be on the agent's PATH."""
    found = shutil.which(DTU_COMMAND, path=str(Path(sys.executable).parent))
    return _quoted(found) if found else f"{_quoted(sys.executable)} -m digital_twin_universe.cli"


def _install_command() -> str:
    """`install-computer-use` from this environment's CLI, which need not be on the agent's PATH."""
    found = shutil.which(DISTRIBUTION, path=str(Path(sys.executable).parent))
    cli = _quoted(found) if found else f"{_quoted(sys.executable)} -m reality_check.cli"
    return f"{cli} install-computer-use"


def _named_files(*texts: str | None) -> list[Path]:
    """Files the texts name that exist relative to the working directory, best effort."""
    found: list[Path] = []
    for text in texts:
        for token in (text or "").split():
            candidate = token.strip("\"'`,;:()[]{}<>").rstrip(".")
            if not candidate or len(found) >= MAX_NAMED_FILES:
                continue
            with contextlib.suppress(OSError, ValueError):
                path = (Path.cwd() / candidate).resolve()
                if path.is_file() and path not in found:
                    found.append(path)
    return found


def _prompt(
    request: str,
    target: str | None,
    directory: Path,
    previous_checks: list[Path],
    ask_first: AskFirst,
    keep_running: bool,
    computer_use: ComputerUse | NotInstalled | Unavailable,
) -> str:
    files = _named_files(request, target)
    named = NAMED_FILES.substitute(files=_listed(files)) if files else ""
    return Template((HERE / "prompt.md").read_text(encoding="utf-8")).substitute(
        request=request.strip(),
        target=target or TARGET_FROM_REQUEST,
        named_files=named,
        evidence=_evidence_text(directory),
        previous_checks=_previous_checks_text(previous_checks),
        computer_use=_computer_use_text(computer_use),
        ask_first=ASK_FIRST[ask_first],
        keep_running=KEEP_RUNNING[keep_running],
        dtu=_dtu_command(),
        report_format=(HERE / "report-format.md").read_text(encoding="utf-8"),
    )


def _resume_prompt(
    request: str,
    directory: Path,
    resumed: Path,
    previous_checks: list[Path],
    ask_first: AskFirst,
    keep_running: bool,
    computer_use: ComputerUse | NotInstalled | Unavailable,
) -> str:
    return Template((HERE / "resume-prompt.md").read_text(encoding="utf-8")).substitute(
        request=request.strip(),
        evidence=_evidence_text(directory),
        earlier_evidence=EARLIER_EVIDENCE.substitute(
            evidence=resumed / EVIDENCE, relative=f"../{resumed.name}/{EVIDENCE}/"
        ),
        previous_checks=_previous_checks_text(previous_checks),
        computer_use=_computer_use_text(computer_use),
        ask_first=ASK_FIRST[ask_first],
        keep_running=KEEP_RUNNING[keep_running],
        report_format=(HERE / "report-format.md").read_text(encoding="utf-8"),
    )


def _evidence_text(directory: Path) -> str:
    return EVIDENCE_DIRECTORY.substitute(evidence=directory / EVIDENCE, report=directory / "report.md")


def _computer_use_text(computer_use: ComputerUse | NotInstalled | Unavailable) -> str:
    if isinstance(computer_use, ComputerUse):
        command = _quoted(str(computer_use.command))
        text = COMPUTER_USE_ENABLED.substitute(command=command)
        return text if computer_use.accessibility else f"{text} {NO_ACCESSIBILITY_TREE.substitute(command=command)}"
    if isinstance(computer_use, NotInstalled):
        return COMPUTER_USE_NOT_INSTALLED.substitute(
            install=_install_command(), command=_quoted(str(computer_use.command))
        )
    if computer_use.remedy is None:
        return COMPUTER_USE_UNSUPPORTED.substitute(reason=computer_use.reason)
    return COMPUTER_USE_OFF.substitute(reason=computer_use.reason, remedy=computer_use.remedy)


def _previous_checks_text(previous_checks: list[Path]) -> str:
    return PREVIOUS_CHECKS.substitute(directories=_listed(previous_checks)) if previous_checks else ""


def _listed(paths: list[Path]) -> str:
    return "\n".join(f"- `{path}`" for path in paths)


def _duration(seconds: float) -> str:
    """Seconds as a person reads them: whole minutes from two minutes up."""
    if seconds >= 120:
        return f"{round(seconds / 60)} minutes"
    return f"{max(1, round(seconds))} seconds"


def _added(usage: CheckUsage, data: dict[str, Any]) -> CheckUsage:
    """`usage` with one model call's `usage` event added."""
    billing = dict(usage.billing)
    for unit, amount in (data.get("billing") or {}).items():
        billing[unit] = billing.get(unit, 0.0) + amount
    return CheckUsage(
        model_calls=usage.model_calls + 1,
        fresh_input_tokens=usage.fresh_input_tokens + (data.get("fresh_input_tokens") or 0),
        cache_read_tokens=usage.cache_read_tokens + (data.get("cache_read_tokens") or 0),
        cache_write_tokens=usage.cache_write_tokens + (data.get("cache_write_tokens") or 0),
        output_tokens=usage.output_tokens + (data.get("output_tokens") or 0),
        reasoning_tokens=usage.reasoning_tokens + (data.get("reasoning_tokens") or 0),
        billing=billing,
    )


def _shorten(text: str, limit: int = SHORTENED_LENGTH) -> str:
    return text if len(text) <= limit else f"{text[:limit]}... [{len(text) - limit} more characters]"
