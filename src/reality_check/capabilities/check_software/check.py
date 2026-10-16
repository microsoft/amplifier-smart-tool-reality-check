"""Check software: an agent uses the software as a user does, gathers evidence, and writes a report."""

import asyncio
from collections.abc import AsyncIterator
import contextlib
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
import secrets
import shutil
from string import Template
import sys
from typing import Any, Literal

import platformdirs
import yaml

from reality_check.capabilities.check_software.constants import (
    ASK_FIRST,
    KEEP_RUNNING,
    NAMED_FILES,
    PREVIOUS_CHECKS,
    TARGET_FROM_REQUEST,
)
from reality_check.core.skill import DISTRIBUTION, skill_directory
from reality_check.intelligence.interface import AgentRun, Intelligence, resolve_agent_provider, select_intelligence
from reality_check.intelligence.schemas import AgentEvent, AgentRequest, AgentResult, HostWorkspace
from reality_check.schemas import (
    AGENT_PROVIDERS,
    DEFAULT_CHECKS_DIRECTORY,
    DEFAULT_INTELLIGENCE_MODELS,
    DEFAULT_INTELLIGENCE_REASONING_EFFORT,
    AgentProvider,
    AskFirst,
    CheckEvent,
    CheckEventKind,
    CheckRecord,
    CheckResult,
    CheckStatus,
    CheckTimeoutError,
    RealityCheckError,
    ReasoningEffort,
)

HERE = Path(__file__).parent
CHECK_ID_PATTERN = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{6}$")
# The skills under the package's `skills/` directory that every check's agent gets.
CHECKING_SKILLS = ("reaching-software", "using-software", "gathering-evidence")
DTU_SKILL = "digital-twin-universe"
DTU_COMMAND = "digital-twin-universe"
# Skills made at run time, outside the project the agent works in.
SKILLS_CACHE_DIRECTORY = platformdirs.user_cache_path(DISTRIBUTION, appauthor=False) / "skills"
# How often the process running a check looks for steering messages and a cancel from other processes.
POLL_SECONDS = 1.0
# The agent's own timeout outlasts the check's, so the check is what stops it and the session drains whole.
AGENT_TIMEOUT_GRACE_SECONDS = 60
SHORTENED_LENGTH = 500
MAX_NAMED_FILES = 20


