"""One run: a task, for one agent provider and model, in its own evaluation environment, judged there."""

from collections.abc import Callable
from datetime import UTC, datetime
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import threading
import time
import traceback
from typing import Any, Literal

from harness import capabilities, collect, grading, providers, usage
from harness.environment import HOME, PROJECT, REPOSITORY_URL, WORK, Environment
from harness.tasks import EvaluationError, Task
from pydantic import BaseModel, Field

from reality_check.schemas import AgentProvider, ReasoningEffort

HARNESS = Path(__file__).resolve().parent
REPOSITORY = HARNESS.parents[1]
TOOL_BIN = f"{HOME}/.local/share/uv/tools/reality-check/bin"
DTU = f"{TOOL_BIN}/digital-twin-universe"
# Time past the capability's own timeout for it to stop and write its record.
CAPABILITY_GRACE_SECONDS = 600
JUDGE_GRACE_SECONDS = 300

RunStatus = Literal["running", "completed", "failed"]


class RunSpec(BaseModel):
    """What one run evaluates, and with which judge."""

    task: str
    agent_provider: AgentProvider
    model: str
    reasoning_effort: ReasoningEffort
    repeat: int
    judge_agent_provider: AgentProvider
    judge_model: str
    judge_reasoning_effort: ReasoningEffort
    judge_timeout_seconds: int
    keep: bool = False


class RunRecord(BaseModel):
    """A run's run.json: what ran, how it ended, how long each step took, its usage, and its score."""

    run_id: str
    spec: RunSpec
    capability: str
    status: RunStatus = "running"
    step: str = ""
    error: str | None = None
    universe_id: str | None = None
    versions: dict[str, Any] = Field(default_factory=dict)
    outcome: dict[str, Any] = Field(default_factory=dict, description="How the capability ended")
    capability_seconds: float | None = Field(
        default=None, description="Wall clock of the capability alone, from its first event to its last"
    )
    timings: dict[str, float] = Field(default_factory=dict, description="Wall clock of each harness step, in seconds")
    usage: dict[str, Any] = Field(default_factory=dict)
    score: float | None = Field(default=None, ge=0, le=100)
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    ended_at: datetime | None = None