class CheckRun:
    """A running check: its events, a way to talk to its agent, and how it ended."""

    def __init__(
        self,
        record: CheckRecord,
        directory: Path,
        intelligence: Intelligence,
        request: AgentRequest,
        timeout_seconds: int,
        next_command: str,
    ) -> None:
        self.check_id = record.check_id
        self.directory = directory
        self._record = record
        self._intelligence = intelligence
        self._request = request
        self._timeout_seconds = timeout_seconds
        self._next = next_command
        self._events: list[CheckEvent] = []
        # Replaced on every append, so a reader waits on the one current when it ran out of events.
        self._appended = asyncio.Event()
        self._agent: AgentRun | None = None
        self._pending: list[str] = []
        self._cancelling = False
        self._cancel_task: asyncio.Task[None] | None = None
        self._emit("started", f"Check {self.check_id} started in {directory}.", {"directory": str(directory)})
        self._task = asyncio.create_task(self._drive())

    def events(self) -> AsyncIterator[CheckEvent]:
        """Every event from the start, then live ones until the check ends with `finished` or `failed`."""
        return self._replay()

    async def steer(self, message: str) -> None:
        """Send a message to the agent while it works; a `steered` event shows when it is delivered."""
        if self._task.done():
            raise _not_running(self.check_id, self._record.status)
        if self._agent is None or self._pending:
            self._pending.append(message)
            return
        await self._deliver(message)

    async def cancel(self) -> None:
        """End the check and wait for it to stop; its session can still be resumed."""
        self._request_cancel()
        await asyncio.wait([self._task])

    async def result(self) -> CheckResult:
        """Wait for the check to end; raises the RealityCheckError a `failed` event carries."""
        return await asyncio.shield(self._task)

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
        deadline = asyncio.get_running_loop().time() + self._timeout_seconds
        watcher = asyncio.create_task(self._watch())
        forward: asyncio.Task[None] | None = None
        timed_out = False
        try:
            try:
                async with asyncio.timeout_at(deadline):
                    agent = await self._intelligence.start(self._request)
                    self._agent = agent
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
        if timed_out:
            report = self._report(outcome.text, "it timed out")
            so_far = (
                f"its report so far is in {self._report_path}" if self._report_path.is_file() else "it wrote no report"
            )
            result = self._result("cancelled", outcome.session_id, report)
            self._end("failed", outcome.session_id)
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
            raise RealityCheckError(
                code="agent-failed",
                message=f"The agent running check {self.check_id} failed: {outcome.error}",
                remedy=f"Read {self.directory / 'events.jsonl'} for what it did; go on with `{self._next}` when its "
                "session was kept, or start the check again.",
            )
        return self._finish("done", outcome.session_id, self._report(outcome.text, "it ended"))

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
            case "tool_call" | "tool_result":
                phase = "call" if event.kind == "tool_call" else "result"
                self._emit("tool", _shorten(event.text), {**event.data, "phase": phase}, event.time)
            case "usage":
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
            for path in sorted(steer.glob("*.md")):
                self._pending.append(path.read_text(encoding="utf-8"))
                path.unlink()
            while self._agent is not None and self._pending and not self._cancelling:
                message = self._pending.pop(0)
                try:
                    await self._deliver(message)
                except RealityCheckError as error:
                    self._emit("progress", f"A steering message was not delivered: {error}", {"code": error.code})
            await asyncio.sleep(POLL_SECONDS)

    async def _deliver(self, message: str) -> None:
        if self._agent is None:
            raise _not_running(self.check_id, self._record.status)
        await self._agent.steer(message)
        self._emit("steered", message, {"steering": self._intelligence.steering})

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
            _write_record(self.directory, self._record)

    def _result(self, status: CheckStatus, session_id: str | None, report: str) -> CheckResult:
        return CheckResult(
            check_id=self.check_id,
            status=status,
            session_id=session_id,
            agent_provider=self._record.agent_provider,
            report=report,
            directory=self.directory,
            next=self._next,
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
        _write_record(self.directory, self._record)

    def _emit(
        self, kind: CheckEventKind, text: str = "", data: dict[str, Any] | None = None, time: datetime | None = None
    ) -> None:
        event = CheckEvent(check_id=self.check_id, kind=kind, text=text, data=data or {})
        if time is not None:
            event.time = time
        with (self.directory / "events.jsonl").open("a", encoding="utf-8") as events:
            events.write(json.dumps(event.model_dump(mode="json")) + "\n")
        self._events.append(event)
        self._appended.set()
        self._appended = asyncio.Event()


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
    reasoning_effort: ReasoningEffort = DEFAULT_INTELLIGENCE_REASONING_EFFORT,
    timeout_seconds: int = 3600,
    intelligence: Intelligence | None = None,
) -> CheckRun:
    """Start a check and return its handle once it runs; the work goes on in the background."""
    root = checks_directory.resolve()
    resumed = _load_record(root, resume) if resume is not None else None
    if resumed is not None and resumed.session_id is None:
        raise RealityCheckError(
            code="check-not-resumable",
            message=f"Check {resumed.check_id} has no agent session to resume; its status is {resumed.status}.",
            remedy="Resume a check that ended done or cancelled, or start a new check without resume.",
        )
    previous = _previous_checks(previous_checks or [])
    if resumed is not None and agent_provider is None:
        agent_provider = resumed.agent_provider
    if resumed is not None and agent_provider != resumed.agent_provider:
        raise RealityCheckError(
            code="resume-other-provider",
            message=f"Check {resumed.check_id} ran on {resumed.agent_provider}, and {agent_provider} was asked for.",
            remedy=f"Resume it on {resumed.agent_provider} by leaving the agent provider out, or start a new check "
            "without resume.",
        )
    if intelligence is None:
        agent_provider = resolve_agent_provider(agent_provider)
    provider: AgentProvider = agent_provider or AGENT_PROVIDERS[0]
    intelligence, model = select_intelligence(intelligence, provider, model, DEFAULT_INTELLIGENCE_MODELS)
    intelligence.preflight()

    check_id, directory = _new_check_directory(root)
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
        reasoning_effort=reasoning_effort,
    )
    _write_record(directory, record)
    if resumed is not None:
        prompt = _resume_prompt(request, previous, ask_first, keep_running)
    else:
        prompt = _prompt(request, target, previous, ask_first, keep_running)
    agent_request = AgentRequest(
        prompt=prompt,
        model=model,
        workspace=HostWorkspace(path=Path.cwd()),
        reasoning_effort=reasoning_effort,
        timeout_seconds=timeout_seconds + AGENT_TIMEOUT_GRACE_SECONDS,
        resume=resumed.session_id if resumed is not None else None,
        skill_directories=[skill_directory() / "skills", _dtu_skill()],
    )
    return CheckRun(
        record, directory, intelligence, agent_request, timeout_seconds, _next_command(check_id, checks_directory)
    )


def steer_check(check_id: str, message: str, checks_directory: Path = DEFAULT_CHECKS_DIRECTORY) -> None:
    """Write a steering message for the process running the check to deliver."""
    directory = _running_check(checks_directory.resolve(), check_id)
    steer = directory / "steer"
    steer.mkdir(exist_ok=True)
    name = f"{datetime.now(UTC).strftime('%Y%m%d-%H%M%S-%f')}-{secrets.token_hex(3)}"
    # Written aside and renamed, so the running check never reads half a message.
    partial = steer / f"{name}.tmp"
    partial.write_text(message, encoding="utf-8")
    partial.replace(steer / f"{name}.md")


def cancel_check(check_id: str, checks_directory: Path = DEFAULT_CHECKS_DIRECTORY) -> None:
    """Write the cancel the process running the check acts on."""
    directory = _running_check(checks_directory.resolve(), check_id)
    (directory / "cancel").touch()


def _running_check(root: Path, check_id: str) -> Path:
    record = _load_record(root, check_id)
    if record.status != "running":
        raise _not_running(check_id, record.status)
    return root / check_id


def _not_running(check_id: str, status: str) -> RealityCheckError:
    return RealityCheckError(
        code="check-not-running",
        message=f"Check {check_id} is not running; it ended {status}.",
        remedy=f"Start a new check with resume={check_id!r} (`--resume {check_id}`) and the message as its request.",
    )


def _load_record(root: Path, check_id: str) -> CheckRecord:
    path = root / check_id / "check.json"
    if not CHECK_ID_PATTERN.match(check_id) or not path.is_file():
        known = sorted(found.parent.name for found in root.glob("*/check.json"))[-5:]
        raise RealityCheckError(
            code="check-not-found",
            message=f"No check {check_id!r} in {root}.",
            remedy=f"Name a check_id from that directory (the latest: {', '.join(known) or 'none'}), or pass the "
            "checks directory the check was started with.",
        )
    return CheckRecord.model_validate_json(path.read_text(encoding="utf-8"))


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
        return check_id, directory


def _write_record(directory: Path, record: CheckRecord) -> None:
    # Written aside and renamed, because other processes read it while the check runs.
    partial = directory / "check.json.tmp"
    partial.write_text(record.model_dump_json(indent=2), encoding="utf-8")
    partial.replace(directory / "check.json")


def _next_command(check_id: str, checks_directory: Path) -> str:
    command = f'reality-check check-software --resume {check_id} --request "<your answer>"'
    if checks_directory != DEFAULT_CHECKS_DIRECTORY:
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
    previous_checks: list[Path],
    ask_first: AskFirst,
    keep_running: bool,
) -> str:
    files = _named_files(request, target)
    named = NAMED_FILES.substitute(files=_listed(files)) if files else ""
    return Template((HERE / "prompt.md").read_text(encoding="utf-8")).substitute(
        request=request.strip(),
        target=target or TARGET_FROM_REQUEST,
        named_files=named,
        previous_checks=_previous_checks_text(previous_checks),
        ask_first=ASK_FIRST[ask_first],
        keep_running=KEEP_RUNNING[keep_running],
        dtu=_dtu_command(),
    )


def _resume_prompt(request: str, previous_checks: list[Path], ask_first: AskFirst, keep_running: bool) -> str:
    return Template((HERE / "resume-prompt.md").read_text(encoding="utf-8")).substitute(
        request=request.strip(),
        previous_checks=_previous_checks_text(previous_checks),
        ask_first=ASK_FIRST[ask_first],
        keep_running=KEEP_RUNNING[keep_running],
    )


def _previous_checks_text(previous_checks: list[Path]) -> str:
    return PREVIOUS_CHECKS.substitute(directories=_listed(previous_checks)) if previous_checks else ""


def _listed(paths: list[Path]) -> str:
    return "\n".join(f"- `{path}`" for path in paths)


def _shorten(text: str, limit: int = SHORTENED_LENGTH) -> str:
    return text if len(text) <= limit else f"{text[:limit]}... [{len(text) - limit} more characters]"