class Live:
    """The environments running now, so an interrupted batch can destroy them."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._environments: dict[str, Environment] = {}

    def add(self, environment: Environment) -> None:
        with self._lock:
            self._environments[environment.id] = environment

    def remove(self, environment: Environment) -> None:
        with self._lock:
            self._environments.pop(environment.id, None)

    def destroy_all(self) -> list[str]:
        with self._lock:
            environments = list(self._environments.values())
            self._environments.clear()
        for environment in environments:
            environment.destroy()
        return [environment.id for environment in environments]


class Run:
    """Drives one run, keeping run.json current after every step."""

    def __init__(
        self,
        spec: RunSpec,
        task: Task,
        directory: Path,
        images: Path | None,
        live: Live,
        report: Callable[[str], None],
    ) -> None:
        self.spec = spec
        self.task = task
        self.directory = directory
        self.record = RunRecord(run_id=directory.name, spec=spec, capability=task.capability)
        self._live = live
        self._report = report
        self._environment: Environment | None = None
        self._images = images
        self._since = ""
        self._logs = directory / "logs" / "setup"

    def execute(self) -> RunRecord:
        self.directory.mkdir(parents=True, exist_ok=True)
        self._save()
        try:
            self._step("launch", self._launch)
            self._step("setup", self._setup)
            self._step("place", self._place)
            self._step("baseline", self._baseline)
            self._step("capability", self._capability)
            self._step("collect", self._collect)
            self._step("judge", self._judge)
            self.record.status = "completed"
        except Exception as error:
            self.record.status = "failed"
            self.record.error = f"{type(error).__name__}: {error}"
            (self.directory / "logs").mkdir(parents=True, exist_ok=True)
            (self.directory / "logs" / "harness-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        finally:
            self._finish()
        return self.record

    def _step(self, name: str, action: Callable[[], None]) -> None:
        self.record.step = name
        self._save()
        self._report(f"{self.record.run_id}: {name}")
        started = time.monotonic()
        try:
            action()
        finally:
            self.record.timings[name] = round(time.monotonic() - started, 1)
            self._save()

    @property
    def environment(self) -> Environment:
        if self._environment is None:
            raise EvaluationError("The evaluation environment is not launched.")
        return self._environment

    def _launch(self) -> None:
        self._environment = Environment.launch(self._logs)
        self._live.add(self._environment)
        self.record.universe_id = self._environment.id

    def _setup(self) -> None:
        """The provider's prerequisites, then reality-check, installed the way the README tells a user to."""
        for name in dict.fromkeys([self.spec.agent_provider, self.spec.judge_agent_provider]):
            self.environment.run_checked(f"setup-{name}", providers.provider(name).setup)
        extra = providers.provider(self.spec.agent_provider).extra
        # The checkout uv cloned holds this harness's tasks and answer keys; the installed tool does not need it.
        self.environment.run_checked(
            "install", f"uv tool install {shlex.quote(_install_spec(extra))} && rm -rf {HOME}/.cache/uv/git-v*"
        )
        listed = self.environment.run_checked(
            "versions", f"uv pip list --python {TOOL_BIN}/python --format json", timeout_seconds=60
        )
        self.record.versions = {
            "repository": _repository_version(),
            "environment": {package["name"]: package["version"] for package in json.loads(listed.stdout)},
        }

    def _place(self) -> None:
        """The task's files in the user's project, and its images in the nested daemon."""
        for source, destination in self.task.files.items():
            target = f"{PROJECT}/{destination}"
            self.environment.run_checked(f"place-{source}", f"mkdir -p {shlex.quote(str(Path(target).parent))}")
            self.environment.push(self.task.directory / source, target)
        if self._images is not None:
            self.environment.load_images(self._images)

    def _baseline(self) -> None:
        """The time and the installed packages before the capability, kept on the host so nothing hints at them."""
        self._since = self.environment.run_checked("baseline-time", "date +%s.%N").stdout.strip()
        before = self.directory / "packages" / "before"
        before.mkdir(parents=True, exist_ok=True)
        for name, command in collect.PACKAGE_LISTS.items():
            listed = self.environment.run(f"baseline-{name}", f"sudo {shlex.join(command)}")
            (before / name).write_text(listed.stdout, encoding="utf-8")

    def _capability(self) -> None:
        command = capabilities.command(self.task, self.spec.agent_provider, self.spec.model, self.spec.reasoning_effort)
        result = self.environment.capture(
            "capability", command, timeout_seconds=self.task.timeout_seconds + CAPABILITY_GRACE_SECONDS
        )
        (self.directory / "events.jsonl").write_text(result.stdout, encoding="utf-8")
        (self.directory / "logs" / "capability.stderr").write_text(result.stderr, encoding="utf-8")
        found = capabilities.events(self.directory / "events.jsonl")
        self.record.outcome = capabilities.outcome(self.task, found) | {"exit_code": result.exit_code}
        if len(found) >= 2:
            first = datetime.fromisoformat(found[0]["time"])
            last = datetime.fromisoformat(found[-1]["time"])
            self.record.capability_seconds = round((last - first).total_seconds(), 1)
        self.record.usage["capability"] = usage.summarize(found)

    def _collect(self) -> None:
        found = capabilities.events(self.directory / "events.jsonl")
        provider = providers.provider(self.spec.agent_provider)
        self.environment.run_checked("work", f"sudo mkdir -p {WORK} && sudo chown user {WORK}")
        self.environment.push(HARNESS / "collect.py", f"{WORK}/collect.py")
        config = {
            "since": self._since,
            "out": f"{WORK}/out",
            "check_directory": _in_project(capabilities.output_directory(self.task, found)),
            "sessions": _home(provider.sessions),
            "logs": [_home(path) for path in provider.logs],
        }
        self._push_json(config, f"{WORK}/collect.json")
        self.environment.run_checked(
            "collect",
            f"sudo python3 {WORK}/collect.py {WORK}/collect.json && sudo chown -R user {WORK}/out",
            timeout_seconds=1800,
        )
        with tempfile.TemporaryDirectory() as scratch:
            collected = Path(scratch) / "out"
            self.environment.pull(f"{WORK}/out", collected)
            for child in collected.iterdir():
                destination = self.directory / child.name
                if destination.is_dir() and child.is_dir():
                    shutil.copytree(child, destination, dirs_exist_ok=True)
                else:
                    shutil.move(child, destination)
        packages = self.directory / "packages"
        collect.installed_diff(packages / "before", packages / "after", self.directory / "installed.diff")
        self.environment.container_logs(self.directory / "logs" / "dockerd.log")
        report = self.directory / "check" / "report.md"
        if report.is_file():
            shutil.copy2(report, self.directory / "report.md")

    def _judge(self) -> None:
        found = capabilities.events(self.directory / "events.jsonl")
        record = _in_project(capabilities.output_directory(self.task, found)) or "(the capability left no record)"
        provider = providers.provider(self.spec.judge_agent_provider)
        config = {
            "agent_provider": self.spec.judge_agent_provider,
            "model": self.spec.judge_model,
            "reasoning_effort": self.spec.judge_reasoning_effort,
            "workspace": HOME,
            "timeout_seconds": self.spec.judge_timeout_seconds,
            "output_schema": grading.schema(self.task),
            "prompt": grading.prompt(
                self.task,
                project=PROJECT,
                report=f"{record}/report.md",
                record=record,
                session=f"{WORK}/out/session",
                changes=f"{WORK}/out (changes.json, changes/, installed.diff, logs/)",
                dtu=DTU,
            ),
        }
        self.environment.run_checked("judge-work", f"mkdir -p {WORK}/judge")
        self.environment.push(HARNESS / "judge.py", f"{WORK}/judge/judge.py")
        self._push_json(config, f"{WORK}/judge/config.json")
        spec = _install_spec(provider.extra)
        self.environment.run(
            "judge",
            f"cd {HOME} && uv run --no-project --with {shlex.quote(spec)} python {WORK}/judge/judge.py {WORK}/judge/config.json",
            timeout_seconds=self.spec.judge_timeout_seconds + JUDGE_GRACE_SECONDS,
        )
        judge = self.directory / "judge"
        self.environment.pull(f"{WORK}/judge", judge)
        judge_events = capabilities.events(judge / "events.jsonl")
        self.record.usage["judge"] = usage.summarize(judge_events)
        result_path = judge / "result.json"
        if not result_path.is_file():
            raise EvaluationError(f"The judge wrote no result; see {self._logs / 'judge.log'}.")
        result = json.loads(result_path.read_text(encoding="utf-8"))
        if result.get("session_id"):
            self.environment.pull(f"{_home(provider.sessions)}/{result['session_id']}", judge / "session")
        if result.get("output") is None:
            raise EvaluationError(f"The judge submitted no grade: {result.get('error')}")
        grade = {
            "judge": self.spec.model_dump(include={"judge_agent_provider", "judge_model", "judge_reasoning_effort"})
        }
        grade |= result["output"]
        self.record.score = grading.score(self.task, result["output"])
        grade |= {"score": self.record.score}
        (self.directory / "grade.json").write_text(json.dumps(grade, indent=2), encoding="utf-8")

    def _push_json(self, value: dict[str, Any], destination: str) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            path = Path(scratch) / Path(destination).name
            path.write_text(json.dumps(value, indent=2), encoding="utf-8")
            self.environment.push(path, destination)

    def _finish(self) -> None:
        if self._environment is not None and not self.spec.keep:
            try:
                self._environment.destroy()
            except Exception as error:
                self.record.error = (self.record.error or "") + f" Destroying {self._environment.id} failed: {error}"
            self._live.remove(self._environment)
        self.record.ended_at = datetime.now(UTC)
        self._save()
        kept = f"; kept: digital-twin-universe destroy --id {self.record.universe_id}" if self.spec.keep else ""
        self._report(f"{self.record.run_id}: {self.record.status}, score {self.record.score}{kept}")

    def _save(self) -> None:
        (self.directory / "run.json").write_text(self.record.model_dump_json(indent=2), encoding="utf-8")


def _install_spec(extra: str) -> str:
    return f"reality-check[{extra}] @ git+{REPOSITORY_URL}"


def _home(path: str) -> str:
    return path.replace("~", HOME, 1) if path.startswith("~") else path


def _in_project(path: str | None) -> str | None:
    """A path the capability reported, which is relative to the project it ran in."""
    if path is None:
        return None
    return path if path.startswith("/") else f"{PROJECT}/{path}"


def _repository_version() -> dict[str, Any]:
    def git(*arguments: str) -> str:
        return subprocess.run(["git", "-C", str(REPOSITORY), *arguments], capture_output=True, text=True).stdout.strip()

    return {"commit": git("rev-parse", "HEAD"), "dirty": bool(git("status", "--porcelain"))}
